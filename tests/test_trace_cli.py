import re
import shutil
import sqlite3
import sys
from collections.abc import Callable
from pathlib import Path

import pytest

from genplis.config import CollectionConfig, Config
from genplis.core import (
    Args,
    Mode,
    main,
    resolve_args,
    setup_argparse,
    trace_path,
)
from genplis.exceptions import GenplisConfigError, GenplisError
from genplis.types import Verbosity


def _args(
    make_args: Callable[..., Args],
    path: Path,
    target: Path,
    *,
    filters: tuple[Path, ...] = (),
    **kwargs: object,
) -> Args:
    return make_args(
        str(path),
        mode=Mode.TRACE,
        trace_path=target,
        filters=filters,
        **kwargs,
    )


def test_trace_matching_filter(
    genplis_db: sqlite3.Connection,
    make_args: Callable[..., Args],
    file_mp3: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    song = tmp_path / "song.mp3"
    shutil.copy2(file_mp3, song)
    filter_file = tmp_path / "favorites.m3ug"
    filter_file.write_text('artist = "Test Artist"\n', encoding="utf-8")

    trace_path(
        genplis_db,
        genplis_db.cursor(),
        _args(make_args, tmp_path, song, filters=(filter_file,)),
    )

    output = capsys.readouterr().out
    assert f"Trace target: {song}" in output
    assert "Cache status: not present" in output
    assert "Filters: 1" in output
    assert f"Filter: {filter_file}" in output
    assert "tags consulted:" in output
    assert "  artist" in output
    assert "PASS artist" in output
    assert "MATCH" in output
    assert not filter_file.with_suffix(".m3u").exists()


def test_trace_failing_filter(
    genplis_db: sqlite3.Connection,
    make_args: Callable[..., Args],
    file_mp3: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    song = tmp_path / "song.mp3"
    shutil.copy2(file_mp3, song)
    filter_file = tmp_path / "favorites.m3ug"
    filter_file.write_text('artist = "Nobody"\n', encoding="utf-8")

    trace_path(
        genplis_db,
        genplis_db.cursor(),
        _args(make_args, tmp_path, song, filters=(filter_file,)),
    )

    output = capsys.readouterr().out
    assert "FAIL artist" in output
    assert "NO MATCH" in output


def test_trace_or_short_circuit(
    genplis_db: sqlite3.Connection,
    make_args: Callable[..., Args],
    file_mp3: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    song = tmp_path / "song.mp3"
    shutil.copy2(file_mp3, song)
    filter_file = tmp_path / "favorites.m3ug"
    filter_file.write_text(
        'artist = "Test Artist"\n@OR artist = "Nobody"\n',
        encoding="utf-8",
    )

    trace_path(
        genplis_db,
        genplis_db.cursor(),
        _args(make_args, tmp_path, song, filters=(filter_file,)),
    )

    output = capsys.readouterr().out
    assert "PASS artist" in output
    assert 'SKIP artist = "Nobody"' in output
    assert "an earlier OR child passed" in output


def test_trace_included_rules(
    genplis_db: sqlite3.Connection,
    make_args: Callable[..., Args],
    file_mp3: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    song = tmp_path / "song.mp3"
    shutil.copy2(file_mp3, song)
    base = tmp_path / "Base.m3ug"
    main_filter = tmp_path / "Main.m3ug"
    base.write_text('artist = "Test Artist"\n', encoding="utf-8")
    main_filter.write_text("@INCLUDE Base.m3ug\ngenre ~ Synthwave\n", encoding="utf-8")

    trace_path(
        genplis_db,
        genplis_db.cursor(),
        _args(make_args, tmp_path, song, filters=(main_filter,)),
    )

    output = capsys.readouterr().out
    assert f"@INCLUDE Base.m3ug (Main.m3ug:1) -> {base.resolve()}" in output
    assert "PASS artist" in output
    assert "MATCH" in output


def test_trace_multiple_filters_prints_summary(
    genplis_db: sqlite3.Connection,
    make_args: Callable[..., Args],
    file_mp3: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    song = tmp_path / "song.mp3"
    shutil.copy2(file_mp3, song)
    matching = tmp_path / "matching.m3ug"
    failing = tmp_path / "failing.m3ug"
    matching.write_text('artist = "Test Artist"\n', encoding="utf-8")
    failing.write_text('artist = "Nobody"\n', encoding="utf-8")

    trace_path(
        genplis_db,
        genplis_db.cursor(),
        _args(make_args, tmp_path, song),
    )

    output = capsys.readouterr().out
    assert "Filters: 2" in output
    assert "Summary:" in output
    assert f"  MATCH {matching}" in output
    assert f"  NO MATCH {failing}" in output


def test_trace_rejects_missing_target(
    genplis_db: sqlite3.Connection,
    make_args: Callable[..., Args],
    tmp_path: Path,
) -> None:
    missing = tmp_path / "missing.mp3"
    with pytest.raises(GenplisError, match="does not exist"):
        trace_path(
            genplis_db,
            genplis_db.cursor(),
            _args(make_args, tmp_path, missing),
        )


def test_trace_rejects_directory_and_m3ug_targets(
    genplis_db: sqlite3.Connection,
    make_args: Callable[..., Args],
    file_m3ug: Path,
    tmp_path: Path,
) -> None:
    with pytest.raises(GenplisError, match="is a directory"):
        trace_path(
            genplis_db,
            genplis_db.cursor(),
            _args(make_args, tmp_path, tmp_path),
        )
    with pytest.raises(GenplisError, match="not audio"):
        trace_path(
            genplis_db,
            genplis_db.cursor(),
            _args(make_args, tmp_path, file_m3ug),
        )


def test_trace_rejects_unsupported_target(
    genplis_db: sqlite3.Connection,
    make_args: Callable[..., Args],
    tmp_path: Path,
) -> None:
    target = tmp_path / "notes.txt"
    target.write_text("not music\n", encoding="utf-8")

    with pytest.raises(GenplisError, match="not a supported music file"):
        trace_path(
            genplis_db,
            genplis_db.cursor(),
            _args(make_args, tmp_path, target),
        )


def test_trace_warns_for_excluded_target(
    genplis_db: sqlite3.Connection,
    make_args: Callable[..., Args],
    file_mp3: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    song = tmp_path / "song.mp3"
    shutil.copy2(file_mp3, song)
    filter_file = tmp_path / "favorites.m3ug"
    filter_file.write_text('artist = "Test Artist"\n', encoding="utf-8")

    trace_path(
        genplis_db,
        genplis_db.cursor(),
        _args(
            make_args,
            tmp_path,
            song,
            filters=(filter_file,),
            exclude=[re.compile(r"song\.mp3$")],
        ),
    )

    output = capsys.readouterr().out
    assert "WARNING: This file is excluded by current configuration." in output
    assert "MATCH" in output


def test_trace_reports_no_filters(
    genplis_db: sqlite3.Connection,
    make_args: Callable[..., Args],
    file_mp3: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    song = tmp_path / "song.mp3"
    shutil.copy2(file_mp3, song)

    trace_path(
        genplis_db,
        genplis_db.cursor(),
        _args(make_args, tmp_path, song),
    )

    assert f"No filters found in {tmp_path}" in capsys.readouterr().out


def test_trace_warns_when_target_is_outside_scan_root(
    genplis_db: sqlite3.Connection,
    make_args: Callable[..., Args],
    file_mp3: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    music = tmp_path / "music"
    music.mkdir()
    song = tmp_path / "outside.mp3"
    shutil.copy2(file_mp3, song)
    filter_file = music / "favorites.m3ug"
    filter_file.write_text('artist = "Test Artist"\n', encoding="utf-8")

    trace_path(
        genplis_db,
        genplis_db.cursor(),
        _args(make_args, music, song),
    )

    output = capsys.readouterr().out
    assert f"WARNING: {song} is outside the scan root {music}." in output
    assert "MATCH" in output


def test_trace_uses_config_path() -> None:
    config = Config(collection=CollectionConfig(path=Path("/music")))

    args = resolve_args(
        setup_argparse().parse_args(["--trace", "/music/song.mp3"]),
        config,
    )

    assert args.mode is Mode.TRACE
    assert args.path == Path("/music")
    assert args.trace_path == Path("/music/song.mp3")


def test_trace_quiet_modes(
    genplis_db: sqlite3.Connection,
    make_args: Callable[..., Args],
    file_mp3: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    song = tmp_path / "song.mp3"
    shutil.copy2(file_mp3, song)
    filter_file = tmp_path / "favorites.m3ug"
    filter_file.write_text('artist = "Test Artist"\n', encoding="utf-8")

    trace_path(
        genplis_db,
        genplis_db.cursor(),
        _args(
            make_args,
            tmp_path,
            song,
            filters=(filter_file,),
            verbosity=Verbosity.QUIET,
        ),
    )
    assert "MATCH" in capsys.readouterr().out

    trace_path(
        genplis_db,
        genplis_db.cursor(),
        _args(
            make_args,
            tmp_path,
            song,
            filters=(filter_file,),
            verbosity=Verbosity.REALLY_QUIET,
        ),
    )
    assert capsys.readouterr().out == ""


def test_trace_mode_conflicts(tmp_path: Path) -> None:
    parser = setup_argparse()
    for conflicting in ("--tag-stats", "--show-rules", "--clean"):
        with pytest.raises(SystemExit) as exc_info:
            parser.parse_args(["--trace", "song.mp3", conflicting, str(tmp_path)])
        assert exc_info.value.code == 2

    with pytest.raises(GenplisConfigError, match="cannot be combined"):
        resolve_args(
            parser.parse_args(["--trace", "song.mp3", "-t", "genre", str(tmp_path)]),
            Config(),
        )


def test_main_trace_writes_no_playlist(
    file_mp3: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    song = tmp_path / "song.mp3"
    shutil.copy2(file_mp3, song)
    filter_file = tmp_path / "favorites.m3ug"
    filter_file.write_text('artist = "Test Artist"\n', encoding="utf-8")
    db_path = tmp_path / "genplis.db"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "genplis",
            "--trace",
            str(song),
            "--no-config",
            "--db",
            str(db_path),
            "--filter",
            str(filter_file),
            str(tmp_path),
        ],
    )

    main()

    output = capsys.readouterr().out
    assert "MATCH" in output
    assert not filter_file.with_suffix(".m3u").exists()
