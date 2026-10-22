import shutil
import sqlite3
import sys
from collections.abc import Callable
from pathlib import Path

import pytest

import genplis.executors as executors
from genplis.config import CollectionConfig, Config
from genplis.core import (
    Args,
    Mode,
    display_tag_stats,
    main,
    process_directory,
    resolve_args,
    setup_argparse,
)
from genplis.db import create_files_table, setup_database_connection
from genplis.exceptions import GenplisConfigError, GenplisError
from genplis.output import Palette, Theme
from genplis.stats import (
    TagStatsCollector,
    TagValueStat,
    full_tag_names,
    render_tag_details,
    render_tag_stats,
)
from genplis.types import Tags, Verbosity


def test_full_tag_names_includes_calculated_form() -> None:
    assert full_tag_names(("Genre", "rating", "*duration")) == frozenset(
        {"genre", "*genre", "rating", "*rating", "*duration"}
    )


def test_collector_counts_files_and_deduplicates_values_per_file() -> None:
    collector = TagStatsCollector(full_tags={"genre"})
    collector.record_file(
        {
            "artist": ["Artist A"],
            "genre": ["Rock", "Metal"],
            "filename": "/music/a.mp3",
        },
        {"*duration": 3.0},
    )
    collector.record_file(
        {
            "artist": ["Artist A", "Artist B"],
            "genre": ["Rock", "Rock"],
        },
        {"*duration": 4.0},
    )

    report = collector.report()
    embedded = {stat.name: stat for stat in report.embedded}
    calculated = {stat.name: stat for stat in report.calculated}

    assert report.files == 2
    assert report.files_with_embedded == 2
    assert "filename" not in embedded
    assert embedded["artist"].files == 2
    assert embedded["artist"].distinct == 2
    assert embedded["genre"].files == 2
    assert embedded["genre"].distinct == 2
    assert embedded["genre"].values == (
        TagValueStat("Rock", 2),
        TagValueStat("Metal", 1),
    )
    assert calculated["*duration"].files == 2
    assert calculated["*duration"].examples == ("3", "4")


def test_collector_caps_distinct_values() -> None:
    collector = TagStatsCollector(max_distinct=2)
    collector.record_file({"genre": ["A", "B", "C"]}, {})

    stat = collector.report().embedded[0]

    assert stat.name == "genre"
    assert stat.distinct == 2
    assert stat.capped is True
    assert stat.values == ()


def test_collector_does_not_cap_requested_tags() -> None:
    collector = TagStatsCollector(full_tags={"genre"}, max_distinct=2)
    collector.record_file({"genre": ["A", "B", "C"]}, {})

    stat = collector.report().embedded[0]

    assert stat.distinct == 3
    assert stat.capped is False
    assert tuple(value.value for value in stat.values) == ("A", "B", "C")


def test_collector_counts_files_without_tags() -> None:
    collector = TagStatsCollector()
    collector.record_file({}, {"*duration": 1.0})

    report = collector.report()

    assert report.files == 1
    assert report.files_with_embedded == 0
    assert report.embedded == ()


def test_render_summary_sections() -> None:
    collector = TagStatsCollector()
    collector.record_file(
        {"artist": ["A"], "genre": ["Rock"]},
        {"*duration": 3.0},
    )

    output = render_tag_stats(collector.report())

    assert "1 of 1 supported files have embedded tags" in output
    assert "Embedded tags" in output
    assert "Calculated tags" in output
    assert "artist" in output
    assert "*duration" in output
    assert "100.0%" in output


def test_render_details_lists_every_value() -> None:
    collector = TagStatsCollector(full_tags={"genre"})
    collector.record_file({"genre": ["Rock", "Metal"]}, {})
    collector.record_file({"genre": ["Rock"]}, {})

    output = render_tag_details(collector.report(), ("genre",))

    assert "Tag: genre (embedded)" in output
    assert "Files: 2 of 2 (100.0%)" in output
    assert "Distinct values: 2" in output
    assert "Rock" in output
    assert "Metal" in output
    assert "A file can contain more than one value" in output
    assert "Files without this tag: 0 (0.0%)" in output


def test_render_details_reports_missing_tag() -> None:
    collector = TagStatsCollector()
    collector.record_file({"artist": ["A"]}, {})

    output = render_tag_details(collector.report(), ("nope",))

    assert "Tag 'nope' was not found" in output
    assert "[tags] ignore" in output


