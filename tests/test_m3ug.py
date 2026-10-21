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
    RuleNode,
    ValueNode,
    get_rating,
    parse_m3ug,
)
from genplis.sorting import SortKey
from genplis.types import Verbosity


def parse_rules(
    content: str,
    filename: str = "N/A",
    verbosity: Verbosity = Verbosity.NORMAL,
) -> list[RuleNode]:
    """Return only the filter rules from a parsed M3UG file."""
    return list(parse_m3ug(content, filename, verbosity).rules)


def test_contains_rule_string_value() -> None:
    rules = parse_rules("genre ~= Synthwave")
    assert rules == [
        ContainsRuleNode(NameNode("genre"), ValueNode("Synthwave")),
    ]
    assert rules[0].apply({"genre": "Synthwave"})
    assert rules[0].apply({"genre": "Synthwave; Retrowave"})
    assert not rules[0].apply({"genre": "Synth; Electronic"})


def test_contains_rule_quoted_string_value() -> None:
    rules = parse_rules('genre ~= "Heavy Metal"')
    assert rules == [
        ContainsRuleNode(NameNode("genre"), ValueNode("Heavy Metal")),
    ]
    assert rules[0].apply({"genre": "Heavy Metal"})
    assert rules[0].apply({"genre": ["Power Metal", "Heavy Metal"]})
    assert not rules[0].apply({"genre": "Synthwave"})


def test_equal_rule_single_quoted_string_value() -> None:
    rules = parse_rules("artist = 'DANCE WITH THE DEAD'")
    assert rules == [
        EqualRuleNode(NameNode("artist"), ValueNode("DANCE WITH THE DEAD")),
    ]
    assert rules[0].apply({"artist": "DANCE WITH THE DEAD"})
    assert not rules[0].apply({"artist": "DANCE WITH THE DEAD "})


def test_quoted_numeric_value_is_string() -> None:
    rules = parse_rules('rating = "4"')
    assert rules == [
        EqualRuleNode(NameNode("rating"), ValueNode("4")),
    ]
    assert not rules[0].apply({"rating": 4})


def test_equal_rule_float_value() -> None:
    rules = parse_rules("rating = 4.5")
    assert rules == [
        EqualRuleNode(NameNode("rating"), ValueNode(4.5)),
    ]
    assert rules[0].apply({"rating": 4.5})
    assert not rules[0].apply({"rating": 3.5})
    assert not rules[0].apply({"rating": "string for some reason"})
    assert not rules[0].apply({"rating": None})
    assert not rules[0].apply({})


def test_rules_with_different_operators_are_not_equal() -> None:
    assert parse_rules("rating = 4")[0] != parse_rules("rating != 4")[0]


def test_equal_rule_integer_value() -> None:
    rules = parse_rules("rating = 5")
    assert rules == [
        EqualRuleNode(NameNode("rating"), ValueNode(5)),
    ]
    assert rules[0].apply({"rating": 5})
    assert not rules[0].apply({"rating": 4.5})
    assert not rules[0].apply({"rating": "string for some reason"})
    assert not rules[0].apply({"rating": None})
    assert not rules[0].apply({})


def test_boolean_never_matches_numeric_rule() -> None:
    assert not parse_rules("is_lossless = 1")[0].apply({"is_lossless": True})
    assert not parse_rules("is_lossless < 2")[0].apply({"is_lossless": True})
    assert parse_rules("is_lossless != 1")[0].apply({"is_lossless": True})


def test_equal_rule_string_value() -> None:
    rules = parse_rules("genre = Synthwave")
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
    rules = parse_rules("rating > 3.5")
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
    rules = parse_rules("rating > 4")
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
        parse_rules("rating > invalid")


def test_greater_or_equal_rule_float_value() -> None:
    rules = parse_rules("rating >= 3.5")
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
    rules = parse_rules("rating >= 4")
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
        parse_rules("rating >= invalid")


def test_lesser_rule_float_value() -> None:
    rules = parse_rules("rating < 3.5")
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
    rules = parse_rules("rating < 4")
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
        parse_rules("rating > invalid")


def test_lesser_or_equal_rule_float_value() -> None:
    rules = parse_rules("rating <= 3.5")
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
    rules = parse_rules("rating <= 4")
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
        parse_rules("rating >= invalid")


