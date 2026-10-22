from __future__ import annotations

import logging
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar, Literal, Protocol, Self, TypeGuard

from .exceptions import GenplisM3UGException
from .sorting import (
    FLOAT_RE,
    INT_RE,
    SortSpec,
    SortSpecError,
    format_sort_spec,
    parse_sort_spec,
)
from .types import TagValue, Verbosity

logger = logging.getLogger(__name__)


type RuleValue = str | float | int | bool
type ValueMode = Literal["equality", "text", "numeric"]

EQUALITY_OPERATORS = frozenset({"=", "!="})
TEXT_OPERATORS = frozenset({"~", "^", "$", "%"})
NUMERIC_OPERATORS = frozenset({"<", "<=", ">", ">="})
OPERATORS = EQUALITY_OPERATORS | TEXT_OPERATORS | NUMERIC_OPERATORS


@dataclass(frozen=True, slots=True)
class SourceLocation:
    """The file and line that produced a parsed filter rule."""

    filename: str
    line: int


def is_number(value: object) -> TypeGuard[int | float]:
    return isinstance(value, int | float) and not isinstance(value, bool)


def values_equal(
    tag_value: TagValue, expected: RuleValue, *, case_sensitive: bool = False
) -> bool:
    """Compare a tag value with a rule value.

    tinytag 2.3 stores numeric metadata such as ``track`` and ``disc`` as
    strings inside lists, so compare numeric strings numerically when the
    rule value is a number.
    """
    # bool is a subclass of int, but booleans are not numbers for M3UG rules.
    if isinstance(tag_value, bool) or isinstance(expected, bool):
        return tag_value is expected
    if is_number(expected) and isinstance(tag_value, str):
        if INT_RE.match(tag_value):
            return int(tag_value) == expected
        if FLOAT_RE.match(tag_value):
            return float(tag_value) == expected
    if isinstance(tag_value, str) and isinstance(expected, str) and not case_sensitive:
        return tag_value.casefold() == expected.casefold()
    return tag_value == expected


def normalize(raw: TagValue) -> TagValue:
    if isinstance(raw, list):
        # tinytag transforms some values into lists in its as_dict() method
        length = len(raw)
        if length == 0:
            return None
        elif length == 1:
            return raw[0]
        else:
            return raw
    return raw


def _find_tag(
    tags: Mapping[str, TagValue], normalized_name: str
) -> tuple[bool, TagValue]:
    """Look up a tag by its lower-case name, ignoring key casing."""
    if normalized_name in tags:
        return True, tags[normalized_name]
    for key, value in tags.items():
        if key.lower() == normalized_name:
            return True, value
    return False, None


def get_rating(tags: Mapping[str, TagValue]) -> float | None:
    """Return a rating calculated from known rating alias tags.

    Returns None when no alias tag is present, or when the tags already
    contain a raw ``rating`` tag. In the latter case the raw value is used
    directly, so there is no calculated rating to report.

    Ratings are normalized to a 0 to 5 stars range. If you know of a rating
    tag that is missing, feel free to open an issue with a PR to add support
    for it.
    """
    has_rating, _ = _find_tag(tags, "rating")
    if has_rating:
        return None

    found, raw_fmps_rating = _find_tag(tags, "fmps_rating")
    fmps_rating = normalize(raw_fmps_rating) if found else None
    if isinstance(fmps_rating, list):
        # normalize() only leaves lists with more than one item
        logger.warning("Unexpected fmps_rating as list: %s", fmps_rating)
        fmps_rating = fmps_rating[0]
    if fmps_rating is not None:
        # fmps_rating goes from 0.0 to 1.0 (5 stars)
        if isinstance(fmps_rating, bool):
            logger.warning("Ignoring non-numeric fmps_rating: %r", fmps_rating)
            return None
        try:
            return float(fmps_rating) * 5
        except (TypeError, ValueError):
            logger.warning("Ignoring non-numeric fmps_rating: %r", fmps_rating)
            return None
    return None


def _unescape_quoted(text: str) -> str:
    """Remove quote escaping while preserving other backslashes."""
    result: list[str] = []
    index = 0
    while index < len(text):
        character = text[index]
        if character == "\\" and index + 1 < len(text):
            following = text[index + 1]
            if following in {'"', "'", "\\"}:
                result.append(following)
                index += 2
                continue
        result.append(character)
        index += 1
    return "".join(result)


def _is_quoted(text: str) -> bool:
    return len(text) >= 2 and text[0] == text[-1] and text[0] in {"'", '"'}


def _split_rule_line(text: str) -> list[str]:
    """Split a rule into tag, operator, and the untouched value remainder."""
    parts: list[str] = []
    buffer: list[str] = []
    quote: str | None = None
    escaped = False
    bracket_depth = 0

    for index, character in enumerate(text):
        if quote is not None:
            buffer.append(character)
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == quote:
                quote = None
            continue

        if character in {"'", '"'}:
            quote = character
            buffer.append(character)
        elif character == "[":
            bracket_depth += 1
            buffer.append(character)
        elif character == "]":
            bracket_depth = max(0, bracket_depth - 1)
            buffer.append(character)
        elif character in {" ", "\t"} and bracket_depth == 0:
            if buffer:
                parts.append("".join(buffer))
                buffer = []
                if len(parts) == 2:
                    remainder = text[index:].strip()
                    if remainder:
                        return [*parts, remainder]
                    return parts
        else:
            buffer.append(character)

    if buffer:
        parts.append("".join(buffer))
    return parts


