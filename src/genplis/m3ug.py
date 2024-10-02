import logging
import re
from typing import Tuple

logger = logging.getLogger(__name__)


Value = str | float | int | None

FLOAT_RE = re.compile(r"\d+\.\d+")
INT_RE = re.compile(r"\d+")


class FilterParseException(Exception):
    def __init__(self, message: str, filename: str, line: int):
        super().__init__(message)
        self.filename = filename
        self.line = line


class Filter:
    def __init__(self, tag, operator, value):
        self.tag = tag
        self.operator = operator
        self.value = value


class NameNode:
    def __init__(self, name: str):
        self.name = name

    def __repr__(self):
        return f"<Name={self.name}>"

    def __str__(self):
        return self.name

    @classmethod
    def build(cls, name, filename: str, line: int):
        if not isinstance(name, str):
            raise FilterParseException("Invalid name: {name}", filename, line)
        return cls(name)


class ValueNode:
    def __init__(self, value: Value):
        self.value = value

    def __repr__(self):
        return f"<Value={self.value}>"

    def __str__(self):
        return str(self.value)

    @classmethod
    def build(cls, value, filename: str, line: int):
        if FLOAT_RE.match(value):
            return cls(float(value))
        elif INT_RE.match(value):
            return cls(int(value))
        elif isinstance(value, str):
            return cls(str(value))
        else:
            raise FilterParseException("Invalid value: {value}", filename, line)

    def is_number(self) -> bool:
        return isinstance(self.value, (int, float))


class RuleNode:
    def __init__(self, name: NameNode, value: ValueNode):
        self.name = name
        self.value = value

    def __repr__(self):
        return f"Rule=<{self.name}, {self.OPERATOR_NAME}, {self.value}>"

    def __str__(self):
        return f"{self.name} {self.OPERATOR_NAME} {self.value}"

    @classmethod
    def build(cls, operator: str, name: NameNode, value: ValueNode, filename: str, line: int):
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
            raise FilterParseException(f"Unrecognized operator: {operator}", filename, line)
        rule_cls.check_params(name, value, filename, line)
        return rule_cls(name, value)

    @classmethod
    def check_params(cls, name: NameNode, value: ValueNode, filename: str, line: int):
        """Raise FilterParseException if something is wrong with the rule."""
        pass


class EqualRuleNode(RuleNode):
    OPERATOR_NAME = "equals"

class NotEqualRuleNode(RuleNode):
    OPERATOR_NAME = "not equal"


class ContainsRuleNode(RuleNode):
    OPERATOR_NAME = "contains"

    @classmethod
    def check_params(cls, name: NameNode, value: ValueNode, filename: str, line: int):
        if value.is_number():
            raise FilterParseException("{operator} needs a string value", filename, line)


class LessRuleNode(RuleNode):
    OPERATOR_NAME = "lesser"

    @classmethod
    def check_params(cls, name: NameNode, value: ValueNode, filename: str, line: int):
        if not value.is_number():
            raise FilterParseException(
                f"Less than operator (<) needs a numeric value, got: {value.value}",
                filename,
                line,
            )


class LessOrEqualRuleNode(RuleNode):
    OPERATOR_NAME = "less or equal"

    @classmethod
    def check_params(cls, name: NameNode, value: ValueNode, filename: str, line: int):
        if not value.is_number():
            raise FilterParseException(
                f"Less or equal than operator (<=) needs a numeric value, got: {value.value}",
                filename,
                line,
            )

class GreaterRuleNode(RuleNode):
    OPERATOR_NAME = "greater"

    @classmethod
    def check_params(cls, name: NameNode, value: ValueNode, filename: str, line: int):
        if not value.is_number():
            raise FilterParseException(
                f"Greater than operator (>) needs a numeric value, got: {value.value}",
                filename,
                line,
            )


class GreaterOrEqualRuleNode(RuleNode):
    OPERATOR_NAME = "greater or equal"

    @classmethod
    def check_params(cls, name: NameNode, value: ValueNode, filename: str, line: int):
        if not value.is_number():
            raise FilterParseException(
                f"Greater or equal than operator (>=) needs a numeric value, got: {value.value}",
                filename,
                line,
            )


def parse_m3ug(filename: str, content: str, verbose: bool = False):
    rules = []
    if verbose:
        print(f"Parsing M3UG file {filename}:")
        print("----------------")
        print(content.ljust(4))
        print("----------------")
    for n, line in enumerate(content.splitlines(), 1):
        # ignore comments
        if line.startswith('#'):
            if verbose:
                print("Ignoring line {n}: comment")
            continue
        elif not line.strip():
            if verbose:
                print("Ignoring line {n}: empty")
            continue

        components = line.split(" ", 2)

        if len(components) != 3:
            raise FilterParseException("Invalid filter syntax", filename, n)

        tag, operator, value = components

        # building validates data
        tag_node = NameNode.build(tag, filename, n)
        value_node = ValueNode.build(value, filename, n)
        rule_node = RuleNode.build(operator, tag_node, value_node, filename, n)

        rules.append(rule_node)

    if verbose:
        print("Parsed rules:")
        for rule in rules:
            print(str(rule))
        print()

    return rules
