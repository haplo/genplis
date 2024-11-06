import logging
import re

from .exceptions import GenplisM3UGException

logger = logging.getLogger(__name__)


Value = str | float | int | list[str] | None

FLOAT_RE = re.compile(r"^\d+\.\d+$")
INT_RE = re.compile(r"^\d+$")


def is_number(value: Value) -> bool:
    return isinstance(value, int | float)


def normalize(raw, verbose: bool = False) -> Value:
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


class NameNode:
    def __init__(self, name: str, verbose: bool = False):
        self.name = name
        self.verbose = verbose

    def __repr__(self):
        return f"<Name={self.name}>"

    def __str__(self):
        return self.name

    @classmethod
    def build(cls, name, filename: str, line: int, verbose: bool = False):
        if not isinstance(name, str):
            raise GenplisM3UGException("Invalid name: {name}", filename, line)
        return cls(name, verbose)

    def find(self, tags) -> tuple[str, str | None]:
        normalized_name = self.name.lower()
        # if there is a tag with the exact (case-insensitive) name, use it
        if raw_value := tags.get(normalized_name):
            return normalized_name, raw_value
        # handle special cases
        if normalized_name == "rating":
            # There are multiple ways that different apps use to store ratings.
            # genplis uses "rating" as an alias for as many of them as possible,
            # and they are normalized to a 0 to 5 stars range.
            # If you know of a rating tag that is missing feel free to open an
            # issue with a PR to add support for it.
            fmps_rating = normalize(tags.get("fmps_rating"))
            if fmps_rating is not None:
                # fmps_rating goes from 0.0 to 1.0 (5 stars)
                normalized_rating = float(fmps_rating) * 5
                return normalized_name, normalized_rating
        # default case is no match, no value found
        return normalized_name, None


class ValueNode:
    def __init__(self, value: Value, verbose: bool = False):
        self.value = value
        self.verbose = verbose

    def __repr__(self):
        return f"<Value={self.value}>"

    def __str__(self):
        return str(self.value)

    @classmethod
    def build(cls, value, filename: str, line: int, verbose: bool = False):
        if FLOAT_RE.match(value):
            return cls(float(value), verbose)
        elif INT_RE.match(value):
            return cls(int(value), verbose)
        elif isinstance(value, str):
            return cls(str(value), verbose)
        else:
            raise GenplisM3UGException("Invalid value: {value}", filename, line)

    def normalize(self, raw) -> Value:
        return normalize(raw, self.verbose)


class RuleNode:
    def __init__(self, name: NameNode, value: ValueNode, verbose: bool = False):
        self.name_node = name
        self.value_node = value
        self.verbose = verbose

    def __repr__(self):
        return f"Rule=<{self.name_node}, {self.OPERATOR_NAME}, {self.value_node}>"

    def __str__(self):
        return f"{self.name_node} {self.OPERATOR_NAME} {self.value_node}"

    @classmethod
    def build(
        cls,
        operator: str,
        name: NameNode,
        value: ValueNode,
        filename: str,
        line: int,
        verbose: bool = False,
    ):
        if operator == "=":
            rule_cls = EqualRuleNode
        elif operator == "!=":
            rule_cls = NotEqualRuleNode
        elif operator == "~=":
            rule_cls = ContainsRuleNode
        elif operator == "<":
            rule_cls = LessRuleNode
        elif operator == "<=":
            rule_cls = LessOrEqualRuleNode
        elif operator == ">":
            rule_cls = GreaterRuleNode
        elif operator == ">=":
            rule_cls = GreaterOrEqualRuleNode
        else:
            raise GenplisM3UGException(
                f"Unrecognized operator: {operator}", filename, line
            )
        rule_cls.check_params(name, value, filename, line)
        return rule_cls(name, value, verbose)

    def apply(self, tags) -> bool:
        tag, raw_value = self.name_node.find(tags)
        # print(tag, repr(raw_value))
        tag_value = self.value_node.normalize(raw_value)
        return self.check(tag_value)

    def check(self, tag_value: Value) -> bool:
        """True if rule passes for the given value.

        Expected value will be in self.value_node.value.

        """
        raise NotImplementedError()

    @classmethod
    def check_params(cls, name: NameNode, value: ValueNode, filename: str, line: int):
        """Raise GenplisM3UGException if something is wrong with the rule."""
        pass


class EqualRuleNode(RuleNode):
    OPERATOR_NAME = "equals"

    def check(self, tag_value: Value) -> bool:
        if isinstance(tag_value, list):
            any(v == self.value_node.value for v in tag_value)
        else:
            return tag_value == self.value_node.value


class NotEqualRuleNode(RuleNode):
    OPERATOR_NAME = "not equal"

    def check(self, tag_value: Value) -> bool:
        if isinstance(tag_value, list):
            any(v != self.value_node.value for v in tag_value)
        else:
            return tag_value != self.value_node.value


