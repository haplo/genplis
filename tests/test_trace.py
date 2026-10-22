from pathlib import Path

import pytest

from genplis.diagnostics import (
    FileTrace,
    format_file_trace,
    format_tags_consulted,
    trace_expression,
    trace_file,
)
from genplis.m3ug import parse_m3ug
from genplis.types import Tags


def trace(content: str, tags: Tags, filename: str = "N/A") -> FileTrace:
    return trace_file(parse_m3ug(content, filename), tags)


def test_and_short_circuits_after_a_failure() -> None:
    result = trace(
        "artist = X\nrating >= 4\ngenre ~ Metal\n",
        {"artist": ["X"], "rating": 3, "genre": "Metal"},
    )

    output = format_file_trace(result, title="Favorites.m3ug")
    assert result.passed is False
    assert "FAIL AND" in output
    assert "PASS artist = X (line 1)" in output
    assert "FAIL rating >= 4 (line 2)" in output
    assert (
        "SKIP genre ~ Metal (line 3) "
        "(short-circuited: an earlier AND child failed)" in output
    )
    assert "tag genre" not in output


def test_or_short_circuits_after_a_pass() -> None:
    result = trace(
        "genre = Metal\n@OR genre = Rock\nartist = X\n",
        {"genre": "Metal", "artist": "X"},
    )

    output = format_file_trace(result, title="Favorites.m3ug")
    assert result.passed is True
    assert "PASS OR" in output
    assert "PASS genre = Metal (line 1)" in output
    assert (
        "SKIP genre = Rock (line 2) "
        "(short-circuited: an earlier OR child passed)" in output
    )
    assert "PASS artist = X (line 3)" in output


def test_not_traces_its_child_result() -> None:
    result = trace("@NOT genre = Metal\n", {"genre": "Rock"})

    output = format_file_trace(result)
    assert result.passed is True
    assert "PASS NOT" in output
    assert "FAIL genre = Metal (line 1)" in output
    assert "tag genre = 'Rock'" in output


def test_missing_tags_and_not_equal() -> None:
    equal = trace("genre = Metal\n", {})
    not_equal = trace("genre != Metal\n", {})

    equal_output = format_file_trace(equal)
    assert equal.passed is False
    assert "missing tag genre" in equal_output
    assert format_tags_consulted(equal.consulted) == (
        "tags consulted:\n  genre (missing)"
    )

    assert not_equal.passed is True
    assert "missing tag genre" in format_file_trace(not_equal)


def test_calculated_rating_is_reported() -> None:
    result = trace("rating >= 4\n", {"fmps_rating": ["0.8"]})

    output = format_file_trace(result)
    assert result.passed is True
    assert "calculated rating = 4.0 (from fmps_rating)" in output
    assert "rating (calculated)" in format_tags_consulted(result.consulted)


def test_case_sensitivity_and_actual_key_casing() -> None:
    result = trace("@CASE artist = X\n", {"Artist": "X"})

    output = format_file_trace(result)
    assert result.passed is True
    assert "[case-sensitive]" in output
    assert "tag Artist = 'X'" in output
    assert "artist (key Artist)" in format_tags_consulted(result.consulted)


def test_multi_value_tags_show_the_list_value() -> None:
    result = trace("genre = Metal\n", {"genre": ["Rock", "Metal"]})

    output = format_file_trace(result)
    assert result.passed is True
    assert "tag genre = ['Rock', 'Metal']" in output


def test_consulted_tags_are_unique_and_in_first_use_order() -> None:
    result = trace(
        "artist = X\n@OR artist = Y\ngenre = Metal\n",
        {"artist": ["Y"], "genre": "Metal"},
    )

    assert result.passed is True
    assert [lookup.requested for lookup in result.consulted] == [
        "artist",
        "genre",
    ]