def test_render_details_resolves_embedded_and_calculated_rating() -> None:
    collector = TagStatsCollector(full_tags=full_tag_names(("rating",)))
    collector.record_file({"rating": ["4"]}, {})
    collector.record_file({}, {"*rating": 5.0})

    report = collector.report()
    both = render_tag_details(report, ("rating",))
    requested_calculated = render_tag_details(report, ("*rating",))

    assert "Tag: rating (embedded)" in both
    assert "Tag: *rating (calculated)" in both
    assert "Tag: rating (embedded)" not in requested_calculated
    assert "Tag: *rating (calculated)" in requested_calculated


def test_render_details_escapes_control_characters() -> None:
    collector = TagStatsCollector(full_tags={"comment"})
    collector.record_file({"comment": ["line one\nline two"]}, {})

    output = render_tag_details(collector.report(), ("comment",))

    assert "line one\\nline two" in output


def test_render_details_uses_empty_marker() -> None:
    collector = TagStatsCollector(full_tags={"comment"})
    collector.record_file({"comment": [""]}, {})

    output = render_tag_details(collector.report(), ("comment",))

    assert "<empty>" in output


def test_render_summary_uses_palette() -> None:
    collector = TagStatsCollector()
    collector.record_file(
        {"artist": ["A"], "genre": ["Rock"]},
        {"*duration": 3.0},
    )
    palette = Palette(theme=Theme.DARK, enabled=True)

    output = render_tag_stats(collector.report(), palette=palette)

    assert "\x1b[1;38;5;255mEmbedded tags\x1b[0m" in output
    assert "\x1b[1;38;5;255mCalculated tags\x1b[0m" in output
    assert "\x1b[1;38;5;255mTag\x1b[0m" in output
    assert "\x1b[38;5;51martist\x1b[0m" in output
    assert "\x1b[38;5;220mRock\x1b[0m" in output
    assert "\x1b[38;5;220m100.0%\x1b[0m" in output
    assert "\x1b[38;5;244m----" in output


def test_render_details_uses_palette() -> None:
    collector = TagStatsCollector(full_tags={"genre"})
    collector.record_file({"genre": ["Rock", "Metal"]}, {})
    collector.record_file({"genre": ["Rock"]}, {})
    palette = Palette(theme=Theme.DARK, enabled=True)

    output = render_tag_details(collector.report(), ("genre",), palette=palette)

    assert "Tag: \x1b[38;5;51mgenre\x1b[0m \x1b[38;5;244m(embedded)\x1b[0m" in output
    assert "\x1b[38;5;220mRock\x1b[0m" in output
    assert "\x1b[38;5;220m100.0%\x1b[0m" in output
    assert "\x1b[38;5;244mA file can contain more than one value" in output


def test_stats_light_theme_uses_light_codes() -> None:
    collector = TagStatsCollector(full_tags={"genre"})
    collector.record_file({"genre": ["Rock"]}, {})
    palette = Palette(theme=Theme.LIGHT, enabled=True)

    output = render_tag_details(collector.report(), ("genre",), palette=palette)

    assert "\x1b[38;5;30mgenre\x1b[0m" in output
    assert "\x1b[38;5;90mRock\x1b[0m" in output


def test_colored_stats_preserve_plain_layout(
    strip_ansi: Callable[[str], str],
) -> None:
    collector = TagStatsCollector(full_tags={"genre"})
    collector.record_file(
        {"artist": ["Artist"], "genre": ["Rock"]},
        {"*duration": 3.0},
    )
    collector.record_file(
        {"artist": ["Artist"], "genre": ["Metal"]},
        {"*duration": 4.0},
    )
    report = collector.report()
    palette = Palette(theme=Theme.DARK, enabled=True)

    assert strip_ansi(render_tag_stats(report, palette=palette)) == render_tag_stats(
        report
    )
    assert strip_ansi(
        render_tag_details(report, ("genre",), palette=palette)
    ) == render_tag_details(report, ("genre",))


def test_resolve_args_tag_stats() -> None:
    args = resolve_args(
        setup_argparse().parse_args(["--tag-stats", "/music"]),
        Config(),
    )

    assert args.mode is Mode.TAG_STATS
    assert args.tags == ()


def test_resolve_args_tag_implies_tag_stats_and_deduplicates() -> None:
    args = resolve_args(
        setup_argparse().parse_args(["-t", "Genre", "--tag", "genre", "/music"]),
        Config(),
    )

    assert args.mode is Mode.TAG_STATS
    assert args.tags == ("genre",)


