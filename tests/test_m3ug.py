from pathlib import Path

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
    get_rating,
    parse_m3ug,
)


def test_contains_rule_string_value() -> None:
    rules = parse_m3ug("genre ~= Synthwave")
    assert rules == [
        ContainsRuleNode(NameNode("genre"), ValueNode("Synthwave")),
    ]
    assert rules[0].apply({"genre": "Synthwave"})
    assert rules[0].apply({"genre": "Synthwave; Retrowave"})
    assert not rules[0].apply({"genre": "Synth; Electronic"})


def test_contains_rule_quoted_string_value() -> None:
    rules = parse_m3ug('genre ~= "Heavy Metal"')
    assert rules == [
        ContainsRuleNode(NameNode("genre"), ValueNode("Heavy Metal")),
    ]
    assert rules[0].apply({"genre": "Heavy Metal"})
    assert rules[0].apply({"genre": ["Power Metal", "Heavy Metal"]})
    assert not rules[0].apply({"genre": "Synthwave"})


def test_equal_rule_single_quoted_string_value() -> None:
    rules = parse_m3ug("artist = 'DANCE WITH THE DEAD'")
    assert rules == [
        EqualRuleNode(NameNode("artist"), ValueNode("DANCE WITH THE DEAD")),
    ]
    assert rules[0].apply({"artist": "DANCE WITH THE DEAD"})
    assert not rules[0].apply({"artist": "DANCE WITH THE DEAD "})


def test_quoted_numeric_value_is_string() -> None:
    rules = parse_m3ug('rating = "4"')
    assert rules == [
        EqualRuleNode(NameNode("rating"), ValueNode("4")),
    ]
    assert not rules[0].apply({"rating": 4})


def test_equal_rule_float_value() -> None:
    rules = parse_m3ug("rating = 4.5")
    assert rules == [
        NotEqualRuleNode(NameNode("rating"), ValueNode(4.5)),
    ]
    assert rules[0].apply({"rating": 4.5})
    assert not rules[0].apply({"rating": 3.5})
    assert not rules[0].apply({"rating": "string for some reason"})
    assert not rules[0].apply({"rating": None})
    assert not rules[0].apply({})


def test_equal_rule_integer_value() -> None:
    rules = parse_m3ug("rating = 5")
    assert rules == [
        EqualRuleNode(NameNode("rating"), ValueNode(5)),
    ]
    assert rules[0].apply({"rating": 5})
    assert not rules[0].apply({"rating": 4.5})
    assert not rules[0].apply({"rating": "string for some reason"})
    assert not rules[0].apply({"rating": None})
    assert not rules[0].apply({})


def test_equal_rule_string_value() -> None:
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


def test_greater_rule_float_value() -> None:
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


def test_greater_rule_integer_value() -> None:
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


def test_greater_rule_string_value() -> None:
    with pytest.raises(GenplisM3UGException):
        parse_m3ug("rating > invalid")


def test_greater_or_equal_rule_float_value() -> None:
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


def test_greater_or_equal_rule_integer_value() -> None:
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


def test_greater_or_equal_rule_string_value() -> None:
    with pytest.raises(GenplisM3UGException):
        parse_m3ug("rating >= invalid")


def test_lesser_rule_float_value() -> None:
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


def test_lesser_rule_integer_value() -> None:
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


def test_lesser_rule_string_value() -> None:
    with pytest.raises(GenplisM3UGException):
        parse_m3ug("rating > invalid")


def test_lesser_or_equal_rule_float_value() -> None:
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


def test_lesser_or_equal_rule_integer_value() -> None:
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


def test_lesser_or_equal_rule_string_value() -> None:
    with pytest.raises(GenplisM3UGException):
        parse_m3ug("rating >= invalid")


def test_not_equal_rule_float_value() -> None:
    rules = parse_m3ug("rating != 3.5")
    assert rules == [
        NotEqualRuleNode(NameNode("rating"), ValueNode(3.5)),
    ]
    assert not rules[0].apply({"rating": 3.5})
    assert rules[0].apply({"rating": 5})
    assert rules[0].apply({"rating": "string for some reason"})
    assert rules[0].apply({"rating": None})
    assert rules[0].apply({})


