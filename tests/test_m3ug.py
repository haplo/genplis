import pytest

from genplis.exceptions import GenplisM3UGException
from genplis.m3ug import (
    ContainsRuleNode,
    EqualRuleNode,
    GreaterOrEqualRuleNode,
    GreaterRuleNode,
    LesserOrEqualRuleNode,
    LesserRuleNode,
    NameNode,
    NotEqualRuleNode,
    ValueNode,
    parse_m3ug,
)


def test_contains_rule_string_value():
    rules = parse_m3ug("genre ~= Synthwave")
    assert rules == [
        ContainsRuleNode(NameNode("genre"), ValueNode("Synthwave")),
    ]
    assert rules[0].apply({"genre": "Synthwave"})
    assert rules[0].apply({"genre": "Synthwave; Retrowave"})
    assert not rules[0].apply({"genre": "Synth; Electronic"})


def test_equal_rule_float_value():
    rules = parse_m3ug("rating = 4.5")
    assert rules == [
        NotEqualRuleNode(NameNode("rating"), ValueNode(4.5)),
    ]
    assert rules[0].apply({"rating": 4.5})
    assert not rules[0].apply({"rating": 3.5})
    assert not rules[0].apply({"rating": "string for some reason"})
    assert not rules[0].apply({"rating": None})
    assert not rules[0].apply({})


def test_equal_rule_integer_value():
    rules = parse_m3ug("rating = 5")
    assert rules == [
        EqualRuleNode(NameNode("rating"), ValueNode(5)),
    ]
    assert rules[0].apply({"rating": 5})
    assert not rules[0].apply({"rating": 4.5})
    assert not rules[0].apply({"rating": "string for some reason"})
    assert not rules[0].apply({"rating": None})
    assert not rules[0].apply({})


def test_equal_rule_string_value():
    rules = parse_m3ug("genre = Synthwave")
    assert rules == [
        EqualRuleNode(NameNode("genre"), ValueNode("Synthwave")),
    ]
    assert rules[0].apply({"genre": "Synthwave"})
    assert not rules[0].apply({"genre": "Synthwave; Retrowave"})
    assert not rules[0].apply({"genre": 100})
    assert not rules[0].apply({"genre": 42.42})
    assert not rules[0].apply({"rating": None})
    assert not rules[0].apply({})


def test_greater_rule_float_value():
    rules = parse_m3ug("rating > 3.5")
    assert rules == [
        GreaterRuleNode(NameNode("rating"), ValueNode(3.5)),
    ]
    assert rules[0].apply({"rating": 4})
    assert rules[0].apply({"rating": 4.5})
    assert not rules[0].apply({"rating": 3})
    assert not rules[0].apply({"rating": 3.5})
    assert not rules[0].apply({"rating": "string for some reason"})
    assert not rules[0].apply({"rating": None})
    assert not rules[0].apply({})


def test_greater_rule_integer_value():
    rules = parse_m3ug("rating > 4")
    assert rules == [
        GreaterRuleNode(NameNode("rating"), ValueNode(4)),
    ]
    assert rules[0].apply({"rating": 4.5})
    assert rules[0].apply({"rating": 5})
    assert not rules[0].apply({"rating": 4})
    assert not rules[0].apply({"rating": 3.5})
    assert not rules[0].apply({"rating": "string for some reason"})
    assert not rules[0].apply({"rating": None})
    assert not rules[0].apply({})


def test_greater_rule_string_value():
    with pytest.raises(GenplisM3UGException):
        parse_m3ug("rating > invalid")


def test_greater_or_equal_rule_float_value():
    rules = parse_m3ug("rating >= 3.5")
    assert rules == [
        GreaterOrEqualRuleNode(NameNode("rating"), ValueNode(3.5)),
    ]
    assert rules[0].apply({"rating": 3.5})
    assert rules[0].apply({"rating": 4})
    assert not rules[0].apply({"rating": 3})
    assert not rules[0].apply({"rating": 2.5})
    assert not rules[0].apply({"rating": "string for some reason"})
    assert not rules[0].apply({"rating": None})
    assert not rules[0].apply({})


def test_greater_or_equal_rule_integer_value():
    rules = parse_m3ug("rating >= 4")
    assert rules == [
        GreaterOrEqualRuleNode(NameNode("rating"), ValueNode(4)),
    ]
    assert rules[0].apply({"rating": 4.5})
    assert rules[0].apply({"rating": 4})
    assert not rules[0].apply({"rating": 3})
    assert not rules[0].apply({"rating": 3.5})
    assert not rules[0].apply({"rating": "string for some reason"})
    assert not rules[0].apply({"rating": None})
    assert not rules[0].apply({})


def test_greater_or_equal_rule_string_value():
    with pytest.raises(GenplisM3UGException):
        parse_m3ug("rating >= invalid")