def test_nested_includes_are_traced(tmp_path: Path) -> None:
    deepest = tmp_path / "Deepest.m3ug"
    middle = tmp_path / "Middle.m3ug"
    main = tmp_path / "Main.m3ug"
    deepest.write_text("genre = Metal\n", encoding="utf-8")
    middle.write_text("@INCLUDE Deepest.m3ug\nrating >= 4\n", encoding="utf-8")
    main.write_text("@INCLUDE Middle.m3ug\nartist = X\n", encoding="utf-8")

    result = trace_file(
        parse_m3ug(main.read_text(), str(main)),
        {"genre": "Metal", "rating": 4, "artist": "X"},
    )
    output = format_file_trace(result, title=str(main))

    assert result.passed is True
    assert f"PASS @INCLUDE Middle.m3ug (Main.m3ug:1) -> {middle.resolve()}" in (output)
    assert f"PASS @INCLUDE Deepest.m3ug (Middle.m3ug:1) -> {deepest.resolve()}" in (
        output
    )
    assert "PASS genre = Metal (line 1)" in output
    assert "PASS rating >= 4 (line 2)" in output
    assert "PASS artist = X (line 2)" in output


def test_failed_include_short_circuits_later_children(tmp_path: Path) -> None:
    first = tmp_path / "First.m3ug"
    second = tmp_path / "Second.m3ug"
    main = tmp_path / "Main.m3ug"
    first.write_text("rating >= 4\n", encoding="utf-8")
    second.write_text("genre = Metal\n", encoding="utf-8")
    main.write_text(
        "@INCLUDE First.m3ug\n@INCLUDE Second.m3ug\nartist = X\n",
        encoding="utf-8",
    )

    result = trace_file(
        parse_m3ug(main.read_text(), str(main)),
        {"rating": 3, "genre": "Metal", "artist": "X"},
    )
    output = format_file_trace(result, title=str(main))

    assert result.passed is False
    assert f"FAIL @INCLUDE First.m3ug (Main.m3ug:1) -> {first.resolve()}" in (output)
    assert (
        f"SKIP @INCLUDE Second.m3ug (Main.m3ug:2) -> {second.resolve()} "
        "(short-circuited: include First.m3ug failed)" in output
    )
    assert "SKIP AND (short-circuited: include First.m3ug failed)" in output
    assert "tag artist" not in output


def test_directive_only_include_does_not_affect_passing(tmp_path: Path) -> None:
    base = tmp_path / "Base.m3ug"
    main = tmp_path / "Main.m3ug"
    base.write_text("@SORT artist\n@LIMIT 2\n", encoding="utf-8")
    main.write_text("@INCLUDE Base.m3ug\nartist = X\n", encoding="utf-8")

    result = trace_file(parse_m3ug(main.read_text(), str(main)), {"artist": "X"})
    output = format_file_trace(result, title=str(main))

    assert result.passed is True
    assert f"@INCLUDE Base.m3ug (Main.m3ug:1) -> {base.resolve()}" in output
    assert "(no rules; directives only)" in output
    assert "sort: artist" in output
    assert "limit: 2" in output


@pytest.mark.parametrize(
    ("content", "tags"),
    [
        ("", {}),
        ("artist = X\n", {"artist": "X"}),
        ("artist = X\n", {"artist": "Y"}),
        ("artist = X\nrating >= 4\n", {"artist": "X", "rating": 3}),
        ("genre = Metal\n@OR genre = Rock\n", {"genre": "Rock"}),
        ("@NOT genre = Metal\n", {}),
    ],
)
def test_file_trace_matches_the_expression_result(content: str, tags: Tags) -> None:
    parsed = parse_m3ug(content)
    result = trace_file(parsed, tags)

    assert result.passed == (parsed.expression is None or parsed.expression.apply(tags))


@pytest.mark.parametrize(
    ("name", "value", "tags"),
    [
        ("artist", "X", {"artist": "X"}),
        ("artist", "X", {"artist": "Y"}),
        ("genre", "Metal", {"genre": ["Rock", "Metal"]}),
        ("rating", "4", {"fmps_rating": ["0.8"]}),
        ("track", "7", {"track": ["7"]}),
        ("genre", "Metal", {}),
    ],
)
def test_rule_explanation_matches_rule_application(
    name: str, value: str, tags: Tags
) -> None:
    rule = parse_m3ug(f"{name} = {value}\n").rules[0]

    assert rule.explain(tags).passed == rule.apply(tags)


def test_trace_expression_short_circuits_without_lookups() -> None:
    parsed = parse_m3ug("artist = X\nrating >= 4\n")
    assert parsed.expression is not None
    result = trace_expression(parsed.expression, {"artist": "Y", "rating": 3})

    assert result.passed is False
    assert result.children[1].skipped is True
    assert result.children[1].rule is None