def test_not_equal_rule_integer_value() -> None:
    rules = parse_m3ug("rating != 5")
    assert rules == [
        NotEqualRuleNode(NameNode("rating"), ValueNode(5)),
    ]
    assert not rules[0].apply({"rating": 5})
    assert rules[0].apply({"rating": 3.5})
    assert rules[0].apply({"rating": "string for some reason"})
    assert rules[0].apply({"rating": None})
    assert rules[0].apply({})


def test_not_equal_rule_string_value() -> None:
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


def test_invalid_input() -> None:
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


def test_equal_rule_list_value() -> None:
    rules = parse_m3ug("genre = Metal")
    assert rules[0].apply({"genre": ["Metal", "Rock"]})
    assert not rules[0].apply({"genre": ["Rock", "Pop"]})


def test_not_equal_rule_list_value() -> None:
    rules = parse_m3ug("genre != Metal")
    assert rules[0].apply({"genre": ["Rock", "Pop"]})
    assert not rules[0].apply({"genre": ["Metal", "Rock"]})


def test_equal_rule_numeric_string_value() -> None:
    rules = parse_m3ug("track = 7")
    assert rules[0].apply({"track": ["7"]})
    assert rules[0].apply({"track": "7"})
    assert rules[0].apply({"track": 7})
    assert not rules[0].apply({"track": ["8"]})
    assert not rules[0].apply({"track": "not a number"})


def test_not_equal_rule_numeric_string_value() -> None:
    rules = parse_m3ug("track != 7")
    assert rules[0].apply({"track": ["8"]})
    assert rules[0].apply({"track": "not a number"})
    assert not rules[0].apply({"track": ["7"]})
    assert not rules[0].apply({"track": 7})


def test_contains_rule_list_value() -> None:
    rules = parse_m3ug("genre ~= wave")
    assert rules[0].apply({"genre": ["Synthwave", "Retrowave"]})
    assert not rules[0].apply({"genre": ["Metal", "Rock"]})


def test_get_rating_from_fmps_rating() -> None:
    assert get_rating({"fmps_rating": ["0.8"]}) == pytest.approx(4.0)


def test_get_rating_without_rating_tags() -> None:
    assert get_rating({"title": ["Test"]}) is None


def test_get_rating_returns_none_when_raw_rating_tag_exists() -> None:
    assert get_rating({"rating": 4, "fmps_rating": ["0.8"]}) is None


def test_find_rating_uses_raw_rating_tag() -> None:
    name, value = NameNode("rating").find({"rating": 4, "fmps_rating": ["0.8"]})
    assert name == "rating"
    assert value == 4


def test_find_rating_uses_zero_raw_rating_tag() -> None:
    name, value = NameNode("rating").find({"rating": 0, "fmps_rating": ["0.8"]})
    assert name == "rating"
    assert value == 0


def test_find_rating_from_single_item_fmps_rating_list() -> None:
    name, value = NameNode("rating").find({"fmps_rating": ["0.8"]})
    assert name == "rating"
    assert value == pytest.approx(4.0)


def test_find_rating_from_multi_item_fmps_rating_list(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level("WARNING", logger="genplis.m3ug"):
        name, value = NameNode("rating").find({"fmps_rating": ["0.8", "0.9"]})
    assert name == "rating"
    assert value == pytest.approx(4.0)
    assert "Unexpected fmps_rating as list" in caplog.text


def test_multiple_rules() -> None:
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


def test_examples_parse() -> None:
    """Every shipped example filter must remain valid."""
    examples_dir = Path(__file__).resolve().parent.parent / "examples"
    examples = sorted(examples_dir.glob("*.m3ug"))

    assert examples
    for example in examples:
        rules = parse_m3ug(example.read_text(encoding="utf-8"), str(example))
        assert rules, f"{example.name} should define at least one rule"