class ContainsRuleNode(RuleNode):
    OPERATOR_NAME = "contains"

    def check(self, tag_value: Value) -> bool:
        if tag_value is None or is_number(tag_value):
            return False
        return self.value_node.value in tag_value

    @classmethod
    def check_params(cls, name: NameNode, value: ValueNode, filename: str, line: int):
        if is_number(value.value):
            raise GenplisM3UGException(
                "{operator} needs a string value", filename, line
            )


class LessRuleNode(RuleNode):
    OPERATOR_NAME = "lesser"

    def check(self, tag_value: Value) -> bool:
        if isinstance(tag_value, list):
            return any(self.check(v) for v in tag_value)
        elif is_number(tag_value):
            return tag_value < self.value_node.value
        elif isinstance(tag_value, str):
            if INT_RE.match(tag_value):
                return int(tag_value) < self.value_node.value
            elif FLOAT_RE.match(tag_value):
                return float(tag_value) < self.value_node.value
        return False

    @classmethod
    def check_params(cls, name: NameNode, value: ValueNode, filename: str, line: int):
        if not is_number(value.value):
            raise GenplisM3UGException(
                f"Less than operator (<) needs a numeric value, got: {value.value}",
                filename,
                line,
            )


class LessOrEqualRuleNode(RuleNode):
    OPERATOR_NAME = "less or equal"

    def check(self, tag_value: Value) -> bool:
        if isinstance(tag_value, list):
            return any(self.check(v) for v in tag_value)
        elif is_number(tag_value):
            return tag_value <= self.value_node.value
        elif isinstance(tag_value, str):
            if INT_RE.match(tag_value):
                return int(tag_value) <= self.value_node.value
            elif FLOAT_RE.match(tag_value):
                return float(tag_value) <= self.value_node.value
        return False

    @classmethod
    def check_params(cls, name: NameNode, value: ValueNode, filename: str, line: int):
        if not is_number(value.value):
            raise GenplisM3UGException(
                f"Less or equal than operator (<=) needs a numeric value, got: {value.value}",
                filename,
                line,
            )


class GreaterRuleNode(RuleNode):
    OPERATOR_NAME = "greater"

    def check(self, tag_value: Value) -> bool:
        if isinstance(tag_value, list):
            return any(self.check(v) for v in tag_value)
        elif is_number(tag_value):
            return tag_value > self.value_node.value
        elif isinstance(tag_value, str):
            if INT_RE.match(tag_value):
                return int(tag_value) > self.value_node.value
            elif FLOAT_RE.match(tag_value):
                return float(tag_value) > self.value_node.value
        return False

    @classmethod
    def check_params(cls, name: NameNode, value: ValueNode, filename: str, line: int):
        if not is_number(value.value):
            raise GenplisM3UGException(
                f"Greater than operator (>) needs a numeric value, got: {value.value}",
                filename,
                line,
            )


class GreaterOrEqualRuleNode(RuleNode):
    OPERATOR_NAME = "greater or equal"

    def check(self, tag_value: Value) -> bool:
        if isinstance(tag_value, list):
            return any(self.check(v) for v in tag_value)
        elif is_number(tag_value):
            return tag_value >= self.value_node.value
        elif isinstance(tag_value, str):
            if INT_RE.match(tag_value):
                return int(tag_value) >= self.value_node.value
            elif FLOAT_RE.match(tag_value):
                return float(tag_value) >= self.value_node.value
        return False

    @classmethod
    def check_params(cls, name: NameNode, value: ValueNode, filename: str, line: int):
        if not is_number(value.value):
            raise GenplisM3UGException(
                f"Greater or equal than operator (>=) needs a numeric value, got: {value.value}",
                filename,
                line,
            )


def parse_m3ug(content: str, filename: str = "N/A", verbose: bool = False):
    rules = []
    if verbose:
        print(f"Parsing M3UG file {filename}:")
        print("----------------")
        print(content.ljust(4))
        print("----------------")
    for n, line in enumerate(content.splitlines(), 1):
        # ignore comments
        if line.startswith("#"):
            if verbose:
                print("Ignoring line {n}: comment")
            continue
        elif not line.strip():
            if verbose:
                print("Ignoring line {n}: empty")
            continue

        components = line.split(" ", 2)

        if len(components) != 3:
            raise GenplisM3UGException("Invalid filter syntax", filename, n)

        tag, operator, value = components

        # building validates data
        tag_node = NameNode.build(tag, filename, n, verbose)
        value_node = ValueNode.build(value, filename, n, verbose)
        rule_node = RuleNode.build(operator, tag_node, value_node, filename, n, verbose)

        rules.append(rule_node)

    if verbose:
        print("Parsed rules:")
        for rule in rules:
            print(str(rule))
        print()

    return rules