def test_resolve_args_rejects_empty_tag() -> None:
    with pytest.raises(GenplisConfigError, match="tag name must not be empty"):
        resolve_args(
            setup_argparse().parse_args(["-t", " ", "/music"]),
            Config(),
        )


def test_resolve_args_rejects_tag_with_clean() -> None:
    with pytest.raises(GenplisConfigError, match="cannot be combined"):
        resolve_args(
            setup_argparse().parse_args(["--clean", "-t", "genre"]),
            Config(),
        )


def test_tag_stats_and_clean_are_mutually_exclusive() -> None:
    with pytest.raises(SystemExit) as exc_info:
        setup_argparse().parse_args(["--clean", "--tag-stats", "/music"])

    assert exc_info.value.code == 2


def test_main_rejects_tag_with_clean(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys, "argv", ["genplis", "--clean", "-t", "genre"])

    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == 2


def test_main_tag_stats_writes_no_playlist(
    file_mp3: Path,
    file_m3ug: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    music = tmp_path / "music"
    music.mkdir()
    shutil.copy2(file_mp3, music / "song.mp3")
    shutil.copy2(file_m3ug, music / "favorites.m3ug")
    db_path = tmp_path / "cache.db"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "genplis",
            "--tag-stats",
            "--no-config",
            "--db",
            str(db_path),
            str(music),
        ],
    )

    main()

    output = capsys.readouterr().out
    assert f"Tag statistics for {music}" in output
    assert "Embedded tags" in output
    assert not (music / "favorites.m3u").exists()


def test_main_tag_stats_uses_color_flags(
    file_mp3: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    music = tmp_path / "music"
    music.mkdir()
    shutil.copy2(file_mp3, music / "song.mp3")
    db_path = tmp_path / "cache.db"
    argv = [
        "genplis",
        "--tag-stats",
        "--theme",
        "dark",
        "--no-config",
        "--db",
        str(db_path),
        str(music),
    ]
    monkeypatch.setattr(sys, "argv", [*argv, "--color"])

    main()

    output = capsys.readouterr().out
    assert f"\x1b[1;38;5;255m{music}\x1b[0m" in output
    assert "\x1b[1;38;5;255mEmbedded tags\x1b[0m" in output
    assert "\x1b[38;5;51martist\x1b[0m" in output

    monkeypatch.setattr(sys, "argv", [*argv, "--no-color"])
    main()

    assert "\x1b[" not in capsys.readouterr().out


def test_main_tag_single_file_uses_color(
    file_mp3: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    db_path = tmp_path / "cache.db"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "genplis",
            "-t",
            "artist",
            "--color",
            "--theme",
            "dark",
            "--no-config",
            "--db",
            str(db_path),
            str(file_mp3),
        ],
    )

    main()

    output = capsys.readouterr().out
    assert "\x1b[38;5;51martist\x1b[0m" in output
    assert "\x1b[1;38;5;255mParsed tags:\x1b[0m" in output


