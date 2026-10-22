from pathlib import Path

import pytest

from genplis.diagnostics import format_filter_tree
from genplis.m3ug import parse_m3ug
from genplis.sorting import parse_sort_spec


def render(content: str, *, title: str | None = None) -> str:
    return format_filter_tree(parse_m3ug(content), title=title)


def test_renders_simple_and_tree() -> None:
    output = render("artist = X\nrating >= 4\n", title="Favorites.m3ug")

    assert output.splitlines() == [
        "Favorites.m3ug",
        "  AND",
        "    artist = X (line 1)",
        "    rating >= 4 (line 2)",
    ]


def test_renders_or_and_not_nodes() -> None:
    output = render(
        "genre = Metal\n@OR genre = Rock\n@NOT rating >= 4\n",
        title="Favorites.m3ug",
    )

    assert "  AND" in output
    assert "    OR" in output
    assert "      genre = Metal (line 1)" in output
    assert "      genre = Rock (line 2)" in output
    assert "    NOT" in output
    assert "      rating >= 4 (line 3)" in output


def test_renders_expanded_sets_with_one_source_line() -> None:
    output = render("[genre | style] = [Metal | Rock]\n")

    assert output.splitlines() == [
        "OR",
        "  genre = Metal (line 1)",
        "  genre = Rock (line 1)",
        "  style = Metal (line 1)",
        "  style = Rock (line 1)",
    ]


def test_renders_case_sensitive_rules() -> None:
    output = render('@CASE artist = "DANCE WITH THE DEAD"\n')

    assert 'artist = "DANCE WITH THE DEAD" (line 1) [case-sensitive]' in output


def test_renders_literals_and_duration() -> None:
    output = render('rating = "4"\nquoted = "true"\nflag = true\nduration >= 10m\n')

    assert 'rating = "4" (line 1)' in output
    assert 'quoted = "true" (line 2)' in output
    assert "flag = true (line 3)" in output
    assert "duration >= 10m (600s) (line 4)" in output


def test_renders_nested_includes_inline(tmp_path: Path) -> None:
    deepest = tmp_path / "Deepest.m3ug"
    middle = tmp_path / "Middle.m3ug"
    main = tmp_path / "Main.m3ug"
    deepest.write_text("genre = Metal\n", encoding="utf-8")
    middle.write_text('@INCLUDE "Deepest.m3ug"\nrating >= 4\n', encoding="utf-8")
    main.write_text("@INCLUDE Middle.m3ug\nartist = X\n", encoding="utf-8")

    output = format_filter_tree(
        parse_m3ug(main.read_text(), str(main)), title=str(main)
    )

    assert f"  @INCLUDE Middle.m3ug (Main.m3ug:1) -> {middle.resolve()}" in output
    assert (
        f'    @INCLUDE "Deepest.m3ug" (Middle.m3ug:1) -> {deepest.resolve()}' in output
    )
    assert "      genre = Metal (line 1)" in output
    assert "      rating >= 4 (line 2)" in output
    assert "    rating >= 4 (line 2)" in output
    assert "  artist = X (line 2)" in output
    assert output.index("@INCLUDE Middle.m3ug") < output.index("artist = X")


def test_renders_directives_in_order() -> None:
    output = render(
        "@SORT artist\n"
        "@LIMIT 2\n"
        "@LIMIT 1 PER album\n"
        "@DEDUPE title, album\n"
        "@MAX-DURATION 10m\n"
        "@NO-PLAYLIST\n"
        "artist = X\n",
        title="Favorites.m3ug",
    )

    lines = output.splitlines()
    start = lines.index("  directives:")
    assert lines[start + 1 :] == [
        "    sort: artist",
        "    limit: 2",
        "    per-tag limit: 1 per album",
        "    dedupe: title, album",
        "    max duration: 600s",
        "    no playlist: yes (@NO-PLAYLIST)",
    ]


def test_renders_disabled_directives_clearly() -> None:
    output = render(
        "@SORT\n@LIMIT 0\n@LIMIT 0 PER artist\n@DEDUPE\n@MAX-DURATION 0\n",
        title="Favorites.m3ug",
    )

    assert "    sort: walk order" in output
    assert "    limit: 0 (disabled)" in output
    assert "    per-tag limit: 0 per artist (disabled)" in output
    assert "    dedupe: (disabled)" in output
    assert "    max duration: 0s (disabled)" in output


def test_renders_directive_only_include(tmp_path: Path) -> None:
    base = tmp_path / "Base.m3ug"
    main = tmp_path / "Main.m3ug"
    base.write_text("@SORT artist\n@LIMIT 2\n", encoding="utf-8")
    main.write_text("@INCLUDE Base.m3ug\ngenre = Metal\n", encoding="utf-8")

    output = format_filter_tree(
        parse_m3ug(main.read_text(), str(main)), title=str(main)
    )

    assert f"  @INCLUDE Base.m3ug (Main.m3ug:1) -> {base.resolve()}" in output
    assert "    (no rules; directives only)" in output
    assert "      sort: artist" in output
    assert "      limit: 2" in output
    assert "  genre = Metal (line 2)" in output
    assert "AND" not in output
    assert output.index("@INCLUDE Base.m3ug") < output.index("genre = Metal")


def test_renders_effective_default_sort() -> None:
    parsed = parse_m3ug("artist = X\n")

    output = format_filter_tree(
        parsed,
        title="Favorites.m3ug",
        default_sort=parse_sort_spec("artist, album desc"),
    )

    assert "    sort: artist, album desc (default)" in output


def test_renders_no_playlist_and_empty_filter() -> None:
    no_playlist = parse_m3ug("@NO-PLAYLIST\n")
    output = format_filter_tree(no_playlist, title="Fragment.m3ug")

    assert output.splitlines()[0] == "Fragment.m3ug"
    assert "  (always)" in output
    assert "    no playlist: yes (@NO-PLAYLIST)" in output

    assert format_filter_tree(parse_m3ug("")) == "(always)"


def test_renderer_does_not_open_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    main = tmp_path / "Main.m3ug"
    main.write_text("artist = X\n", encoding="utf-8")
    parsed = parse_m3ug(main.read_text(), str(main))

    def fail(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("rendering must not read files")

    monkeypatch.setattr(Path, "read_text", fail)
    assert "artist = X" in format_filter_tree(parsed)