def test_lesser_rule_float_value():
    rules = parse_m3ug("rating < 3.5")
    assert rules == [
        LesserRuleNode(NameNode("rating"), ValueNode(3.5)),
    ]
    assert rules[0].apply({"rating": 3})
    assert rules[0].apply({"rating": 2.5})
    assert not rules[0].apply({"rating": 4})
    assert not rules[0].apply({"rating": 3.5})
    assert not rules[0].apply({"rating": "string for some reason"})
    assert not rules[0].apply({"rating": None})
    assert not rules[0].apply({})


def test_lesser_rule_integer_value():
    rules = parse_m3ug("rating < 4")
    assert rules == [
        LesserRuleNode(NameNode("rating"), ValueNode(4)),
    ]
    assert rules[0].apply({"rating": 3.9})
    assert rules[0].apply({"rating": 3})
    assert not rules[0].apply({"rating": 4})
    assert not rules[0].apply({"rating": 4.5})
    assert not rules[0].apply({"rating": "string for some reason"})
    assert not rules[0].apply({"rating": None})
    assert not rules[0].apply({})


def test_lesser_rule_string_value():
    with pytest.raises(GenplisM3UGException):
        parse_m3ug("rating > invalid")


def test_lesser_or_equal_rule_float_value():
    rules = parse_m3ug("rating <= 3.5")
    assert rules == [
        LesserOrEqualRuleNode(NameNode("rating"), ValueNode(3.5)),
    ]
    assert rules[0].apply({"rating": 3.5})
    assert rules[0].apply({"rating": 3})
    assert not rules[0].apply({"rating": 4})
    assert not rules[0].apply({"rating": 3.6})
    assert not rules[0].apply({"rating": "string for some reason"})
    assert not rules[0].apply({"rating": None})
    assert not rules[0].apply({})


def test_lesser_or_equal_rule_integer_value():
    rules = parse_m3ug("rating <= 4")
    assert rules == [
        LesserOrEqualRuleNode(NameNode("rating"), ValueNode(4)),
    ]
    assert rules[0].apply({"rating": 3.9})
    assert rules[0].apply({"rating": 4})
    assert not rules[0].apply({"rating": 5})
    assert not rules[0].apply({"rating": 4.1})
    assert not rules[0].apply({"rating": "string for some reason"})
    assert not rules[0].apply({"rating": None})
    assert not rules[0].apply({})


def test_lesser_or_equal_rule_string_value():
    with pytest.raises(GenplisM3UGException):
        parse_m3ug("rating >= invalid")


def test_not_equal_rule_float_value():
    rules = parse_m3ug("rating != 3.5")
    assert rules == [
        NotEqualRuleNode(NameNode("rating"), ValueNode(3.5)),
    ]
    assert not rules[0].apply({"rating": 3.5})
    assert rules[0].apply({"rating": 5})
    assert rules[0].apply({"rating": "string for some reason"})
    assert rules[0].apply({"rating": None})
    assert rules[0].apply({})


def test_not_equal_rule_integer_value():
    rules = parse_m3ug("rating != 5")
    assert rules == [
        NotEqualRuleNode(NameNode("rating"), ValueNode(5)),
    ]
    assert not rules[0].apply({"rating": 5})
    assert rules[0].apply({"rating": 3.5})
    assert rules[0].apply({"rating": "string for some reason"})
    assert rules[0].apply({"rating": None})
    assert rules[0].apply({})


def test_not_equal_rule_string_value():
    rules = parse_m3ug("genre != Pop")
    assert rules == [
        NotEqualRuleNode(NameNode("genre"), ValueNode("Pop")),
    ]
    assert not rules[0].apply({"genre": "Pop"})
    assert rules[0].apply({"genre": "Pop; Reggaeton"})
    assert rules[0].apply({"genre": "Metal"})
    assert rules[0].apply({"genre": 100})
    assert rules[0].apply({"genre": 42.42})
    assert rules[0].apply({"rating": None})
    assert rules[0].apply({})


def test_invalid_input():
    with pytest.raises(GenplisM3UGException):
        parse_m3ug("invalid")
    with pytest.raises(GenplisM3UGException):
        parse_m3ug("rating invalid 4")
    with pytest.raises(GenplisM3UGException):
        parse_m3ug(">= invalid")
    with pytest.raises(GenplisM3UGException):
        parse_m3ug("invalid >=")
    with pytest.raises(GenplisM3UGException):
        parse_m3ug("rating > 4 invalid")


def test_multiple_rules():
    assert parse_m3ug("""
# My favorite DANCE WITH THE DEAD songs
artist = DANCE WITH THE DEAD
rating >= 4
genre ~= Synthwave
    """) == [
        EqualRuleNode(NameNode("artist"), ValueNode("DANCE WITH THE DEAD")),
        GreaterOrEqualRuleNode(NameNode("rating"), ValueNode(4)),
        ContainsRuleNode(NameNode("genre"), ValueNode("Synthwave")),
    ]