def _split_first_word(text: str) -> tuple[str, str]:
    """Split off the first whitespace-delimited word."""
    parts = text.split(maxsplit=1)
    if len(parts) == 1:
        return parts[0], ""
    return parts[0], parts[1]


def _set_elements(token: str, filename: str, line: int) -> list[str] | None:
    """Return the top-level elements of a bracketed set, or None.

    A token is a set only when it is unquoted, starts with ``[``, ends with
    ``]``, and contains at least one top-level ``|``. Empty elements and
    nested unquoted brackets are errors.
    """
    token = token.strip()
    if len(token) < 2 or token[0] != "[" or token[-1] != "]" or _is_quoted(token):
        return None

    elements: list[str] = []
    buffer: list[str] = []
    quote: str | None = None
    escaped = False
    for character in token[1:-1]:
        if quote is not None:
            buffer.append(character)
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == quote:
                quote = None
            continue
        if character in {'"', "'"}:
            quote = character
            buffer.append(character)
        elif escaped:
            buffer.append(character)
            escaped = False
        elif character == "\\":
            buffer.append(character)
            escaped = True
        elif character == "[":
            raise GenplisM3UGException(
                "Nested unquoted brackets are not allowed", filename, line
            )
        elif character == "]":
            raise GenplisM3UGException(
                "Nested unquoted brackets are not allowed", filename, line
            )
        elif character == "|":
            elements.append("".join(buffer))
            buffer = []
        else:
            buffer.append(character)
    elements.append("".join(buffer))

    if len(elements) == 1:
        return None

    for element in elements:
        if not element.strip():
            raise GenplisM3UGException("Empty set element", filename, line)
    return elements


def _parse_tag_names(
    token: str, filename: str, line: int
) -> tuple[NameNode, ...] | None:
    elements = _set_elements(token, filename, line)
    if elements is None:
        return None
    names: list[NameNode] = []
    for element in elements:
        name = element.strip()
        if (
            not name
            or any(character.isspace() for character in name)
            or any(character in "[]\"'" for character in name)
        ):
            raise GenplisM3UGException(
                f"Invalid tag name in set: {element!r}", filename, line
            )
        names.append(NameNode.build(name, filename, line))
    return tuple(names)


def _parse_value_set(
    token: str,
    mode: ValueMode,
    filename: str,
    line: int,
    *,
    allow_duration: bool = False,
) -> tuple[ValueNode, ...] | None:
    elements = _set_elements(token, filename, line)
    if elements is None:
        return None
    return tuple(
        ValueNode.parse(element, mode, filename, line, allow_duration=allow_duration)
        for element in elements
    )


def _build_rule_set(
    operator: str,
    names: tuple[NameNode, ...],
    values: tuple[ValueNode, ...],
    filename: str,
    line: int,
    case_sensitive: bool,
) -> FilterNode:
    """Build existentially or universally quantified rules for a set."""
    warning_state = [False]
    source = SourceLocation(filename, line)
    leaves = tuple(
        RuleNode.build(
            operator,
            name,
            value,
            filename,
            line,
            case_sensitive,
            warning_state=warning_state,
            source=source,
        )
        for name in names
        for value in values
    )
    if len(leaves) == 1:
        return leaves[0]
    if operator == "!=":
        return AndNode(leaves)
    return OrNode(leaves)


def _normalize_inline_flags(pattern: str) -> str:
    """Turn ``(?-i)`` into a scoped group for Python's regex engine.

    Python only allows inline flag removals inside a scoped group, while M3UG
    and many other regex flavours accept ``(?-i)`` as a switch for the rest of
    the pattern. Wrapping the remainder keeps that behaviour.
    """
    result: list[str] = []
    index = 0
    in_class = False
    closings = 0
    while index < len(pattern):
        character = pattern[index]
        if character == "\\" and index + 1 < len(pattern):
            result.append(pattern[index : index + 2])
            index += 2
            continue
        if character == "[":
            in_class = True
        elif character == "]":
            in_class = False
        if not in_class and pattern.startswith("(?", index):
            match = re.match(r"\(\?([aiLmsux]*)-([aiLmsux]*)\)", pattern[index:])
            if match is not None:
                result.append(f"(?{match.group(1)}-{match.group(2)}:")
                closings += 1
                index += len(match.group(0))
                continue
        result.append(character)
        index += 1
    return "".join(result) + ")" * closings


def parse_duration_literal(text: str) -> float | None:
    """Parse a duration literal into seconds, or return None."""
    value = text.strip()
    if not value:
        return None
    if INT_RE.match(value):
        return float(int(value))

    if re.fullmatch(r"(?:\d+[smhd])+", value):
        total = 0
        for amount, unit in re.findall(r"(\d+)([smhd])", value):
            multiplier = {"s": 1, "m": 60, "h": 3600, "d": 86400}[unit]
            total += int(amount) * multiplier
        return float(total)

    match = re.fullmatch(r"(\d+):(\d{1,2})", value)
    if match is not None:
        minutes, seconds = int(match.group(1)), int(match.group(2))
        if seconds > 59:
            return None
        return float(minutes * 60 + seconds)

    match = re.fullmatch(r"(\d+):(\d{1,2}):(\d{1,2})", value)
    if match is not None:
        hours = int(match.group(1))
        minutes = int(match.group(2))
        seconds = int(match.group(3))
        if minutes > 59 or seconds > 59:
            return None
        return float(hours * 3600 + minutes * 60 + seconds)
    return None


