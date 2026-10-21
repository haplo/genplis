from pathlib import Path

import pytest

from genplis.exceptions import GenplisM3UGException
from genplis.m3ug import (
    AndNode,
    ContainsRuleNode,
    EndsWithRuleNode,
    EqualRuleNode,
    GreaterOrEqualRuleNode,
    GreaterRuleNode,
    LesserOrEqualRuleNode,
    LesserRuleNode,
    LimitPerTag,
    NameNode,
    NotEqualRuleNode,
    NotNode,
    OrNode,
    RegexRuleNode,
    RuleNode,
    StartsWithRuleNode,
    ValueNode,
    format_expression,
    get_rating,
    parse_duration_literal,
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
    rules = parse_rules("genre ~ Synthwave")
    assert rules == [
        ContainsRuleNode(NameNode("genre"), ValueNode("Synthwave")),
    ]
    assert rules[0].apply({"genre": "Synthwave"})
    assert rules[0].apply({"genre": "Synthwave; Retrowave"})
    assert not rules[0].apply({"genre": "Synth; Electronic"})


def test_contains_rule_quoted_string_value() -> None:
    rules = parse_rules('genre ~ "Heavy Metal"')
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


def test_boolean_literals_compare_equal() -> None:
    equal = parse_rules("is_lossless = true")[0]
    assert equal == EqualRuleNode(NameNode("is_lossless"), ValueNode(True))
    assert equal.apply({"is_lossless": True})
    assert not equal.apply({"is_lossless": False})
    assert not equal.apply({})

    assert parse_rules("is_lossless != false")[0].apply({"is_lossless": True})
    assert not parse_rules("is_lossless != false")[0].apply({"is_lossless": False})


def test_quoted_booleans_are_strings() -> None:
    rule = parse_rules('genre = "true"')[0]
    assert rule == EqualRuleNode(NameNode("genre"), ValueNode("true"))
    assert rule.apply({"genre": "true"})
    assert not rule.apply({"genre": True})


def test_text_operators_treat_booleans_as_strings() -> None:
    rule = parse_rules("comment ~ true")[0]
    assert rule == ContainsRuleNode(NameNode("comment"), ValueNode("true"))
    assert rule.apply({"comment": "this is true"})
    assert not rule.apply({"comment": True})


def test_numeric_operators_reject_booleans() -> None:
    with pytest.raises(GenplisM3UGException, match="numeric value"):
        parse_rules("rating > true")


def test_text_operator_on_boolean_tag_warns_once(
    caplog: pytest.LogCaptureFixture,
) -> None:
    rule = parse_rules("comment ~ true")[0]
    with caplog.at_level("WARNING", logger="genplis.m3ug"):
        assert not rule.apply({"comment": True})
        assert not rule.apply({"comment": False})

    assert caplog.messages == [
        "text operator '~' applied to boolean tag 'comment'; use = true or = false"
    ]


def test_text_matching_is_case_insensitive_by_default() -> None:
    assert parse_rules("genre = metal")[0].apply({"genre": "Metal"})
    assert parse_rules("genre != metal")[0].apply({"genre": "Rock"})
    assert not parse_rules("genre != metal")[0].apply({"genre": "METAL"})
    assert parse_rules("genre ~ metal")[0].apply({"genre": "Heavy Metal"})
    assert parse_rules("genre ^ heavy")[0].apply({"genre": "Heavy Metal"})
    assert parse_rules("genre $ metal")[0].apply({"genre": "Heavy Metal"})
    assert parse_rules("genre % ^heavy")[0].apply({"genre": "Heavy Metal"})


def test_case_modifier_makes_one_rule_case_sensitive() -> None:
    sensitive = parse_rules('@CASE artist = "DANCE WITH THE DEAD"')[0]
    assert sensitive == EqualRuleNode(
        NameNode("artist"), ValueNode("DANCE WITH THE DEAD"), case_sensitive=True
    )
    assert sensitive.apply({"artist": "DANCE WITH THE DEAD"})
    assert not sensitive.apply({"artist": "Dance With The Dead"})

    default = parse_rules("artist = x\ngenre = metal\n")[0]
    assert default.apply({"artist": "X"})
    assert parse_rules("genre = metal\n")[0].apply({"genre": "Metal"})


def test_case_modifier_applies_to_text_operators() -> None:
    rule = parse_rules("@CASE genre ~ Metal")[0]
    assert rule.apply({"genre": "Heavy Metal"})
    assert not rule.apply({"genre": "heavy metal"})

    regex = parse_rules("@CASE genre % ^metal")[0]
    assert regex.apply({"genre": "metalcore"})
    assert not regex.apply({"genre": "Metalcore"})


def test_case_modifier_is_an_error_for_comparisons() -> None:
    with pytest.raises(GenplisM3UGException, match="@CASE"):
        parse_rules("@CASE rating > 4")


def test_regex_operator_uses_search_and_inline_flags() -> None:
    assert parse_rules("genre % Metal")[0].apply({"genre": "Heavy Metal"})
    assert not parse_rules("genre % ^Metal")[0].apply({"genre": "Heavy Metal"})
    assert parse_rules("genre % (?-i)Metal")[0].apply({"genre": "Heavy Metal"})
    assert not parse_rules("genre % (?-i)Metal")[0].apply({"genre": "heavy metal"})


def test_invalid_regex_reports_location() -> None:
    with pytest.raises(
        GenplisM3UGException,
        match=r"favorites\.m3ug:3: Invalid regular expression",
    ):
        parse_m3ug("artist = X\n\n@CASE genre % [\n", "favorites.m3ug")


def test_quotes_support_escapes_and_preserve_regex_backslashes() -> None:
    assert parse_rules(r'artist = "He said \"hi\""')[0].apply(
        {"artist": 'He said "hi"'}
    )
    assert parse_rules(r"artist = 'it\'s fine'")[0].apply({"artist": "it's fine"})
    assert parse_rules(r'artist = "a\\b"')[0].apply({"artist": r"a\b"})
    assert parse_rules(r"filename % \.mp3$")[0].apply({"filename": "/music/song.mp3"})
    assert parse_rules(r'filename % "\\.mp3$"')[0].apply(
        {"filename": "/music/song.mp3"}
    )


def test_new_text_operators() -> None:
    starts = parse_rules("artist ^ DANCE")[0]
    assert starts == StartsWithRuleNode(NameNode("artist"), ValueNode("DANCE"))
    assert starts.apply({"artist": "DANCE WITH THE DEAD"})
    assert not starts.apply({"artist": "The DANCE"})

    ends = parse_rules("artist $ DEAD")[0]
    assert ends == EndsWithRuleNode(NameNode("artist"), ValueNode("DEAD"))
    assert ends.apply({"artist": "DANCE WITH THE DEAD"})
    assert not ends.apply({"artist": "DEAD DANCE"})

    regex = parse_rules('genre % "^(Synth|Retro)wave$"')[0]
    assert regex == RegexRuleNode(NameNode("genre"), ValueNode("^(Synth|Retro)wave$"))
    assert regex.apply({"genre": "Synthwave"})
    assert not regex.apply({"genre": "Synthwave; Electronic"})


def test_text_operators_use_string_values_for_numbers() -> None:
    rule = parse_rules("title ~ 1980")[0]
    assert rule.value_node == ValueNode("1980")
    assert rule.apply({"title": "Songs from 1980"})


def test_multi_tag_and_multi_value_sets_are_existential() -> None:
    parsed = parse_m3ug("[genre | style] = [Metal | Rock]")

    assert parsed.rules == (
        EqualRuleNode(NameNode("genre"), ValueNode("Metal")),
        EqualRuleNode(NameNode("genre"), ValueNode("Rock")),
        EqualRuleNode(NameNode("style"), ValueNode("Metal")),
        EqualRuleNode(NameNode("style"), ValueNode("Rock")),
    )
    assert parsed.expression is not None
    assert parsed.expression.apply({"genre": "Rock"})
    assert parsed.expression.apply({"style": "Metal"})
    assert not parsed.expression.apply({"genre": "Pop"})
    assert not parsed.expression.apply({})


def test_multi_value_text_operators() -> None:
    rule = parse_m3ug("[filename | comment] ~ [Live | Bootleg]").expression
    assert rule is not None
    assert rule.apply({"filename": "/music/Live at Wembley.mp3"})
    assert rule.apply({"comment": ["studio", "bootleg recording"]})
    assert not rule.apply({"comment": "studio"})


def test_not_equal_set_is_universal_non_membership() -> None:
    rule = parse_m3ug("[genre | style] != [Pop | Rap]").expression
    assert rule is not None
    assert rule.apply({"genre": "Metal", "style": "Rock"})
    assert not rule.apply({"genre": "Pop"})
    assert not rule.apply({"style": "Rap"})
    assert not rule.apply({"genre": ["Metal", "Pop"]})
    assert rule.apply({})


def test_multi_tag_comparisons_are_existential() -> None:
    rule = parse_m3ug("[year | original_year] >= 1980").expression
    assert rule is not None
    assert rule.apply({"year": 1970, "original_year": 1985})
    assert not rule.apply({"year": 1970, "original_year": 1975})
    assert not rule.apply({})


def test_comparison_rejects_multiple_values() -> None:
    with pytest.raises(
        GenplisM3UGException,
        match="comparison operators take exactly one value; use @OR",
    ):
        parse_m3ug("rating > [3 | 4]", "favorites.m3ug")


def test_quoted_pipes_and_bracket_literals() -> None:
    assert parse_m3ug('title = "[Intro | Outro]"').rules == (
        EqualRuleNode(NameNode("title"), ValueNode("[Intro | Outro]")),
    )
    assert parse_m3ug("title = [Untitled]").rules == (
        EqualRuleNode(NameNode("title"), ValueNode("[Untitled]")),
    )
    assert parse_m3ug("title = []").rules == (
        EqualRuleNode(NameNode("title"), ValueNode("[]")),
    )

    rule = parse_m3ug('artist = ["AC|DC" | "A|B"]').expression
    assert rule is not None
    assert rule.apply({"artist": "AC|DC"})
    assert rule.apply({"artist": "A|B"})
    assert not rule.apply({"artist": "AC"})


def test_empty_and_nested_set_elements_are_errors() -> None:
    for content in (
        "[genre | ] = Metal",
        "[genre | style] = [Metal | ]",
        "[genre | [style]] = Metal",
        "title = [Metal | [Rock]]",
    ):
        with pytest.raises(GenplisM3UGException):
            parse_m3ug(content, "favorites.m3ug")


def test_tag_set_elements_must_be_bare_names() -> None:
    with pytest.raises(GenplisM3UGException, match="Invalid tag name in set"):
        parse_m3ug('[genre | "style"] = Metal', "favorites.m3ug")
    with pytest.raises(GenplisM3UGException, match="Invalid tag name in set"):
        parse_m3ug("[genre | album style] = Metal", "favorites.m3ug")


def test_case_modifier_applies_to_every_set_pair() -> None:
    parsed = parse_m3ug("@CASE [artist | albumartist] = [X | Y]")
    assert parsed.expression is not None
    assert parsed.expression.apply({"artist": "X", "albumartist": "Y"})
    assert not parsed.expression.apply({"artist": "x"})
    assert all(rule.case_sensitive for rule in parsed.rules)


def test_boolean_values_in_sets() -> None:
    rule = parse_m3ug("[is_lossless | is_vbr] = [true | false]").expression
    assert rule is not None
    assert rule.apply({"is_lossless": True})
    assert rule.apply({"is_vbr": False})
    assert not rule.apply({"is_lossless": "true"})


def test_multi_tag_missing_values_follow_operator_rules() -> None:
    equal = parse_m3ug("[genre | style] = Metal").expression
    not_equal = parse_m3ug("[genre | style] != Metal").expression
    assert equal is not None and not_equal is not None
    assert not equal.apply({})
    assert not_equal.apply({})
    assert equal.apply({"style": "Metal"})


def test_multi_value_sets_combine_with_tag_value_lists() -> None:
    rule = parse_m3ug("genre = [Metal | Rock]").expression
    assert rule is not None
    assert rule.apply({"genre": ["Pop", "Rock"]})
    assert not rule.apply({"genre": ["Pop", "Jazz"]})

    not_rule = parse_m3ug("genre != [Metal | Rock]").expression
    assert not_rule is not None
    assert not_rule.apply({"genre": ["Pop", "Jazz"]})
    assert not not_rule.apply({"genre": ["Pop", "Rock"]})


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


def test_utf8_bom_is_ignored_by_the_parser() -> None:
    assert parse_rules("\ufeffartist = X\n") == [
        EqualRuleNode(NameNode("artist"), ValueNode("X"))
    ]


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
    rules = parse_rules("genre ~ wave")
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
genre ~ Synthwave
    """) == [
        EqualRuleNode(NameNode("artist"), ValueNode("DANCE WITH THE DEAD")),
        GreaterOrEqualRuleNode(NameNode("rating"), ValueNode(4)),
        ContainsRuleNode(NameNode("genre"), ValueNode("Synthwave")),
    ]


def test_expression_tree_flattens_rules() -> None:
    parsed = parse_m3ug("artist = X\nrating >= 4\n")

    assert isinstance(parsed.expression, AndNode)
    assert parsed.rules == (
        EqualRuleNode(NameNode("artist"), ValueNode("X")),
        GreaterOrEqualRuleNode(NameNode("rating"), ValueNode(4)),
    )
    assert format_expression(parsed.expression) == "artist = X AND rating >= 4"


def test_empty_expression_matches_everything() -> None:
    parsed = parse_m3ug("\n")

    assert parsed.expression is None
    assert parsed.rules == ()
    assert format_expression(parsed.expression) == "(always)"


def test_expression_nodes_apply_logic() -> None:
    first = EqualRuleNode(NameNode("artist"), ValueNode("X"))
    second = EqualRuleNode(NameNode("genre"), ValueNode("Metal"))

    assert AndNode((first, second)).apply({"artist": "X", "genre": "Metal"})
    assert OrNode((first, second)).apply({"artist": "X", "genre": "Rock"})
    assert NotNode(first).apply({"artist": "Y"})
    assert format_expression(OrNode((first, second))) == (
        "(artist = X OR genre = Metal)"
    )
    assert format_expression(NotNode(first)) == "NOT (artist = X)"


def test_or_groups_rules_in_cnf() -> None:
    parsed = parse_m3ug("genre = Metal\n@OR genre = Rock\nrating >= 4\n")

    assert isinstance(parsed.expression, AndNode)
    assert len(parsed.expression.nodes) == 2
    assert isinstance(parsed.expression.nodes[0], OrNode)
    assert format_expression(parsed.expression) == (
        "(genre = Metal OR genre = Rock) AND rating >= 4"
    )
    assert parsed.expression.apply({"genre": "Metal", "rating": 5})
    assert parsed.expression.apply({"genre": "Rock", "rating": 4})
    assert not parsed.expression.apply({"genre": "Pop", "rating": 5})
    assert not parsed.expression.apply({"genre": "Metal", "rating": 3})


def test_or_cannot_be_the_first_rule() -> None:
    with pytest.raises(GenplisM3UGException, match="@OR cannot be the first rule"):
        parse_m3ug("@OR genre = Metal\n", "favorites.m3ug")


def test_or_and_not_need_a_rule() -> None:
    with pytest.raises(GenplisM3UGException, match="@OR needs a rule"):
        parse_m3ug("genre = Metal\n@OR\n", "favorites.m3ug")
    with pytest.raises(GenplisM3UGException, match="@NOT needs a rule"):
        parse_m3ug("@NOT\n", "favorites.m3ug")


def test_not_negates_one_rule() -> None:
    parsed = parse_m3ug("@NOT rating >= 4\n")

    assert isinstance(parsed.expression, AndNode)
    assert isinstance(parsed.expression.nodes[0], NotNode)
    assert format_expression(parsed.expression) == "NOT (rating >= 4)"
    assert parsed.expression.apply({"rating": 3})
    assert not parsed.expression.apply({"rating": 4})
    assert parsed.expression.apply({})


def test_or_not_and_case_combine_in_any_order() -> None:
    parsed = parse_m3ug(
        "@CASE artist = X\n@OR @NOT @CASE artist = Y\n@OR @CASE @NOT artist = Z\n"
    )

    assert parsed.expression is not None
    assert parsed.expression.apply({"artist": "X"})
    assert parsed.expression.apply({"artist": "Y"})
    assert all(rule.case_sensitive for rule in parsed.rules)
    assert not parsed.rules[0].apply({"artist": "x"})
    assert not parsed.rules[1].apply({"artist": "y"})


def test_directives_do_not_end_an_or_group() -> None:
    parsed = parse_m3ug("genre = Metal\n@sort title\n@OR genre = Rock\nrating >= 4\n")

    assert parsed.sort == (SortKey("title"),)
    assert parsed.expression is not None
    assert parsed.expression.apply({"genre": "Rock", "rating": 4})
    assert not parsed.expression.apply({"genre": "Rock", "rating": 3})


def test_not_applies_to_a_whole_set() -> None:
    parsed = parse_m3ug("@NOT [genre | style] = [Metal | Rock]\n")

    assert parsed.expression is not None
    assert not parsed.expression.apply({"genre": "Rock"})
    assert parsed.expression.apply({"genre": "Pop"})
    assert parsed.expression.apply({})


def test_not_does_not_negate_a_group() -> None:
    parsed = parse_m3ug("genre = Metal\n@OR @NOT genre = Rock\n")

    assert parsed.expression is not None
    assert isinstance(parsed.expression, AndNode)
    assert isinstance(parsed.expression.nodes[0], OrNode)
    assert parsed.expression.apply({"genre": "Metal"})
    assert parsed.expression.apply({"genre": "Pop"})
    assert not parsed.expression.apply({"genre": "Rock"})


def test_comparison_negation_and_missing_tags() -> None:
    negated = parse_m3ug("@NOT rating >= 4\n").expression
    direct = parse_m3ug("rating < 4\n").expression
    assert negated is not None and direct is not None
    assert negated.apply({})
    assert not direct.apply({})


@pytest.mark.parametrize(
    ("literal", "seconds"),
    [
        ("600", 600),
        ("10m", 600),
        ("1h30m", 5400),
        ("2m15s", 135),
        ("30s", 30),
        ("2d", 172800),
        ("1:30", 90),
        ("90:00", 5400),
        ("1:30:00", 5400),
        ("0", 0),
    ],
)
def test_duration_literals(literal: str, seconds: float) -> None:
    assert parse_duration_literal(literal) == seconds


@pytest.mark.parametrize(
    "literal", ["", "10M", "1:60", "1:61:00", "1:30:60", "-5", "nope", "1.5m"]
)
def test_invalid_duration_literals(literal: str) -> None:
    assert parse_duration_literal(literal) is None


def test_duration_values_are_numeric_for_duration_tag() -> None:
    for literal, seconds in (
        ("10m", 600),
        ("2m15s", 135),
        ("1:30", 90),
        ("1:30:00", 5400),
    ):
        rule = parse_rules(f"duration >= {literal}")[0]
        assert rule == GreaterOrEqualRuleNode(NameNode("duration"), ValueNode(seconds))
        assert rule.apply({"duration": seconds})
        assert not rule.apply({"duration": seconds - 1})


def test_duration_literals_require_every_tag_to_be_duration() -> None:
    assert parse_rules("title = 10m")[0].value_node == ValueNode("10m")
    assert parse_m3ug("[duration | bitrate] = 10m").rules[0].value_node == ValueNode(
        "10m"
    )
    with pytest.raises(GenplisM3UGException, match="numeric value"):
        parse_rules("rating > 10m")


def test_quoted_duration_literals_are_strings() -> None:
    assert parse_rules('duration = "10m"')[0].value_node == ValueNode("10m")
    with pytest.raises(GenplisM3UGException, match="numeric value"):
        parse_rules('duration > "10m"')


def test_limit_and_max_duration_directives() -> None:
    parsed = parse_m3ug("@LIMIT 10\n@MAX-DURATION 1h30m\nartist = X\n")

    assert parsed.limit == 10
    assert parsed.max_duration == 5400
    assert parsed.expression is not None
    assert parsed.expression.apply({"artist": "X"})


def test_limit_zero_is_unlimited() -> None:
    assert parse_m3ug("@LIMIT 0\n").limit == 0


def test_limit_per_tag_directive() -> None:
    parsed = parse_m3ug("@LIMIT 5 PER Artist\n")

    assert parsed.limit is None
    assert parsed.limit_per == LimitPerTag(5, "artist")


def test_limit_per_tag_zero_disables_it() -> None:
    assert parse_m3ug("@LIMIT 0 PER artist\n").limit_per == LimitPerTag(0, "artist")


def test_global_and_per_tag_limits_coexist() -> None:
    parsed = parse_m3ug("@LIMIT 10\n@LIMIT 3 PER artist\n")

    assert parsed.limit == 10
    assert parsed.limit_per == LimitPerTag(3, "artist")


@pytest.mark.parametrize(
    "directive",
    [
        "@LIMIT 5 PER",
        "@LIMIT 5 PER artist extra",
        "@LIMIT -1 PER artist",
        "@LIMIT 1.5 PER artist",
        "@LIMIT x PER artist",
        '@LIMIT 5 PER "artist"',
        "@LIMIT 5 PER [artist]",
        "@LIMIT 5 PER artist,album",
    ],
)
def test_invalid_per_tag_limit_is_an_error(directive: str) -> None:
    with pytest.raises(GenplisM3UGException, match="@LIMIT"):
        parse_m3ug(f"{directive}\n", "favorites.m3ug")


def test_duplicate_per_tag_limit_is_an_error() -> None:
    with pytest.raises(GenplisM3UGException, match="Duplicate @LIMIT"):
        parse_m3ug(
            "@LIMIT 2 PER artist\n@LIMIT 3 PER album\n",
            "favorites.m3ug",
        )


def test_max_duration_zero_is_unlimited() -> None:
    assert parse_m3ug("@MAX-DURATION 0\n").max_duration == 0


@pytest.mark.parametrize("directive", ["@LIMIT -1", "@LIMIT x", "@LIMIT 1.5"])
def test_invalid_limit_is_an_error(directive: str) -> None:
    with pytest.raises(GenplisM3UGException, match="@LIMIT"):
        parse_m3ug(f"{directive}\n", "favorites.m3ug")


@pytest.mark.parametrize("directive", ["@MAX-DURATION -1", "@MAX-DURATION nope"])
def test_invalid_max_duration_is_an_error(directive: str) -> None:
    with pytest.raises(GenplisM3UGException, match="@MAX-DURATION"):
        parse_m3ug(f"{directive}\n", "favorites.m3ug")


def test_duplicate_limit_and_max_duration_are_errors() -> None:
    with pytest.raises(GenplisM3UGException, match="Duplicate @LIMIT"):
        parse_m3ug("@LIMIT 1\n@LIMIT 2\n", "favorites.m3ug")
    with pytest.raises(GenplisM3UGException, match="Duplicate @MAX-DURATION"):
        parse_m3ug("@MAX-DURATION 1m\n@MAX-DURATION 2m\n", "favorites.m3ug")


def test_dedupe_directive() -> None:
    parsed = parse_m3ug("@DEDUPE title, Album, artist\n")

    assert parsed.dedupe == ("title", "album", "artist")
    assert parsed.expression is None


def test_dedupe_without_keys_disables_it() -> None:
    assert parse_m3ug("@DEDUPE\n").dedupe == ()


def test_dedupe_rejects_duplicates_and_empty_keys() -> None:
    with pytest.raises(GenplisM3UGException, match="Duplicate @DEDUPE key"):
        parse_m3ug("@DEDUPE title, Title\n", "favorites.m3ug")
    with pytest.raises(GenplisM3UGException, match="Empty @DEDUPE key"):
        parse_m3ug("@DEDUPE title,,album\n", "favorites.m3ug")
    with pytest.raises(GenplisM3UGException, match="Empty @DEDUPE key"):
        parse_m3ug("@DEDUPE title,\n", "favorites.m3ug")


def test_duplicate_dedupe_directive_is_an_error() -> None:
    with pytest.raises(GenplisM3UGException, match="Duplicate @DEDUPE"):
        parse_m3ug("@DEDUPE title\n@DEDUPE album\n", "favorites.m3ug")


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


def test_sort_directive_without_keys_means_walk_order() -> None:
    parsed = parse_m3ug("@sort\n", "favorites.m3ug")

    assert parsed.sort == ()


def test_sort_random_directive() -> None:
    assert parse_m3ug("@sort random\n").sort == (SortKey("random"),)
    assert parse_m3ug("@sort random 42\n").sort == (SortKey("random", seed=42),)
    assert parse_m3ug("@sort artist, random 7\n").sort == (
        SortKey("artist"),
        SortKey("random", seed=7),
    )


@pytest.mark.parametrize(
    "spec",
    [
        "random desc",
        "random asc",
        "random -1",
        "random 1.5",
        "random 1, artist",
        "random, random",
    ],
)
def test_invalid_random_sort_keys_are_errors(spec: str) -> None:
    with pytest.raises(GenplisM3UGException):
        parse_m3ug(f"@sort {spec}\n", "favorites.m3ug")


def test_invalid_sort_direction_is_an_error() -> None:
    with pytest.raises(GenplisM3UGException, match="invalid sort direction"):
        parse_m3ug("@sort artist sideways\n", "favorites.m3ug")


def test_unknown_directive_is_an_error() -> None:
    with pytest.raises(GenplisM3UGException, match="Unrecognized directive"):
        parse_m3ug("@group artist\n", "favorites.m3ug")


def test_include_adds_its_rules_as_a_separate_and_group(tmp_path: Path) -> None:
    main = tmp_path / "Main.m3ug"
    base = tmp_path / "Base.m3ug"
    base.write_text("genre = Metal\n", encoding="utf-8")
    main.write_text("@INCLUDE Base.m3ug\nrating >= 4\n", encoding="utf-8")

    parsed = parse_m3ug(main.read_text(), str(main))

    assert parsed.expression is not None
    assert parsed.expression.apply({"genre": "Metal", "rating": 4})
    assert not parsed.expression.apply({"genre": "Rock", "rating": 4})
    assert not parsed.expression.apply({"genre": "Metal", "rating": 3})
    assert len(parsed.rules) == 2


def test_include_does_not_join_the_current_or_group(tmp_path: Path) -> None:
    main = tmp_path / "Main.m3ug"
    base = tmp_path / "Base.m3ug"
    base.write_text("artist = X\n", encoding="utf-8")
    main.write_text(
        "genre = Metal\n@INCLUDE Base.m3ug\n@OR genre = Rock\n",
        encoding="utf-8",
    )

    parsed = parse_m3ug(main.read_text(), str(main))

    assert parsed.expression is not None
    assert parsed.expression.apply({"artist": "X", "genre": "Rock"})
    assert not parsed.expression.apply({"genre": "Rock"})


def test_include_directive_precedence(tmp_path: Path) -> None:
    first = tmp_path / "First.m3ug"
    second = tmp_path / "Second.m3ug"
    main = tmp_path / "Main.m3ug"
    first.write_text(
        "@SORT artist\n@LIMIT 5\n@DEDUPE title\n@MAX-DURATION 1h\ngenre = Metal\n",
        encoding="utf-8",
    )
    second.write_text("@SORT album\n@MAX-DURATION 2h\n", encoding="utf-8")
    main.write_text(
        "@INCLUDE First.m3ug\n@INCLUDE Second.m3ug\n@LIMIT 2\nrating >= 4\n",
        encoding="utf-8",
    )

    parsed = parse_m3ug(main.read_text(), str(main))

    assert parsed.sort == (SortKey("album"),)
    assert parsed.limit == 2
    assert parsed.dedupe == ("title",)
    assert parsed.max_duration == 7200


def test_current_file_directive_wins_regardless_of_position(tmp_path: Path) -> None:
    base = tmp_path / "Base.m3ug"
    main = tmp_path / "Main.m3ug"
    base.write_text("@LIMIT 5\n@SORT artist\n", encoding="utf-8")
    main.write_text(
        "@LIMIT 1\n@INCLUDE Base.m3ug\n@SORT title\n",
        encoding="utf-8",
    )

    parsed = parse_m3ug(main.read_text(), str(main))

    assert parsed.limit == 1
    assert parsed.sort == (SortKey("title"),)


def test_per_tag_limit_merges_from_includes(tmp_path: Path) -> None:
    base = tmp_path / "Base.m3ug"
    main = tmp_path / "Main.m3ug"
    base.write_text(
        "@LIMIT 100\n@LIMIT 5 PER artist\n",
        encoding="utf-8",
    )
    main.write_text(
        "@INCLUDE Base.m3ug\n@LIMIT 2 PER album\n",
        encoding="utf-8",
    )

    parsed = parse_m3ug(main.read_text(), str(main))

    assert parsed.limit == 100
    assert parsed.limit_per == LimitPerTag(2, "album")


def test_per_tag_limit_zero_overrides_included_default(tmp_path: Path) -> None:
    base = tmp_path / "Base.m3ug"
    main = tmp_path / "Main.m3ug"
    base.write_text("@LIMIT 5 PER artist\n", encoding="utf-8")
    main.write_text("@INCLUDE Base.m3ug\n@LIMIT 0 PER artist\n", encoding="utf-8")

    parsed = parse_m3ug(main.read_text(), str(main))

    assert parsed.limit_per == LimitPerTag(0, "artist")


def test_nested_include_merges_depth_first(tmp_path: Path) -> None:
    deepest = tmp_path / "Deepest.m3ug"
    middle = tmp_path / "Middle.m3ug"
    main = tmp_path / "Main.m3ug"
    deepest.write_text("@LIMIT 5\n@DEDUPE title\ngenre = Metal\n", encoding="utf-8")
    middle.write_text(
        "@INCLUDE Deepest.m3ug\n@LIMIT 3\nrating >= 4\n", encoding="utf-8"
    )
    main.write_text("@INCLUDE Middle.m3ug\n@DEDUPE album\n", encoding="utf-8")

    parsed = parse_m3ug(main.read_text(), str(main))

    assert parsed.limit == 3
    assert parsed.dedupe == ("album",)
    assert parsed.expression is not None
    assert parsed.expression.apply({"genre": "Metal", "rating": 4})
    assert not parsed.expression.apply({"genre": "Metal", "rating": 3})
    assert len(parsed.rules) == 2


def test_include_paths_are_relative_to_the_containing_file(tmp_path: Path) -> None:
    subdirectory = tmp_path / "sub"
    subdirectory.mkdir()
    base = subdirectory / "Base file.m3ug"
    main = tmp_path / "Main.m3ug"
    base.write_text("genre = Metal\n", encoding="utf-8")
    main.write_text('@INCLUDE "sub/Base file.m3ug"\n', encoding="utf-8")

    parsed = parse_m3ug(main.read_text(), str(main))

    assert parsed.expression is not None
    assert parsed.expression.apply({"genre": "Metal"})


def test_include_expands_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    base = tmp_path / "Base.m3ug"
    base.write_text("genre = Metal\n", encoding="utf-8")
    main = tmp_path / "Main.m3ug"
    main.write_text("@INCLUDE ~/Base.m3ug\n", encoding="utf-8")

    parsed = parse_m3ug(main.read_text(), str(main))

    assert parsed.expression is not None
    assert parsed.expression.apply({"genre": "Metal"})


def test_include_loader_callback(tmp_path: Path) -> None:
    main = tmp_path / "Main.m3ug"
    base = (tmp_path / "Base.m3ug").resolve()
    main.write_text("@INCLUDE Base.m3ug\n", encoding="utf-8")
    loaded: list[Path] = []

    def loader(path: Path) -> str:
        loaded.append(path)
        return "genre = Metal\n"

    parsed = parse_m3ug(main.read_text(), str(main), include_loader=loader)

    assert loaded == [base]
    assert parsed.expression is not None
    assert parsed.expression.apply({"genre": "Metal"})


def test_include_loader_missing_entry_is_fatal(tmp_path: Path) -> None:
    main = tmp_path / "Metal.m3ug"
    main.write_text("@INCLUDE Base.m3ug\n", encoding="utf-8")
    files: dict[Path, str] = {}

    with pytest.raises(GenplisM3UGException, match="file not found"):
        parse_m3ug(
            main.read_text(),
            str(main),
            include_loader=lambda path: files[path],
        )


def test_missing_include_is_fatal(tmp_path: Path) -> None:
    main = tmp_path / "Metal.m3ug"
    main.write_text("@INCLUDE Base.m3ug\n", encoding="utf-8")

    with pytest.raises(
        GenplisM3UGException,
        match=r'cannot include "Base\.m3ug": file not found',
    ):
        parse_m3ug(main.read_text(), str(main))


def test_include_directory_is_fatal(tmp_path: Path) -> None:
    main = tmp_path / "Metal.m3ug"
    (tmp_path / "Base.m3ug").mkdir()
    main.write_text("@INCLUDE Base.m3ug\n", encoding="utf-8")

    with pytest.raises(
        GenplisM3UGException,
        match=r'cannot include "Base\.m3ug": path is a directory',
    ):
        parse_m3ug(main.read_text(), str(main))


def test_unreadable_include_is_fatal(tmp_path: Path) -> None:
    main = tmp_path / "Metal.m3ug"
    main.write_text("@INCLUDE Base.m3ug\n", encoding="utf-8")

    def loader(path: Path) -> str:
        raise PermissionError(path)

    with pytest.raises(GenplisM3UGException, match="cannot read file"):
        parse_m3ug(main.read_text(), str(main), include_loader=loader)


def test_include_cycle_reports_the_chain(tmp_path: Path) -> None:
    first = tmp_path / "Metal.m3ug"
    second = tmp_path / "Base.m3ug"
    first.write_text("@INCLUDE Base.m3ug\n", encoding="utf-8")
    second.write_text("@INCLUDE Metal.m3ug\n", encoding="utf-8")

    with pytest.raises(
        GenplisM3UGException,
        match=r"include cycle: Metal\.m3ug -> Base\.m3ug -> Metal\.m3ug",
    ):
        parse_m3ug(first.read_text(), str(first))


def test_include_depth_is_limited(tmp_path: Path) -> None:
    for index in range(34):
        content = f"@INCLUDE file-{index + 1}.m3ug\n"
        (tmp_path / f"file-{index}.m3ug").write_text(content, encoding="utf-8")
    (tmp_path / "file-34.m3ug").write_text("genre = Metal\n", encoding="utf-8")
    first = tmp_path / "file-0.m3ug"

    with pytest.raises(GenplisM3UGException, match="include depth exceeded"):
        parse_m3ug(first.read_text(), str(first))


def test_invalid_included_syntax_reports_the_included_file(tmp_path: Path) -> None:
    main = tmp_path / "Metal.m3ug"
    base = tmp_path / "Base.m3ug"
    base.write_text("invalid\n", encoding="utf-8")
    main.write_text("@INCLUDE Base.m3ug\n", encoding="utf-8")

    with pytest.raises(
        GenplisM3UGException,
        match=r"Base\.m3ug:1: Invalid filter syntax",
    ):
        parse_m3ug(main.read_text(), str(main))


def test_include_needs_a_path(tmp_path: Path) -> None:
    main = tmp_path / "Metal.m3ug"
    main.write_text("@INCLUDE\n", encoding="utf-8")

    with pytest.raises(GenplisM3UGException, match="@INCLUDE needs a path"):
        parse_m3ug(main.read_text(), str(main))


def test_include_cannot_be_used_with_rule_modifiers(tmp_path: Path) -> None:
    main = tmp_path / "Metal.m3ug"
    base = tmp_path / "Base.m3ug"
    base.write_text("genre = Metal\n", encoding="utf-8")
    main.write_text("@OR @INCLUDE Base.m3ug\n", encoding="utf-8")

    with pytest.raises(
        GenplisM3UGException,
        match="@INCLUDE cannot be used under @OR or @NOT",
    ):
        parse_m3ug(main.read_text(), str(main))


def test_no_playlist_directive() -> None:
    parsed = parse_m3ug("@NO-PLAYLIST\nartist = X\n")

    assert parsed.no_playlist is True
    assert parsed.expression is not None
    assert parsed.expression.apply({"artist": "X"})


def test_no_playlist_rejects_arguments_and_duplicates() -> None:
    with pytest.raises(GenplisM3UGException, match="takes no arguments"):
        parse_m3ug("@NO-PLAYLIST yes\n", "favorites.m3ug")
    with pytest.raises(GenplisM3UGException, match="Duplicate @NO-PLAYLIST"):
        parse_m3ug("@NO-PLAYLIST\n@NO-PLAYLIST\n", "favorites.m3ug")


def test_no_playlist_is_not_inherited_from_includes(tmp_path: Path) -> None:
    base = tmp_path / "Base.m3ug"
    main = tmp_path / "Main.m3ug"
    base.write_text("@NO-PLAYLIST\nartist = X\n", encoding="utf-8")
    main.write_text("@INCLUDE Base.m3ug\n", encoding="utf-8")

    parsed_base = parse_m3ug(base.read_text(), str(base))
    parsed_main = parse_m3ug(main.read_text(), str(main))

    assert parsed_base.no_playlist is True
    assert parsed_main.no_playlist is False
    assert parsed_main.expression is not None
    assert parsed_main.expression.apply({"artist": "X"})


def test_examples_parse() -> None:
    """Every shipped example filter must remain valid."""
    examples_dir = Path(__file__).resolve().parent.parent / "examples"
    examples = sorted(examples_dir.glob("*.m3ug"))

    assert examples
    for example in examples:
        rules = parse_rules(example.read_text(encoding="utf-8"), str(example))
        assert rules, f"{example.name} should define at least one rule"
