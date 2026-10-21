from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from typing import ClassVar, Self, TypeGuard

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


type RuleValue = str | float | int


def is_number(value: object) -> TypeGuard[int | float]:
    return isinstance(value, int | float) and not isinstance(value, bool)


def values_equal(tag_value: TagValue, expected: RuleValue) -> bool:
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
        return str(self.value)

    @classmethod
    def build(cls, value: object, filename: str, line: int) -> Self:
        if not isinstance(value, str):
            raise GenplisM3UGException(f"Invalid value: {value}", filename, line)

        value = value.strip()
        # quoted values are always literal strings, even if they look numeric
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            return cls(value[1:-1])

        if FLOAT_RE.match(value):
            return cls(float(value))
        elif INT_RE.match(value):
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


class RuleNode:
    OPERATOR_NAME: ClassVar[str]

    def __init__(self, name: NameNode, value: ValueNode) -> None:
        self.name_node = name
        self.value_node = value

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, RuleNode):
            return NotImplemented
        if type(self) is not type(other):
            return False
        return self.name_node == other.name_node and self.value_node == other.value_node

    def __repr__(self) -> str:
        return f"Rule=<{self.name_node}, {self.OPERATOR_NAME}, {self.value_node}>"

    def __str__(self) -> str:
        return f"{self.name_node} {self.OPERATOR_NAME} {self.value_node}"

    @classmethod
    def build(
        cls,
        operator: str,
        name: NameNode,
        value: ValueNode,
        filename: str,
        line: int,
    ) -> RuleNode:
        rule_cls: type[RuleNode]
        if operator == "=":
            rule_cls = EqualRuleNode
        elif operator == "!=":
            rule_cls = NotEqualRuleNode
        elif operator == "~=":
            rule_cls = ContainsRuleNode
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
        return rule_cls(name, value)

    def apply(self, tags: Mapping[str, TagValue]) -> bool:
        _, raw_value = self.name_node.find(tags)
        # print(tag, repr(raw_value))
        tag_value = self.value_node.normalize(raw_value)
        return self.check(tag_value)

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


class EqualRuleNode(RuleNode):
    OPERATOR_NAME = "equals"

    def check(self, tag_value: TagValue) -> bool:
        if isinstance(tag_value, list):
            return any(values_equal(v, self.value_node.value) for v in tag_value)
        return values_equal(tag_value, self.value_node.value)


class NotEqualRuleNode(RuleNode):
    OPERATOR_NAME = "not equal"

    def check(self, tag_value: TagValue) -> bool:
        if isinstance(tag_value, list):
            return all(not values_equal(v, self.value_node.value) for v in tag_value)
        return not values_equal(tag_value, self.value_node.value)


class ContainsRuleNode(RuleNode):
    OPERATOR_NAME = "contains"

    def check(self, tag_value: TagValue) -> bool:
        expected = self.value_node.text()
        if expected is None:
            return False
        if isinstance(tag_value, str):
            return expected in tag_value
        if isinstance(tag_value, list):
            return any(expected in v for v in tag_value)
        return False

    @classmethod
    def check_params(
        cls, name: NameNode, value: ValueNode, filename: str, line: int
    ) -> None:
        if is_number(value.value):
            raise GenplisM3UGException(
                "{operator} needs a string value", filename, line
            )


class LesserRuleNode(RuleNode):
    OPERATOR_NAME = "lesser"

    def check(self, tag_value: TagValue) -> bool:
        if isinstance(tag_value, list):
            return any(self.check(v) for v in tag_value)
        expected = self.value_node.numeric()
        if expected is None:
            return False
        if is_number(tag_value):
            return tag_value < expected
        if isinstance(tag_value, str):
            if INT_RE.match(tag_value):
                return int(tag_value) < expected
            elif FLOAT_RE.match(tag_value):
                return float(tag_value) < expected
        return False

    @classmethod
    def check_params(
        cls, name: NameNode, value: ValueNode, filename: str, line: int
    ) -> None:
        if not is_number(value.value):
            raise GenplisM3UGException(
                f"Lesser than operator (<) needs a numeric value, got: {value.value}",
                filename,
                line,
            )