class NameNode:
    def __init__(self, name: str) -> None:
        self.name = name

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, NameNode):
            return NotImplemented
        return self.name == other.name

    def __repr__(self) -> str:
        return f"<Name={self.name}>"

    def __str__(self) -> str:
        return self.name

    @classmethod
    def build(cls, name: object, filename: str, line: int) -> Self:
        if not isinstance(name, str):
            raise GenplisM3UGException(f"Invalid name: {name}", filename, line)
        return cls(name)

    def find(self, tags: Mapping[str, TagValue]) -> tuple[str, TagValue]:
        normalized_name = self.name.lower()
        found, value = _find_tag(tags, normalized_name)
        # handle special cases
        if normalized_name == "rating":
            if found:
                return normalized_name, value
            return normalized_name, get_rating(tags)
        if found:
            return normalized_name, value
        # default case is no match, no value found
        return normalized_name, None


class ValueNode:
    def __init__(self, value: RuleValue, literal: str | None = None) -> None:
        self.value = value
        self.literal = literal

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, ValueNode):
            return NotImplemented
        return self.value == other.value

    def __repr__(self) -> str:
        return f"<Value={self.value}>"

    def __str__(self) -> str:
        if isinstance(self.value, bool):
            return "true" if self.value else "false"
        return str(self.value)

    @classmethod
    def build(cls, value: object, filename: str, line: int) -> Self:
        return cls.parse(value, "equality", filename, line)

    @classmethod
    def parse(
        cls,
        value: object,
        mode: ValueMode,
        filename: str,
        line: int,
        *,
        allow_duration: bool = False,
    ) -> Self:
        if not isinstance(value, str):
            raise GenplisM3UGException(f"Invalid value: {value}", filename, line)

        value = value.strip()
        literal = value
        # quoted values are always literal strings, even if they look numeric
        if _is_quoted(value):
            return cls(_unescape_quoted(value[1:-1]), literal)

        if mode == "text":
            return cls(value, literal)

        if allow_duration:
            duration = parse_duration_literal(value)
            if duration is not None:
                return cls(duration, literal)

        if value == "true":
            return cls(True, literal)
        if value == "false":
            return cls(False, literal)
        if FLOAT_RE.match(value):
            return cls(float(value), literal)
        if INT_RE.match(value):
            return cls(int(value), literal)
        return cls(value, literal)

    def normalize(self, raw: TagValue) -> TagValue:
        return normalize(raw)

    def numeric(self) -> int | float | None:
        if is_number(self.value):
            return self.value
        return None

    def text(self) -> str | None:
        if isinstance(self.value, str):
            return self.value
        return None


class FilterNode(Protocol):
    def apply(self, tags: Mapping[str, TagValue]) -> bool: ...


class RuleNode:
    OPERATOR_NAME: ClassVar[str]
    OPERATOR: ClassVar[str]
    IS_TEXT: ClassVar[bool] = False

    def __init__(
        self,
        name: NameNode,
        value: ValueNode,
        case_sensitive: bool = False,
        *,
        warning_state: list[bool] | None = None,
        source: SourceLocation | None = None,
    ) -> None:
        self.name_node = name
        self.value_node = value
        self.case_sensitive = case_sensitive
        self._warning_state = warning_state if warning_state is not None else [False]
        self.source = source

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, RuleNode):
            return NotImplemented
        if type(self) is not type(other):
            return False
        return (
            self.name_node == other.name_node
            and self.value_node == other.value_node
            and self.case_sensitive == other.case_sensitive
        )

    def __repr__(self) -> str:
        return f"Rule=<{self.name_node}, {self.OPERATOR}, {self.value_node}>"

    def __str__(self) -> str:
        return f"{self.name_node} {self.OPERATOR} {self.value_node}"

    @classmethod
    def build(
        cls,
        operator: str,
        name: NameNode,
        value: ValueNode,
        filename: str,
        line: int,
        case_sensitive: bool = False,
        *,
        warning_state: list[bool] | None = None,
        source: SourceLocation | None = None,
    ) -> RuleNode:
        rule_cls: type[RuleNode]
        if operator == "=":
            rule_cls = EqualRuleNode
        elif operator == "!=":
            rule_cls = NotEqualRuleNode
        elif operator == "~":
            rule_cls = ContainsRuleNode
        elif operator == "^":
            rule_cls = StartsWithRuleNode
        elif operator == "$":
            rule_cls = EndsWithRuleNode
        elif operator == "%":
            rule_cls = RegexRuleNode
        elif operator == "<":
            rule_cls = LesserRuleNode
        elif operator == "<=":
            rule_cls = LesserOrEqualRuleNode
        elif operator == ">":
            rule_cls = GreaterRuleNode
        elif operator == ">=":
            rule_cls = GreaterOrEqualRuleNode
        else:
            raise GenplisM3UGException(
                f"Unrecognized operator: {operator}", filename, line
            )
        rule_cls.check_params(name, value, filename, line)
        try:
            return rule_cls(
                name,
                value,
                case_sensitive,
                warning_state=warning_state,
                source=source,
            )
        except re.error as exc:
            raise GenplisM3UGException(
                f"Invalid regular expression: {exc}", filename, line
            ) from exc

    def apply(self, tags: Mapping[str, TagValue]) -> bool:
        tag_name, raw_value = self.name_node.find(tags)
        tag_value = self.value_node.normalize(raw_value)
        if self.IS_TEXT and _has_boolean(tag_value):
            self._warn_boolean(tag_name)
        return self.check(tag_value)

    def _warn_boolean(self, tag_name: str) -> None:
        if self._warning_state[0]:
            return
        self._warning_state[0] = True
        logger.warning(
            "text operator %r applied to boolean tag %r; use = true or = false",
            self.OPERATOR,
            tag_name,
        )

    def check(self, tag_value: TagValue) -> bool:
        """True if rule passes for the given value.

        Expected value will be in self.value_node.value.

        """
        raise NotImplementedError()

    @classmethod
    def check_params(
        cls, name: NameNode, value: ValueNode, filename: str, line: int
    ) -> None:
        """Raise GenplisM3UGException if something is wrong with the rule."""
        pass


