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
    trace_full_path,
    trace_path,
)
from genplis.exceptions import GenplisConfigError
from genplis.types import Tags


def _run_full(
    genplis_db: sqlite3.Connection,
    make_args: Callable[..., Args],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    tracks: dict[str, Tags],
    content: str,
    target_name: str,
    *,
    filter_path: Path | None = None,
    **kwargs: object,
) -> Path:
    for name in tracks:
        (tmp_path / name).write_bytes(b"")
    filter_file = filter_path or (tmp_path / "favorites.m3ug")
    if filter_path is not None:
        filter_file.mkdir(parents=True, exist_ok=True)
        filter_file = filter_file / "favorites.m3ug"
    filter_file.write_text(content, encoding="utf-8")

    def fake_get_tags(path: Path, *_args: object, **_kwargs: object) -> Tags | None:
        return tracks.get(path.name)

    monkeypatch.setattr("genplis.core.get_tags", fake_get_tags)
    trace_full_path(
        genplis_db,
        genplis_db.cursor(),
        make_args(
            str(filter_path or tmp_path),
            mode=Mode.TRACE_FULL,
            trace_path=tmp_path / target_name,
            include_source=False,
            extended_m3u=False,
            **kwargs,
        ),
    )
    return filter_file


def test_trace_full_selected(
    genplis_db: sqlite3.Connection,
    make_args: Callable[..., Args],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    tracks: dict[str, Tags] = {
        "a.mp3": {"artist": ["A"], "title": ["A"]},
        "b.mp3": {"artist": ["A"], "title": ["B"]},
    }

    filter_file = _run_full(
        genplis_db,
        make_args,
        tmp_path,
        monkeypatch,
        tracks,
        "@SORT title\nartist = A\n",
        "b.mp3",
    )

    output = capsys.readouterr().out
    assert "selection:" in output
    assert "sorted position: 2 of 2" in output
    assert "result: IN PLAYLIST at position 2" in output
    assert not filter_file.with_suffix(".m3u").exists()
    assert genplis_db.execute("SELECT count(*) FROM files").fetchone() == (2,)


def test_trace_full_count_limit_cut(
    genplis_db: sqlite3.Connection,
    make_args: Callable[..., Args],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    tracks: dict[str, Tags] = {
        "a.mp3": {"artist": ["A"], "title": ["A"]},
        "b.mp3": {"artist": ["A"], "title": ["B"]},
        "c.mp3": {"artist": ["A"], "title": ["C"]},
    }

    _run_full(
        genplis_db,
        make_args,
        tmp_path,
        monkeypatch,
        tracks,
        "@SORT title\n@LIMIT 2\nartist = A\n",
        "c.mp3",
    )

    output = capsys.readouterr().out
    assert "excluded: count cap 2 reached" in output
    assert "result: NOT IN PLAYLIST" in output


def test_trace_full_per_tag_limit_cut(
    genplis_db: sqlite3.Connection,
    make_args: Callable[..., Args],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    tracks: dict[str, Tags] = {
        "a.mp3": {"artist": ["A"], "title": ["A"]},
        "b.mp3": {"artist": ["A"], "title": ["B"]},
    }

    _run_full(
        genplis_db,
        make_args,
        tmp_path,
        monkeypatch,
        tracks,
        "@SORT title\n@LIMIT 1 PER artist\nartist = A\n",
        "b.mp3",
    )

    output = capsys.readouterr().out
    assert "excluded: per-tag cap 1 per artist reached" in output
    assert "result: NOT IN PLAYLIST" in output


def test_trace_full_missing_per_tag_key(
    genplis_db: sqlite3.Connection,
    make_args: Callable[..., Args],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    tracks: dict[str, Tags] = {
        "a.mp3": {"artist": ["A"], "title": ["A"]},
        "missing.mp3": {"title": ["B"]},
    }

    _run_full(
        genplis_db,
        make_args,
        tmp_path,
        monkeypatch,
        tracks,
        "@SORT title\n@LIMIT 1 PER artist\n",
        "missing.mp3",
    )

    output = capsys.readouterr().out
    assert "excluded: missing artist key" in output
    assert "result: NOT IN PLAYLIST" in output


def test_trace_full_dedupe_cut(
    genplis_db: sqlite3.Connection,
    make_args: Callable[..., Args],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    tracks: dict[str, Tags] = {
        "a.mp3": {"artist": ["A"], "title": ["A"]},
        "b.mp3": {"artist": ["A"], "title": ["B"]},
    }

    _run_full(
        genplis_db,
        make_args,
        tmp_path,
        monkeypatch,
        tracks,
        "@SORT title\n@DEDUPE artist\nartist = A\n",
        "b.mp3",
    )

    output = capsys.readouterr().out
    assert "dedupe: excluded: duplicate key" in output
    assert f"winner: {tmp_path / 'a.mp3'}" in output
    assert "result: NOT IN PLAYLIST" in output


def test_trace_full_duration_cut(
    genplis_db: sqlite3.Connection,
    make_args: Callable[..., Args],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    tracks: dict[str, Tags] = {
        "a.mp3": {"artist": ["A"], "title": ["A"], "duration": 10},
        "b.mp3": {"artist": ["A"], "title": ["B"], "duration": 10},
        "c.mp3": {"artist": ["A"], "title": ["C"], "duration": 10},
    }

    _run_full(
        genplis_db,
        make_args,
        tmp_path,
        monkeypatch,
        tracks,
        "@SORT title\n@MAX-DURATION 20\nartist = A\n",
        "c.mp3",
    )

    output = capsys.readouterr().out
    assert "excluded: 10s would exceed 20s cap" in output
    assert "result: NOT IN PLAYLIST" in output


def test_trace_full_no_match_skips_the_scan(
    genplis_db: sqlite3.Connection,
    make_args: Callable[..., Args],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    tracks: dict[str, Tags] = {
        "song.mp3": {"artist": ["Test Artist"], "title": ["Test"]},
    }
    for name in tracks:
        (tmp_path / name).write_bytes(b"")
    filter_file = tmp_path / "favorites.m3ug"
    filter_file.write_text('artist = "Nobody"\n', encoding="utf-8")

    def fake_get_tags(path: Path, *_args: object, **_kwargs: object) -> Tags | None:
        return tracks.get(path.name)

    def fail_process_directory(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("the scan must be skipped")

    monkeypatch.setattr("genplis.core.get_tags", fake_get_tags)
    monkeypatch.setattr("genplis.core.process_directory", fail_process_directory)
    trace_full_path(
        genplis_db,
        genplis_db.cursor(),
        make_args(
            str(tmp_path),
            mode=Mode.TRACE_FULL,
            trace_path=tmp_path / "song.mp3",
        ),
    )

    output = capsys.readouterr().out
    assert "Selection scan skipped: no filter expression matches the target" in (output)
    assert "result: NO MATCH" in output


def test_trace_full_no_playlist_skips_the_scan(
    genplis_db: sqlite3.Connection,
    make_args: Callable[..., Args],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    tracks: dict[str, Tags] = {
        "song.mp3": {"artist": ["A"], "title": ["A"]},
    }
    for name in tracks:
        (tmp_path / name).write_bytes(b"")
    filter_file = tmp_path / "fragment.m3ug"
    filter_file.write_text("@NO-PLAYLIST\nartist = A\n", encoding="utf-8")

    def fake_get_tags(path: Path, *_args: object, **_kwargs: object) -> Tags | None:
        return tracks.get(path.name)

    def fail_process_directory(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("the scan must be skipped")

    monkeypatch.setattr("genplis.core.get_tags", fake_get_tags)
    monkeypatch.setattr("genplis.core.process_directory", fail_process_directory)
    trace_full_path(
        genplis_db,
        genplis_db.cursor(),
        make_args(
            str(tmp_path),
            mode=Mode.TRACE_FULL,
            trace_path=tmp_path / "song.mp3",
        ),
    )

    output = capsys.readouterr().out
    assert "every matching filter has @NO-PLAYLIST" in output
    assert "result: @NO-PLAYLIST" in output
    assert not filter_file.with_suffix(".m3u").exists()


def test_trace_full_excluded_target_skips_the_scan(
    genplis_db: sqlite3.Connection,
    make_args: Callable[..., Args],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    tracks: dict[str, Tags] = {
        "song.mp3": {"artist": ["A"], "title": ["A"]},
    }

    _run_full(
        genplis_db,
        make_args,
        tmp_path,
        monkeypatch,
        tracks,
        "artist = A\n",
        "song.mp3",
        exclude=[re.compile(r"song\.mp3$")],
    )

    output = capsys.readouterr().out
    assert "Selection scan skipped: target is excluded" in output
    assert "result: SKIPPED" in output


def test_trace_full_outside_root_skips_the_scan(
    genplis_db: sqlite3.Connection,
    make_args: Callable[..., Args],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    music = tmp_path / "music"
    tracks: dict[str, Tags] = {
        "song.mp3": {"artist": ["A"], "title": ["A"]},
    }

    _run_full(
        genplis_db,
        make_args,
        tmp_path,
        monkeypatch,
        tracks,
        "artist = A\n",
        "song.mp3",
        filter_path=music,
    )

    output = capsys.readouterr().out
    assert "target is outside the scan root" in output
    assert "result: SKIPPED" in output


def test_trace_full_reports_no_filters(
    genplis_db: sqlite3.Connection,
    make_args: Callable[..., Args],
    file_mp3: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    song = tmp_path / "song.mp3"
    shutil.copy2(file_mp3, song)

    trace_full_path(
        genplis_db,
        genplis_db.cursor(),
        make_args(
            str(tmp_path),
            mode=Mode.TRACE_FULL,
            trace_path=song,
        ),
    )

    assert f"No filters found in {tmp_path}" in capsys.readouterr().out


def test_trace_full_mode_conflicts(tmp_path: Path) -> None:
    parser = setup_argparse()
    for conflicting in (
        "--trace",
        "--tag-stats",
        "--show-rules",
        "--clean",
    ):
        with pytest.raises(SystemExit) as exc_info:
            parser.parse_args(["--trace-full", "song.mp3", conflicting, str(tmp_path)])
        assert exc_info.value.code == 2

    with pytest.raises(GenplisConfigError, match="cannot be combined"):
        resolve_args(
            parser.parse_args(
                ["--trace-full", "song.mp3", "-t", "genre", str(tmp_path)]
            ),
            Config(),
        )


def test_trace_full_uses_config_path() -> None:
    config = Config(collection=CollectionConfig(path=Path("/music")))

    args = resolve_args(
        setup_argparse().parse_args(["--trace-full", "/music/song.mp3"]),
        config,
    )

    assert args.mode is Mode.TRACE_FULL
    assert args.path == Path("/music")
    assert args.trace_path == Path("/music/song.mp3")


def test_main_trace_full_writes_no_playlist(
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
            "--trace-full",
            str(song),
            "--no-config",
            "--db",
            str(db_path),
            str(filter_file),
        ],
    )

    main()

    output = capsys.readouterr().out
    assert "result: IN PLAYLIST at position 1" in output
    assert not filter_file.with_suffix(".m3u").exists()
    assert db_path.exists()


def test_trace_mode_has_no_selection_section(
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
        make_args(
            str(filter_file),
            mode=Mode.TRACE,
            trace_path=song,
        ),
    )

    assert "\nselection:" not in capsys.readouterr().out