class LesserOrEqualRuleNode(RuleNode):
    OPERATOR_NAME = "less or equal"

    def check(self, tag_value: TagValue) -> bool:
        if isinstance(tag_value, list):
            return any(self.check(v) for v in tag_value)
        expected = self.value_node.numeric()
        if expected is None:
            return False
        if is_number(tag_value):
            return tag_value <= expected
        if isinstance(tag_value, str):
            if INT_RE.match(tag_value):
                return int(tag_value) <= expected
            elif FLOAT_RE.match(tag_value):
                return float(tag_value) <= expected
        return False

    @classmethod
    def check_params(
        cls, name: NameNode, value: ValueNode, filename: str, line: int
    ) -> None:
        if not is_number(value.value):
            raise GenplisM3UGException(
                f"Lesser or equal than operator (<=) needs a numeric value, got: {value.value}",
                filename,
                line,
            )


class GreaterRuleNode(RuleNode):
    OPERATOR_NAME = "greater"

    def check(self, tag_value: TagValue) -> bool:
        if isinstance(tag_value, list):
            return any(self.check(v) for v in tag_value)
        expected = self.value_node.numeric()
        if expected is None:
            return False
        if is_number(tag_value):
            return tag_value > expected
        if isinstance(tag_value, str):
            if INT_RE.match(tag_value):
                return int(tag_value) > expected
            elif FLOAT_RE.match(tag_value):
                return float(tag_value) > expected
        return False

    @classmethod
    def check_params(
        cls, name: NameNode, value: ValueNode, filename: str, line: int
    ) -> None:
        if not is_number(value.value):
            raise GenplisM3UGException(
                f"Greater than operator (>) needs a numeric value, got: {value.value}",
                filename,
                line,
            )


class GreaterOrEqualRuleNode(RuleNode):
    OPERATOR_NAME = "greater or equal"

    def check(self, tag_value: TagValue) -> bool:
        if isinstance(tag_value, list):
            return any(self.check(v) for v in tag_value)
        expected = self.value_node.numeric()
        if expected is None:
            return False
        if is_number(tag_value):
            return tag_value >= expected
        if isinstance(tag_value, str):
            if INT_RE.match(tag_value):
                return int(tag_value) >= expected
            elif FLOAT_RE.match(tag_value):
                return float(tag_value) >= expected
        return False

    @classmethod
    def check_params(
        cls, name: NameNode, value: ValueNode, filename: str, line: int
    ) -> None:
        if not is_number(value.value):
            raise GenplisM3UGException(
                f"Greater or equal than operator (>=) needs a numeric value, got: {value.value}",
                filename,
                line,
            )


@dataclass(frozen=True, slots=True)
class M3UGFile:
    """A parsed M3UG file: filter rules and an optional ordering override."""

    rules: tuple[RuleNode, ...]
    sort: SortSpec | None = None


def parse_m3ug(
    content: str, filename: str = "N/A", verbosity: Verbosity = Verbosity.NORMAL
) -> M3UGFile:
    rules: list[RuleNode] = []
    sort_spec: SortSpec | None = None
    if verbosity.is_verbose:
        print(f"Parsing M3UG file {filename}:")
        print("----------------")
        print(content.ljust(4))
        print("----------------")
    for n, line in enumerate(content.splitlines(), 1):
        # ignore comments
        if line.startswith("#"):
            if verbosity.is_verbose:
                print(f"Ignoring line {n}: comment")
            continue
        elif not line.strip():
            if verbosity.is_verbose:
                print(f"Ignoring line {n}: empty")
            continue
        elif line.startswith("@"):
            parts = line.split(maxsplit=1)
            directive = parts[0]
            raw_value = parts[1] if len(parts) == 2 else ""
            if directive.lower() != "@sort":
                raise GenplisM3UGException(
                    f"Unrecognized directive: {directive}", filename, n
                )
            if sort_spec is not None:
                raise GenplisM3UGException(
                    "Duplicate @sort directive; combine all keys on one line",
                    filename,
                    n,
                )
            try:
                sort_spec = parse_sort_spec(raw_value)
            except SortSpecError as exc:
                raise GenplisM3UGException(str(exc), filename, n) from exc
            if not sort_spec:
                raise GenplisM3UGException("@sort needs at least one tag", filename, n)
            if verbosity.is_verbose:
                print(f"Parsed sort: {format_sort_spec(sort_spec)}")
            continue

        components = line.split(" ", 2)

        if len(components) != 3:
            raise GenplisM3UGException("Invalid filter syntax", filename, n)

        tag, operator, value = components

        # building validates data
        tag_node = NameNode.build(tag, filename, n)
        value_node = ValueNode.build(value, filename, n)
        rule_node = RuleNode.build(operator, tag_node, value_node, filename, n)

        rules.append(rule_node)

    if verbosity.is_verbose:
        print("Parsed rules:")
        for rule in rules:
            print(str(rule))
        print()

    return M3UGFile(tuple(rules), sort_spec)