def test_display_tag_stats_uses_configured_path(
    genplis_db: sqlite3.Connection,
    file_mp3: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    music = tmp_path / "music"
    music.mkdir()
    shutil.copy2(file_mp3, music / "song.mp3")
    config = Config(collection=CollectionConfig(path=music))
    args = resolve_args(setup_argparse().parse_args(["-t", "genre"]), config)

    display_tag_stats(genplis_db, genplis_db.cursor(), args)

    output = capsys.readouterr().out
    assert f"Tag statistics for {music}" in output
    assert "Tag: genre (embedded)" in output


def test_display_tag_stats_skips_m3ug_and_writes_no_playlist(
    genplis_db: sqlite3.Connection,
    make_args: Callable[..., Args],
    file_mp3: Path,
    file_m3ug: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    shutil.copy2(file_mp3, tmp_path / "song.mp3")
    shutil.copy2(file_m3ug, tmp_path / "favorites.m3ug")
    args = make_args(str(tmp_path))

    display_tag_stats(genplis_db, genplis_db.cursor(), args)

    output = capsys.readouterr().out
    assert f"Tag statistics for {tmp_path}" in output
    assert "artist" in output
    assert "*duration" in output
    assert not (tmp_path / "favorites.m3u").exists()


def test_display_tag_stats_filters_to_requested_tag(
    genplis_db: sqlite3.Connection,
    make_args: Callable[..., Args],
    file_mp3: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    shutil.copy2(file_mp3, tmp_path / "song.mp3")
    args = make_args(str(tmp_path), tags=("genre",))

    display_tag_stats(genplis_db, genplis_db.cursor(), args)

    output = capsys.readouterr().out
    assert "Tag: genre (embedded)" in output
    assert "Synthwave; Retrowave; Electronic" in output
    assert "Embedded tags" not in output


def test_display_tag_stats_reuses_cache(
    genplis_db: sqlite3.Connection,
    make_args: Callable[..., Args],
    file_mp3: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    music = tmp_path / "music"
    music.mkdir()
    shutil.copy2(file_mp3, music / "song.mp3")
    args = make_args(str(music), tags=("genre",))
    display_tag_stats(genplis_db, genplis_db.cursor(), args)
    capsys.readouterr()

    def fail_get_tags(*_args: object, **_kwargs: object) -> Tags:
        raise AssertionError("cached files must not be parsed again")

    monkeypatch.setattr("genplis.core.get_tags", fail_get_tags)
    display_tag_stats(genplis_db, genplis_db.cursor(), args)

    output = capsys.readouterr().out
    assert "Tag: genre (embedded)" in output
    assert "Updated cache" not in output


def test_display_tag_stats_single_file(
    genplis_db: sqlite3.Connection,
    make_args: Callable[..., Args],
    file_mp3: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    display_tag_stats(
        genplis_db,
        genplis_db.cursor(),
        make_args(str(file_mp3)),
    )

    output = capsys.readouterr().out
    assert f"{file_mp3} detected as music file" in output
    assert "Parsed tags:" in output
    assert "artist" in output


def test_display_tag_stats_single_file_filters_requested_tag(
    genplis_db: sqlite3.Connection,
    make_args: Callable[..., Args],
    file_mp3: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    display_tag_stats(
        genplis_db,
        genplis_db.cursor(),
        make_args(str(file_mp3), tags=("duration",)),
    )

    output = capsys.readouterr().out
    assert "*duration" in output
    assert "artist" not in output


def test_display_tag_stats_rejects_m3ug_path(
    genplis_db: sqlite3.Connection,
    make_args: Callable[..., Args],
    file_m3ug: Path,
) -> None:
    with pytest.raises(GenplisError, match="not a .m3ug filter"):
        display_tag_stats(
            genplis_db,
            genplis_db.cursor(),
            make_args(str(file_m3ug)),
        )


def test_display_tag_stats_rejects_missing_path(
    genplis_db: sqlite3.Connection,
    make_args: Callable[..., Args],
    tmp_path: Path,
) -> None:
    missing = tmp_path / "missing.mp3"

    with pytest.raises(GenplisError, match="must be either a directory or a file"):
        display_tag_stats(
            genplis_db,
            genplis_db.cursor(),
            make_args(str(missing)),
        )


def test_display_tag_stats_quiet_modes(
    genplis_db: sqlite3.Connection,
    make_args: Callable[..., Args],
    file_mp3: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    shutil.copy2(file_mp3, tmp_path / "song.mp3")

    display_tag_stats(
        genplis_db,
        genplis_db.cursor(),
        make_args(str(tmp_path), verbosity=Verbosity.QUIET),
    )
    quiet_output = capsys.readouterr().out
    assert "Embedded tags" in quiet_output
    assert "Processed 1 files" not in quiet_output

    display_tag_stats(
        genplis_db,
        genplis_db.cursor(),
        make_args(str(tmp_path), verbosity=Verbosity.REALLY_QUIET),
    )
    assert capsys.readouterr().out == ""


def test_display_tag_stats_parallel_matches_sequential(
    make_args: Callable[..., Args],
    file_mp3: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "music"
    root.mkdir()
    for index in range(4):
        shutil.copy2(file_mp3, root / f"song-{index}.mp3")
    monkeypatch.setattr(executors, "MIN_PARALLEL_FILES", 4)

    reports = []
    for jobs in (1, 2):
        db_path = tmp_path / f"stats-{jobs}.db"
        conn, cursor = _open_db(db_path)
        try:
            collector = TagStatsCollector()
            process_directory(
                conn,
                cursor,
                root,
                make_args(str(root), db_path=db_path, jobs=jobs),
                filters={},
                stats=collector,
            )
            reports.append(collector.report())
        finally:
            conn.close()

    assert reports[0] == reports[1]


def _open_db(path: Path) -> tuple[sqlite3.Connection, sqlite3.Cursor]:
    conn, cursor = setup_database_connection(path)
    create_files_table(cursor)
    return conn, cursor