def _has_boolean(value: TagValue) -> bool:
    if isinstance(value, bool):
        return True
    if isinstance(value, list):
        return any(isinstance(item, bool) for item in value)
    return False


def _value_mode(operator: str, filename: str, line: int) -> ValueMode:
    if operator in EQUALITY_OPERATORS:
        return "equality"
    if operator in TEXT_OPERATORS:
        return "text"
    if operator in NUMERIC_OPERATORS:
        return "numeric"
    raise GenplisM3UGException(f"Unrecognized operator: {operator}", filename, line)


def _text_equal(first: str, second: str, case_sensitive: bool) -> bool:
    if case_sensitive:
        return first == second
    return first.casefold() == second.casefold()


def _string_values(tag_value: TagValue) -> list[str]:
    if isinstance(tag_value, list):
        return [value for value in tag_value if isinstance(value, str)]
    if isinstance(tag_value, str):
        return [tag_value]
    return []


class EqualRuleNode(RuleNode):
    OPERATOR_NAME = "equals"
    OPERATOR = "="

    def check(self, tag_value: TagValue) -> bool:
        if isinstance(tag_value, list):
            return any(
                values_equal(
                    value, self.value_node.value, case_sensitive=self.case_sensitive
                )
                for value in tag_value
            )
        return values_equal(
            tag_value, self.value_node.value, case_sensitive=self.case_sensitive
        )


class NotEqualRuleNode(RuleNode):
    OPERATOR_NAME = "not equal"
    OPERATOR = "!="

    def check(self, tag_value: TagValue) -> bool:
        if isinstance(tag_value, list):
            return all(
                not values_equal(
                    value, self.value_node.value, case_sensitive=self.case_sensitive
                )
                for value in tag_value
            )
        return not values_equal(
            tag_value, self.value_node.value, case_sensitive=self.case_sensitive
        )


class ContainsRuleNode(RuleNode):
    OPERATOR_NAME = "contains"
    OPERATOR = "~"
    IS_TEXT = True

    def check(self, tag_value: TagValue) -> bool:
        expected = self.value_node.text()
        if expected is None:
            return False
        if not self.case_sensitive:
            expected = expected.casefold()
        for value in _string_values(tag_value):
            candidate = value if self.case_sensitive else value.casefold()
            if expected in candidate:
                return True
        return False


class StartsWithRuleNode(RuleNode):
    OPERATOR_NAME = "starts with"
    OPERATOR = "^"
    IS_TEXT = True

    def check(self, tag_value: TagValue) -> bool:
        expected = self.value_node.text()
        if expected is None:
            return False
        return any(
            _text_equal(value[: len(expected)], expected, self.case_sensitive)
            for value in _string_values(tag_value)
        )


class EndsWithRuleNode(RuleNode):
    OPERATOR_NAME = "ends with"
    OPERATOR = "$"
    IS_TEXT = True

    def check(self, tag_value: TagValue) -> bool:
        expected = self.value_node.text()
        if expected is None:
            return False
        values = _string_values(tag_value)
        if not expected:
            return bool(values)
        return any(
            len(value) >= len(expected)
            and _text_equal(value[-len(expected) :], expected, self.case_sensitive)
            for value in values
        )


class RegexRuleNode(RuleNode):
    OPERATOR_NAME = "matches"
    OPERATOR = "%"
    IS_TEXT = True

    def __init__(
        self,
        name: NameNode,
        value: ValueNode,
        case_sensitive: bool = False,
        *,
        warning_state: list[bool] | None = None,
        source: SourceLocation | None = None,
    ) -> None:
        super().__init__(
            name,
            value,
            case_sensitive,
            warning_state=warning_state,
            source=source,
        )
        pattern = value.text()
        if pattern is None:
            raise re.error("regular expression needs a string value")
        flags = 0 if case_sensitive else re.IGNORECASE
        self.pattern = re.compile(_normalize_inline_flags(pattern), flags)

    def check(self, tag_value: TagValue) -> bool:
        return any(
            self.pattern.search(value) is not None
            for value in _string_values(tag_value)
        )