def test_not_equal_rule_float_value() -> None:
    rules = parse_rules("rating != 3.5")
    assert rules == [
        NotEqualRuleNode(NameNode("rating"), ValueNode(3.5)),
    ]
    assert not rules[0].apply({"rating": 3.5})
    assert rules[0].apply({"rating": 5})
    assert rules[0].apply({"rating": "string for some reason"})
    assert rules[0].apply({"rating": None})
    assert rules[0].apply({})


def test_not_equal_rule_integer_value() -> None:
    rules = parse_rules("rating != 5")
    assert rules == [
        NotEqualRuleNode(NameNode("rating"), ValueNode(5)),
    ]
    assert not rules[0].apply({"rating": 5})
    assert rules[0].apply({"rating": 3.5})
    assert rules[0].apply({"rating": "string for some reason"})
    assert rules[0].apply({"rating": None})
    assert rules[0].apply({})


def test_not_equal_rule_string_value() -> None:
    rules = parse_rules("genre != Pop")
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


def test_m3ug_exception_includes_location() -> None:
    error = GenplisM3UGException("Invalid filter syntax", "Favorites.m3ug", 7)
    assert str(error) == "Favorites.m3ug:7: Invalid filter syntax"


def test_name_node_build_error_includes_name() -> None:
    with pytest.raises(GenplisM3UGException, match="Invalid name: 42"):
        NameNode.build(42, "filter.m3ug", 3)


def test_verbose_parse_reports_line_numbers(
    capsys: pytest.CaptureFixture[str],
) -> None:
    parse_rules("# comment\n\nartist = x\n", verbosity=Verbosity.VERBOSE)

    output = capsys.readouterr().out
    assert "Ignoring line 1: comment" in output
    assert "Ignoring line 2: empty" in output


def test_invalid_input() -> None:
    with pytest.raises(GenplisM3UGException):
        parse_rules("invalid")
    with pytest.raises(GenplisM3UGException):
        parse_rules("rating invalid 4")
    with pytest.raises(GenplisM3UGException):
        parse_rules(">= invalid")
    with pytest.raises(GenplisM3UGException):
        parse_rules("invalid >=")
    with pytest.raises(GenplisM3UGException):
        parse_rules("rating > 4 invalid")


def test_equal_rule_list_value() -> None:
    rules = parse_rules("genre = Metal")
    assert rules[0].apply({"genre": ["Metal", "Rock"]})
    assert not rules[0].apply({"genre": ["Rock", "Pop"]})


def test_not_equal_rule_list_value() -> None:
    rules = parse_rules("genre != Metal")
    assert rules[0].apply({"genre": ["Rock", "Pop"]})
    assert not rules[0].apply({"genre": ["Metal", "Rock"]})


def test_equal_rule_numeric_string_value() -> None:
    rules = parse_rules("track = 7")
    assert rules[0].apply({"track": ["7"]})
    assert rules[0].apply({"track": "7"})
    assert rules[0].apply({"track": 7})
    assert not rules[0].apply({"track": ["8"]})
    assert not rules[0].apply({"track": "not a number"})


def test_not_equal_rule_numeric_string_value() -> None:
    rules = parse_rules("track != 7")
    assert rules[0].apply({"track": ["8"]})
    assert rules[0].apply({"track": "not a number"})
    assert not rules[0].apply({"track": ["7"]})
    assert not rules[0].apply({"track": 7})


def test_contains_rule_list_value() -> None:
    rules = parse_rules("genre ~= wave")
    assert rules[0].apply({"genre": ["Synthwave", "Retrowave"]})
    assert not rules[0].apply({"genre": ["Metal", "Rock"]})


def test_get_rating_from_fmps_rating() -> None:
    assert get_rating({"fmps_rating": ["0.8"]}) == pytest.approx(4.0)


