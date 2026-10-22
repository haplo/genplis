from collections.abc import Callable
from pathlib import Path

from genplis.config import Config, OutputConfig
from genplis.core import Args, build_playlist_input
from genplis.diagnostics import PlaylistInput, format_playlist_input
from genplis.m3ug import LimitPerTag, parse_m3ug
from genplis.sorting import SortSpec, SortValue, SortValues, parse_sort_spec
from genplis.types import Tags


def _input(
    *,
    sort: SortSpec | None = None,
    sort_values: SortValues = ("A",),
    sort_is_default: bool = False,
    dedupe: tuple[str, ...] | None = None,
    dedupe_values: SortValues = (),
    limit: int | None = None,
    limit_per: LimitPerTag | None = None,
    limit_key: SortValue | None = None,
    max_duration: float | None = None,
    duration: float | None = None,
    no_playlist: bool = False,
    exclusion: str | None = None,
) -> PlaylistInput:
    return PlaylistInput(
        filter_file=Path("Favorites.m3ug"),
        sort=parse_sort_spec("artist") if sort is None else sort,
        sort_values=sort_values,
        sort_is_default=sort_is_default,
        dedupe=dedupe,
        dedupe_values=dedupe_values,
        limit=limit,
        limit_per=limit_per,
        limit_key=limit_key,
        max_duration=max_duration,
        duration=duration,
        no_playlist=no_playlist,
        exclusion=exclusion,
    )


def test_default_sort_marks_missing_values_as_sorting_last() -> None:
    output = format_playlist_input(
        _input(
            sort=parse_sort_spec("artist, album"),
            sort_values=("A", None),
            sort_is_default=True,
        )
    )

    assert "  sort: artist, album (default)" in output
    assert "    artist = 'A'" in output
    assert "    album = <missing> (sorts last)" in output
    assert "  selection: not simulated; use --trace-full" in output


def test_empty_and_random_sorts() -> None:
    walk = format_playlist_input(_input(sort=(), sort_values=()))
    assert "  sort: walk order" in walk

    random = format_playlist_input(
        _input(
            sort=parse_sort_spec("artist, random 7"),
            sort_values=("A",),
        )
    )
    assert "  sort: artist, random 7" in random
    assert "    random: seed 7" in random

    unseeded = format_playlist_input(
        _input(sort=parse_sort_spec("random"), sort_values=())
    )
    assert "    random: unseeded" in unseeded


def test_dedupe_values_mark_missing_keys_as_kept() -> None:
    output = format_playlist_input(
        _input(
            dedupe=("title", "album"),
            dedupe_values=("Same", None),
        )
    )

    assert "  dedupe: title, album" in output
    assert "    title = 'Same'" in output
    assert "    album = <missing> (kept)" in output

    disabled = format_playlist_input(_input(dedupe=(), dedupe_values=()))
    assert "  dedupe: (disabled)" in disabled


def test_limit_and_per_tag_limit() -> None:
    output = format_playlist_input(
        _input(
            limit=10,
            limit_per=LimitPerTag(2, "artist"),
            limit_key="A",
        )
    )

    assert "  limit: 10" in output
    assert "  per-tag limit: 2 per artist" in output
    assert "    artist = 'A'" in output

    disabled = format_playlist_input(
        _input(
            limit=0,
            limit_per=LimitPerTag(0, "artist"),
        )
    )
    assert "  limit: 0 (disabled)" in disabled
    assert "  per-tag limit: 0 per artist (disabled)" in disabled


def test_missing_per_tag_key_is_a_deterministic_exclusion() -> None:
    output = format_playlist_input(
        _input(
            limit_per=LimitPerTag(2, "artist"),
            limit_key=None,
            exclusion=("per-tag limit key 'artist' is missing; file would be skipped"),
        )
    )

    assert "    artist = <missing> (file would be skipped)" in output
    assert (
        "  selection: excluded: per-tag limit key 'artist' is missing; "
        "file would be skipped" in output
    )


def test_max_duration_and_missing_duration() -> None:
    output = format_playlist_input(_input(max_duration=600, duration=None))

    assert "  max duration: 600s" in output
    assert "    target duration: 0s (missing)" in output

    present = format_playlist_input(_input(max_duration=600, duration=3.239))
    assert "    target duration: 3.239s" in present

    disabled = format_playlist_input(_input(max_duration=0, duration=10))
    assert "  max duration: 0s (disabled)" in disabled
    assert "    target duration: 10s" in disabled


def test_no_playlist_is_a_deterministic_result() -> None:
    output = format_playlist_input(_input(no_playlist=True))

    assert "  no playlist: yes (@NO-PLAYLIST)" in output
    assert "  selection: no playlist (@NO-PLAYLIST)" in output


def test_builds_inputs_from_filter_and_tags(
    make_args: Callable[..., Args],
) -> None:
    parsed = parse_m3ug(
        "@SORT title\n@DEDUPE album\n@LIMIT 10\n"
        "@LIMIT 2 PER artist\n@MAX-DURATION 10m\nartist = X\n"
    )
    target = Path("song.mp3")
    args = make_args(".")
    tags: Tags = {
        "artist": ["A"],
        "title": ["T"],
        "album": ["B"],
        "duration": 3.2,
    }

    result = build_playlist_input(Path("Favorites.m3ug"), parsed, target, tags, args)

    assert result.sort == parse_sort_spec("title")
    assert result.sort_values == ("t",)
    assert result.sort_is_default is False
    assert result.dedupe == ("album",)
    assert result.dedupe_values == ("b",)
    assert result.limit == 10
    assert result.limit_per == LimitPerTag(2, "artist")
    assert result.limit_key == "a"
    assert result.max_duration == 600
    assert result.duration == 3.2
    assert result.exclusion is None


def test_builds_default_sort_from_config(
    make_args: Callable[..., Args],
) -> None:
    config = Config(output=OutputConfig(sort=parse_sort_spec("album desc")))
    parsed = parse_m3ug("artist = X\n")
    args = make_args(".", config=config)

    result = build_playlist_input(
        Path("Favorites.m3ug"),
        parsed,
        Path("song.mp3"),
        {"artist": ["A"], "album": ["B"]},
        args,
    )

    assert result.sort == parse_sort_spec("album desc")
    assert result.sort_is_default is True
    assert result.sort_values == ("b",)


def test_builds_missing_per_tag_exclusion(
    make_args: Callable[..., Args],
) -> None:
    parsed = parse_m3ug("@LIMIT 1 PER artist\n")
    result = build_playlist_input(
        Path("Favorites.m3ug"),
        parsed,
        Path("song.mp3"),
        {"title": ["T"]},
        make_args("."),
    )

    assert result.limit_key is None
    assert result.exclusion is not None
    assert "file would be skipped" in result.exclusion