class _NumericRuleNode(RuleNode):
    """Base class for numeric comparison operators."""

    @classmethod
    def check_params(
        cls, name: NameNode, value: ValueNode, filename: str, line: int
    ) -> None:
        if not is_number(value.value):
            raise GenplisM3UGException(
                f"{cls.OPERATOR} needs a numeric value, got: {value.value}",
                filename,
                line,
            )

    def check(self, tag_value: TagValue) -> bool:
        if isinstance(tag_value, list):
            return any(self.check(value) for value in tag_value)
        expected = self.value_node.numeric()
        if expected is None:
            return False
        if is_number(tag_value):
            return self.compare(tag_value, expected)
        if isinstance(tag_value, str):
            if INT_RE.match(tag_value):
                return self.compare(int(tag_value), expected)
            if FLOAT_RE.match(tag_value):
                return self.compare(float(tag_value), expected)
        return False

    def compare(self, tag_value: int | float, expected: int | float) -> bool:
        raise NotImplementedError()


class LesserRuleNode(_NumericRuleNode):
    OPERATOR_NAME = "lesser"
    OPERATOR = "<"

    def compare(self, tag_value: int | float, expected: int | float) -> bool:
        return tag_value < expected


class LesserOrEqualRuleNode(_NumericRuleNode):
    OPERATOR_NAME = "less or equal"
    OPERATOR = "<="

    def compare(self, tag_value: int | float, expected: int | float) -> bool:
        return tag_value <= expected


class GreaterRuleNode(_NumericRuleNode):
    OPERATOR_NAME = "greater"
    OPERATOR = ">"

    def compare(self, tag_value: int | float, expected: int | float) -> bool:
        return tag_value > expected


class GreaterOrEqualRuleNode(_NumericRuleNode):
    OPERATOR_NAME = "greater or equal"
    OPERATOR = ">="

    def compare(self, tag_value: int | float, expected: int | float) -> bool:
        return tag_value >= expected


@dataclass(frozen=True, slots=True)
class AndNode:
    """A conjunction of filter nodes."""

    nodes: tuple[FilterNode, ...]

    def apply(self, tags: Mapping[str, TagValue]) -> bool:
        return all(node.apply(tags) for node in self.nodes)


@dataclass(frozen=True, slots=True)
class OrNode:
    """A disjunction of filter nodes."""

    nodes: tuple[FilterNode, ...]

    def apply(self, tags: Mapping[str, TagValue]) -> bool:
        return any(node.apply(tags) for node in self.nodes)


@dataclass(frozen=True, slots=True)
class NotNode:
    """The negation of a filter node."""

    node: FilterNode

    def apply(self, tags: Mapping[str, TagValue]) -> bool:
        return not self.node.apply(tags)


def _leaf_rules(node: FilterNode | None) -> tuple[RuleNode, ...]:
    """Flatten the leaf rules in an expression tree."""
    if node is None:
        return ()
    if isinstance(node, RuleNode):
        return (node,)
    if isinstance(node, AndNode | OrNode):
        leaves: list[RuleNode] = []
        for child in node.nodes:
            leaves.extend(_leaf_rules(child))
        return tuple(leaves)
    if isinstance(node, NotNode):
        return _leaf_rules(node.node)
    return ()


def format_expression(node: FilterNode | None) -> str:
    """Format a filter expression for verbose diagnostics."""
    if node is None:
        return "(always)"
    if isinstance(node, RuleNode):
        return str(node)
    if isinstance(node, NotNode):
        return f"NOT ({format_expression(node.node)})"
    if isinstance(node, OrNode):
        return "(" + " OR ".join(format_expression(child) for child in node.nodes) + ")"
    if isinstance(node, AndNode):
        return " AND ".join(format_expression(child) for child in node.nodes)
    return str(node)


@dataclass(frozen=True, slots=True)
class _Unset:
    """Marker for a directive that a file did not set."""


UNSET = _Unset()


@dataclass(frozen=True, slots=True)
class LimitPerTag:
    """A per-tag limit: keep at most count entries for each tag value."""

    count: int
    tag: str

    def __str__(self) -> str:
        return f"{self.count} per {self.tag}"


@dataclass(frozen=True, slots=True)
class Directives:
    """Directive values with unset markers for include merging."""

    sort: SortSpec | _Unset = UNSET
    limit: int | _Unset = UNSET
    limit_per: LimitPerTag | _Unset = UNSET
    dedupe: tuple[str, ...] | _Unset = UNSET
    max_duration: float | _Unset = UNSET


def _merge_directives(base: Directives, override: Directives) -> Directives:
    """Return base with every directive set by override applied."""
    return Directives(
        sort=base.sort if isinstance(override.sort, _Unset) else override.sort,
        limit=base.limit if isinstance(override.limit, _Unset) else override.limit,
        limit_per=(
            base.limit_per
            if isinstance(override.limit_per, _Unset)
            else override.limit_per
        ),
        dedupe=(
            base.dedupe if isinstance(override.dedupe, _Unset) else override.dedupe
        ),
        max_duration=(
            base.max_duration
            if isinstance(override.max_duration, _Unset)
            else override.max_duration
        ),
    )


@dataclass(frozen=True, slots=True)
class IncludeInfo:
    """One ``@INCLUDE`` directive and the file it resolved to."""

    raw_path: str
    path: Path
    line: int
    file: M3UGFile


