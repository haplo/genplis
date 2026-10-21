from __future__ import annotations

import logging
import re
from collections.abc import Mapping
from dataclasses import dataclass
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
    leaves = tuple(
        RuleNode.build(
            operator,
            name,
            value,
            filename,
            line,
            case_sensitive,
            warning_state=warning_state,
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
    def __init__(self, value: RuleValue) -> None:
        self.value = value

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
        # quoted values are always literal strings, even if they look numeric
        if _is_quoted(value):
            return cls(_unescape_quoted(value[1:-1]))

        if mode == "text":
            return cls(value)

        if allow_duration:
            duration = parse_duration_literal(value)
            if duration is not None:
                return cls(duration)

        if value == "true":
            return cls(True)
        if value == "false":
            return cls(False)
        if FLOAT_RE.match(value):
            return cls(float(value))
        if INT_RE.match(value):
            return cls(int(value))
        return cls(value)

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
    ) -> None:
        self.name_node = name
        self.value_node = value
        self.case_sensitive = case_sensitive
        self._warning_state = warning_state if warning_state is not None else [False]

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
            return rule_cls(name, value, case_sensitive, warning_state=warning_state)
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
        return any(
            len(value) >= len(expected)
            and _text_equal(value[-len(expected) :], expected, self.case_sensitive)
            for value in _string_values(tag_value)
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
    ) -> None:
        super().__init__(name, value, case_sensitive, warning_state=warning_state)
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
class M3UGFile:
    """A parsed M3UG file: a filter expression and playlist settings."""

    expression: FilterNode | None
    sort: SortSpec | None = None
    limit: int | None = None
    max_duration: float | None = None

    @property
    def rules(self) -> tuple[RuleNode, ...]:
        """Return the leaf rules, flattened for diagnostics and tests."""
        return _leaf_rules(self.expression)


def _parse_sort_directive(raw_value: str, filename: str, line: int) -> SortSpec:
    try:
        sort_spec = parse_sort_spec(raw_value)
    except SortSpecError as exc:
        raise GenplisM3UGException(str(exc), filename, line) from exc
    if not sort_spec:
        raise GenplisM3UGException("@sort needs at least one tag", filename, line)
    return sort_spec


def parse_m3ug(
    content: str, filename: str = "N/A", verbosity: Verbosity = Verbosity.NORMAL
) -> M3UGFile:
    and_groups: list[list[FilterNode]] = []
    current_group: list[FilterNode] | None = None
    sort_spec: SortSpec | None = None
    limit_spec: int | None = None
    max_duration_spec: float | None = None
    limit_seen = False
    max_duration_seen = False
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
                if sort_spec is not None:
                    raise GenplisM3UGException(
                        "Duplicate @sort directive; combine all keys on one line",
                        filename,
                        n,
                    )
                sort_spec = _parse_sort_directive(rest, filename, n)
                if verbosity.is_verbose:
                    print(f"Parsed sort: {format_sort_spec(sort_spec)}")
                is_directive = True
                break
            if modifier == "@limit":
                if case_sensitive or or_modifier or not_modifier:
                    raise GenplisM3UGException(
                        "Directives cannot use rule modifiers", filename, n
                    )
                if limit_seen:
                    raise GenplisM3UGException(
                        "Duplicate @LIMIT directive", filename, n
                    )
                raw_limit = rest.strip()
                if not INT_RE.match(raw_limit):
                    raise GenplisM3UGException(
                        f"@LIMIT needs a non-negative integer, got: {raw_limit!r}",
                        filename,
                        n,
                    )
                limit_spec = int(raw_limit)
                limit_seen = True
                if verbosity.is_verbose:
                    print(f"Parsed limit: {limit_spec}")
                is_directive = True
                break
            if modifier == "@max-duration":
                if case_sensitive or or_modifier or not_modifier:
                    raise GenplisM3UGException(
                        "Directives cannot use rule modifiers", filename, n
                    )
                if max_duration_seen:
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
                max_duration_spec = duration
                max_duration_seen = True
                if verbosity.is_verbose:
                    print(f"Parsed max duration: {max_duration_spec}")
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
    expression = AndNode(groups) if groups else None
    if verbosity.is_verbose:
        print("Parsed rules:")
        print(format_expression(expression))
        print()

    return M3UGFile(
        expression,
        sort_spec,
        limit_spec,
        max_duration_spec,
    )