def test_get_rating_ignores_non_numeric_fmps_rating(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level("WARNING", logger="genplis.m3ug"):
        assert get_rating({"fmps_rating": ["abc"]}) is None
        assert get_rating({"fmps_rating": [""]}) is None
        assert get_rating({"fmps_rating": ["0,8"]}) is None
        assert get_rating({"fmps_rating": ["abc", "0.8"]}) is None
        assert get_rating({"fmps_rating": True}) is None
    assert "Ignoring non-numeric fmps_rating" in caplog.text


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


def test_find_returns_falsy_tag_values() -> None:
    assert NameNode("track").find({"track": 0}) == ("track", 0)
    assert NameNode("is_lossless").find({"is_lossless": False}) == (
        "is_lossless",
        False,
    )
    assert NameNode("comment").find({"comment": ""}) == ("comment", "")
    assert NameNode("genre").find({"genre": []}) == ("genre", [])


def test_zero_and_empty_values_match_equality_rules() -> None:
    assert parse_rules("track = 0")[0].apply({"track": 0})
    assert parse_rules('comment = ""')[0].apply({"comment": ""})


def test_tag_names_are_case_insensitive_for_mixed_case_keys() -> None:
    assert parse_rules("ARTIST = X")[0].apply({"Artist": "X"})
    assert parse_rules("artist = X")[0].apply({"ARTIST": "X"})


def test_mixed_case_rating_tags_are_case_insensitive() -> None:
    assert NameNode("rating").find({"Rating": 4}) == ("rating", 4)
    assert NameNode("RATING").find({"FMPS_RATING": ["0.8"]}) == (
        "rating",
        pytest.approx(4.0),
    )
    assert get_rating({"FMPS_RATING": ["0.8"]}) == pytest.approx(4.0)
    assert get_rating({"RATING": 4, "FMPS_RATING": ["0.8"]}) is None


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
    assert parse_rules("""
# My favorite DANCE WITH THE DEAD songs
artist = DANCE WITH THE DEAD
rating >= 4
genre ~= Synthwave
    """) == [
        EqualRuleNode(NameNode("artist"), ValueNode("DANCE WITH THE DEAD")),
        GreaterOrEqualRuleNode(NameNode("rating"), ValueNode(4)),
        ContainsRuleNode(NameNode("genre"), ValueNode("Synthwave")),
    ]


def test_sort_directive_is_parsed_with_filters() -> None:
    parsed = parse_m3ug("@sort artist, album desc\nrating >= 4\n")

    assert parsed.sort == (
        SortKey("artist"),
        SortKey("album", descending=True),
    )
    assert parsed.rules == (GreaterOrEqualRuleNode(NameNode("rating"), ValueNode(4)),)


def test_sort_directive_can_appear_after_filters() -> None:
    parsed = parse_m3ug("rating >= 4\n@sort filename, duration desc\n")

    assert parsed.sort == (
        SortKey("filename"),
        SortKey("duration", descending=True),
    )


def test_sort_only_file_has_no_filter_rules() -> None:
    parsed = parse_m3ug("@sort title\n")

    assert parsed.rules == ()
    assert parsed.sort == (SortKey("title"),)


def test_sort_directive_is_case_insensitive() -> None:
    parsed = parse_m3ug("@SORT ARTIST DESC, Album\n")

    assert parsed.sort == (
        SortKey("artist", descending=True),
        SortKey("album"),
    )


def test_duplicate_sort_directive_is_an_error() -> None:
    with pytest.raises(
        GenplisM3UGException,
        match="Duplicate @sort directive; combine all keys on one line",
    ):
        parse_m3ug("@sort artist\n@sort album\n", "favorites.m3ug")


def test_sort_directive_needs_a_tag() -> None:
    with pytest.raises(GenplisM3UGException, match="@sort needs at least one tag"):
        parse_m3ug("@sort\n", "favorites.m3ug")


def test_invalid_sort_direction_is_an_error() -> None:
    with pytest.raises(GenplisM3UGException, match="invalid sort direction"):
        parse_m3ug("@sort artist sideways\n", "favorites.m3ug")


def test_unknown_directive_is_an_error() -> None:
    with pytest.raises(GenplisM3UGException, match="Unrecognized directive"):
        parse_m3ug("@group artist\n", "favorites.m3ug")


def test_examples_parse() -> None:
    """Every shipped example filter must remain valid."""
    examples_dir = Path(__file__).resolve().parent.parent / "examples"
    examples = sorted(examples_dir.glob("*.m3ug"))

    assert examples
    for example in examples:
        rules = parse_rules(example.read_text(encoding="utf-8"), str(example))
        assert rules, f"{example.name} should define at least one rule"