@dataclass(frozen=True, slots=True)
class M3UGFile:
    """A parsed M3UG file: a filter expression and playlist settings."""

    filename: str | None
    expression: FilterNode | None
    own_expression: FilterNode | None
    includes: tuple[IncludeInfo, ...]
    sort: SortSpec | None = None
    limit: int | None = None
    limit_per: LimitPerTag | None = None
    dedupe: tuple[str, ...] | None = None
    max_duration: float | None = None
    no_playlist: bool = False

    @property
    def rules(self) -> tuple[RuleNode, ...]:
        """Return the leaf rules, flattened for diagnostics and tests."""
        return _leaf_rules(self.expression)


def _parse_sort_directive(raw_value: str, filename: str, line: int) -> SortSpec:
    try:
        return parse_sort_spec(raw_value)
    except SortSpecError as exc:
        raise GenplisM3UGException(str(exc), filename, line) from exc


MAX_INCLUDE_DEPTH = 32

type IncludeLoader = Callable[[Path], str]


def _and_expressions(expressions: list[FilterNode | None]) -> FilterNode | None:
    """Combine expressions with AND, flattening nested conjunctions."""
    nodes: list[FilterNode] = []
    for expression in expressions:
        if expression is None:
            continue
        if isinstance(expression, AndNode):
            nodes.extend(expression.nodes)
        else:
            nodes.append(expression)
    if not nodes:
        return None
    if len(nodes) == 1:
        return nodes[0]
    return AndNode(tuple(nodes))


def _resolve_include_path(raw_path: str, filename: str, line: int) -> Path:
    value = raw_path.strip()
    if not value:
        raise GenplisM3UGException("@INCLUDE needs a path", filename, line)
    if _is_quoted(value):
        value = _unescape_quoted(value[1:-1])
    path = Path(value).expanduser()
    if path.is_absolute():
        return path
    base = Path.cwd() if filename == "N/A" else Path(filename).expanduser().parent
    return base / path


def _include_candidates(target: Path) -> tuple[Path, ...]:
    """Return the paths to try for an include, adding .m3ug when missing."""
    if target.name.lower().endswith(".m3ug"):
        return (target,)
    return (target, target.with_name(f"{target.name}.m3ug"))


def _read_include(
    target: Path,
    raw_path: str,
    filename: str,
    line: int,
    include_loader: IncludeLoader | None,
) -> tuple[str, Path]:
    for candidate in _include_candidates(target):
        try:
            if include_loader is not None:
                content = include_loader(candidate)
            elif not candidate.exists():
                raise FileNotFoundError(candidate)
            elif candidate.is_dir():
                raise IsADirectoryError(candidate)
            else:
                content = candidate.read_text(encoding="utf-8-sig")
            return content, candidate
        except (FileNotFoundError, KeyError):
            continue
        except IsADirectoryError as exc:
            raise GenplisM3UGException(
                f'cannot include "{raw_path}": path is a directory', filename, line
            ) from exc
        except OSError as exc:
            raise GenplisM3UGException(
                f'cannot include "{raw_path}": cannot read file: {exc}',
                filename,
                line,
            ) from exc

    raise GenplisM3UGException(
        f'cannot include "{raw_path}": file not found', filename, line
    )


def _parse_m3ug_file(
    content: str,
    filename: str,
    verbosity: Verbosity,
    include_loader: IncludeLoader | None,
    stack: tuple[Path, ...],
    depth: int,
) -> tuple[M3UGFile, Directives]:
    if content.startswith("\ufeff"):
        content = content[1:]
    and_groups: list[list[FilterNode]] = []
    current_group: list[FilterNode] | None = None
    own_sort: SortSpec | _Unset = UNSET
    own_limit: int | _Unset = UNSET
    own_limit_per: LimitPerTag | _Unset = UNSET
    own_max_duration: float | _Unset = UNSET
    own_dedupe: tuple[str, ...] | _Unset = UNSET
    own_no_playlist = False
    no_playlist_seen = False
    included_directives: list[Directives] = []
    includes: list[IncludeInfo] = []

    if verbosity.is_verbose:
        print(f"Parsing M3UG file {filename}:")
        print("----------------")
        print(content.ljust(4))
        print("----------------")
    for n, line in enumerate(content.splitlines(), 1):
        # ignore comments
        stripped = line.lstrip()
        if stripped.startswith("#"):
            if verbosity.is_verbose:
                print(f"Ignoring line {n}: comment")
            continue
        elif not stripped.strip():
            if verbosity.is_verbose:
                print(f"Ignoring line {n}: empty")
            continue

        text = stripped.strip()
        case_sensitive = False
        or_modifier = False
        not_modifier = False
        is_directive = False
        while text.startswith("@"):
            first, rest = _split_first_word(text)
            modifier = first.lower()
            if modifier == "@case":
                if case_sensitive:
                    raise GenplisM3UGException("Duplicate @CASE modifier", filename, n)
                case_sensitive = True
                text = rest.strip()
                if not text:
                    raise GenplisM3UGException("@CASE needs a rule", filename, n)
                continue
            if modifier == "@or":
                if or_modifier:
                    raise GenplisM3UGException("Duplicate @OR modifier", filename, n)
                or_modifier = True
                text = rest.strip()
                if not text:
                    raise GenplisM3UGException("@OR needs a rule", filename, n)
                continue
            if modifier == "@not":
                if not_modifier:
                    raise GenplisM3UGException("Duplicate @NOT modifier", filename, n)
                not_modifier = True
                text = rest.strip()
                if not text:
                    raise GenplisM3UGException("@NOT needs a rule", filename, n)
                continue
            if modifier == "@sort":
                if case_sensitive or or_modifier or not_modifier:
                    raise GenplisM3UGException(
                        "Directives cannot use rule modifiers", filename, n
                    )
                if not isinstance(own_sort, _Unset):
                    raise GenplisM3UGException(
                        "Duplicate @sort directive; combine all keys on one line",
                        filename,
                        n,
                    )
                own_sort = _parse_sort_directive(rest, filename, n)
                if verbosity.is_verbose:
                    print(f"Parsed sort: {format_sort_spec(own_sort)}")
                is_directive = True
                break
            if modifier == "@limit":
                if case_sensitive or or_modifier or not_modifier:
                    raise GenplisM3UGException(
                        "Directives cannot use rule modifiers", filename, n
                    )
                raw_limit = rest.strip()
                parts = raw_limit.split()
                if len(parts) == 1:
                    if not isinstance(own_limit, _Unset):
                        raise GenplisM3UGException(
                            "Duplicate @LIMIT directive", filename, n
                        )
                    if not INT_RE.match(parts[0]):
                        raise GenplisM3UGException(
                            f"@LIMIT needs a non-negative integer, got: {raw_limit!r}",
                            filename,
                            n,
                        )
                    own_limit = int(parts[0])
                    if verbosity.is_verbose:
                        print(f"Parsed limit: {own_limit}")
                elif len(parts) == 3 and parts[1].lower() == "per":
                    if not isinstance(own_limit_per, _Unset):
                        raise GenplisM3UGException(
                            "Duplicate @LIMIT ... PER directive", filename, n
                        )
                    if not INT_RE.match(parts[0]):
                        raise GenplisM3UGException(
                            "@LIMIT ... PER needs a non-negative integer, "
                            f"got: {raw_limit!r}",
                            filename,
                            n,
                        )
                    tag = parts[2].lower()
                    if any(character in "[]\"'," for character in tag):
                        raise GenplisM3UGException(
                            f"Invalid @LIMIT ... PER tag: {parts[2]!r}",
                            filename,
                            n,
                        )
                    own_limit_per = LimitPerTag(int(parts[0]), tag)
                    if verbosity.is_verbose:
                        print(f"Parsed per-tag limit: {own_limit_per}")
                else:
                    raise GenplisM3UGException(
                        f"@LIMIT expects N or N PER tag, got: {raw_limit!r}",
                        filename,
                        n,
                    )
                is_directive = True
                break
            if modifier == "@max-duration":
                if case_sensitive or or_modifier or not_modifier:
                    raise GenplisM3UGException(
                        "Directives cannot use rule modifiers", filename, n
                    )
                if not isinstance(own_max_duration, _Unset):
                    raise GenplisM3UGException(
                        "Duplicate @MAX-DURATION directive", filename, n
                    )
                raw_duration = rest.strip()
                duration = parse_duration_literal(raw_duration)
                if duration is None:
                    raise GenplisM3UGException(
                        f"Invalid @MAX-DURATION value: {raw_duration!r}",
                        filename,
                        n,
                    )
                own_max_duration = duration
                if verbosity.is_verbose:
                    print(f"Parsed max duration: {own_max_duration}")
                is_directive = True
                break
            if modifier == "@dedupe":
                if case_sensitive or or_modifier or not_modifier:
                    raise GenplisM3UGException(
                        "Directives cannot use rule modifiers", filename, n
                    )
                if not isinstance(own_dedupe, _Unset):
                    raise GenplisM3UGException(
                        "Duplicate @DEDUPE directive", filename, n
                    )
                raw_dedupe = rest.strip()
                keys: list[str] = []
                if raw_dedupe:
                    for element in raw_dedupe.split(","):
                        key = element.strip().lower()
                        if not key:
                            raise GenplisM3UGException("Empty @DEDUPE key", filename, n)
                        if key in keys:
                            raise GenplisM3UGException(
                                f"Duplicate @DEDUPE key: {key}", filename, n
                            )
                        keys.append(key)
                own_dedupe = tuple(keys)
                if verbosity.is_verbose:
                    print(f"Parsed dedupe: {', '.join(own_dedupe) or 'disabled'}")
                is_directive = True
                break
            if modifier == "@no-playlist":
                if case_sensitive or or_modifier or not_modifier:
                    raise GenplisM3UGException(
                        "Directives cannot use rule modifiers", filename, n
                    )
                if rest.strip():
                    raise GenplisM3UGException(
                        "@NO-PLAYLIST takes no arguments", filename, n
                    )
                if no_playlist_seen:
                    raise GenplisM3UGException(
                        "Duplicate @NO-PLAYLIST directive", filename, n
                    )
                own_no_playlist = True
                no_playlist_seen = True
                if verbosity.is_verbose:
                    print("Parsed no-playlist file")
                is_directive = True
                break
            if modifier == "@include":
                if or_modifier or not_modifier:
                    raise GenplisM3UGException(
                        "@INCLUDE cannot be used under @OR or @NOT", filename, n
                    )
                if case_sensitive:
                    raise GenplisM3UGException(
                        "Directives cannot use rule modifiers", filename, n
                    )
                raw_path = rest.strip()
                if not raw_path:
                    raise GenplisM3UGException("@INCLUDE needs a path", filename, n)
                target = _resolve_include_path(raw_path, filename, n)
                if depth + 1 > MAX_INCLUDE_DEPTH:
                    raise GenplisM3UGException(
                        f"include depth exceeded (maximum {MAX_INCLUDE_DEPTH})",
                        filename,
                        n,
                    )
                display_path = (
                    _unescape_quoted(raw_path[1:-1])
                    if _is_quoted(raw_path)
                    else raw_path
                )
                included_content, included_target = _read_include(
                    target.resolve(),
                    display_path,
                    filename,
                    n,
                    include_loader,
                )
                resolved = included_target.resolve()
                if resolved in stack:
                    cycle_start = stack.index(resolved)
                    chain = (*stack[cycle_start:], resolved)
                    raise GenplisM3UGException(
                        "include cycle: " + " -> ".join(path.name for path in chain),
                        filename,
                        n,
                    )
                included_file, included_directive_values = _parse_m3ug_file(
                    included_content,
                    str(included_target),
                    verbosity,
                    include_loader,
                    (*stack, resolved),
                    depth + 1,
                )
                included_directives.append(included_directive_values)
                includes.append(
                    IncludeInfo(
                        raw_path=raw_path,
                        path=resolved,
                        line=n,
                        file=included_file,
                    )
                )
                if verbosity.is_verbose:
                    print(f"Included {included_target}")
                is_directive = True
                break
            raise GenplisM3UGException(f"Unrecognized directive: {first}", filename, n)

        if is_directive:
            continue

        components = _split_rule_line(text)

        if len(components) != 3:
            raise GenplisM3UGException("Invalid filter syntax", filename, n)

        tag, operator, value = components
        if operator not in OPERATORS:
            raise GenplisM3UGException(
                f"Unrecognized operator: {operator}", filename, n
            )
        mode = _value_mode(operator, filename, n)
        if case_sensitive and mode == "numeric":
            raise GenplisM3UGException(
                f"@CASE cannot be used with comparison operator {operator}",
                filename,
                n,
            )

        # building validates data
        tag_names = _parse_tag_names(tag, filename, n)
        if tag_names is None:
            tag_names = (NameNode.build(tag, filename, n),)
        duration_only = all(
            name_node.name.lower() == "duration" for name_node in tag_names
        )
        value_set = _parse_value_set(
            value, mode, filename, n, allow_duration=duration_only
        )
        if value_set is None:
            value_set = (
                ValueNode.parse(
                    value,
                    mode,
                    filename,
                    n,
                    allow_duration=duration_only,
                ),
            )
        if mode == "numeric" and len(value_set) != 1:
            raise GenplisM3UGException(
                "comparison operators take exactly one value; use @OR for alternatives",
                filename,
                n,
            )
        rule_node = _build_rule_set(
            operator,
            tag_names,
            value_set,
            filename,
            n,
            case_sensitive,
        )
        if not_modifier:
            rule_node = NotNode(rule_node)

        if or_modifier:
            if current_group is None:
                raise GenplisM3UGException("@OR cannot be the first rule", filename, n)
            current_group.append(rule_node)
        else:
            current_group = [rule_node]
            and_groups.append(current_group)

    groups = tuple(
        group[0] if len(group) == 1 else OrNode(tuple(group)) for group in and_groups
    )
    own_expression = AndNode(groups) if groups else None
    own_directives = Directives(
        sort=own_sort,
        limit=own_limit,
        limit_per=own_limit_per,
        dedupe=own_dedupe,
        max_duration=own_max_duration,
    )
    merged = Directives()
    for included in included_directives:
        merged = _merge_directives(merged, included)
    merged = _merge_directives(merged, own_directives)

    if includes:
        expression = _and_expressions(
            [*(include.file.expression for include in includes), own_expression]
        )
    else:
        expression = own_expression
    if verbosity.is_verbose:
        print("Parsed rules:")
        print(format_expression(expression))
        print()

    parsed = M3UGFile(
        filename=filename,
        expression=expression,
        own_expression=own_expression,
        includes=tuple(includes),
        sort=None if isinstance(merged.sort, _Unset) else merged.sort,
        limit=None if isinstance(merged.limit, _Unset) else merged.limit,
        limit_per=(None if isinstance(merged.limit_per, _Unset) else merged.limit_per),
        max_duration=(
            None if isinstance(merged.max_duration, _Unset) else merged.max_duration
        ),
        dedupe=None if isinstance(merged.dedupe, _Unset) else merged.dedupe,
        no_playlist=own_no_playlist,
    )
    return parsed, merged


def parse_m3ug(
    content: str,
    filename: str = "N/A",
    verbosity: Verbosity = Verbosity.NORMAL,
    *,
    include_loader: IncludeLoader | None = None,
) -> M3UGFile:
    if content.startswith("\ufeff"):
        content = content[1:]
    stack: tuple[Path, ...] = ()
    if filename != "N/A":
        stack = (Path(filename).expanduser().resolve(),)
    parsed, _ = _parse_m3ug_file(
        content,
        filename,
        verbosity,
        include_loader,
        stack,
        0,
    )
    return parsed
