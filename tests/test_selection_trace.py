import sqlite3
from collections.abc import Callable
from pathlib import Path

import pytest

from genplis.core import Args, process_directory
from genplis.diagnostics import FilterSelectionTrace, SelectionTrace
from genplis.types import Tags


def _run_selection(
    genplis_db: sqlite3.Connection,
    make_args: Callable[..., Args],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    tracks: dict[str, Tags],
    content: str,
    target_name: str,
    *,
    dry_run: bool = True,
) -> tuple[Path, FilterSelectionTrace]:
    for name in tracks:
        (tmp_path / name).write_bytes(b"")
    filter_file = tmp_path / "favorites.m3ug"
    filter_file.write_text(content, encoding="utf-8")

    def fake_get_tags(path: Path, *_args: object, **_kwargs: object) -> Tags | None:
        return tracks.get(path.name)

    monkeypatch.setattr("genplis.core.get_tags", fake_get_tags)
    trace = SelectionTrace(target=tmp_path / target_name)
    process_directory(
        genplis_db,
        genplis_db.cursor(),
        tmp_path,
        make_args(
            str(tmp_path),
            include_source=False,
            extended_m3u=False,
        ),
        dry_run=dry_run,
        selection_trace=trace,
    )
    return filter_file, trace.filters[filter_file]


def test_records_selected_target(
    genplis_db: sqlite3.Connection,
    make_args: Callable[..., Args],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tracks: dict[str, Tags] = {
        "a.mp3": {"artist": ["A"], "title": ["A"]},
        "b.mp3": {"artist": ["A"], "title": ["B"]},
    }

    _, result = _run_selection(
        genplis_db,
        make_args,
        tmp_path,
        monkeypatch,
        tracks,
        "@SORT title\nartist = A\n",
        "b.mp3",
    )

    assert result.considered is True
    assert result.total_matches == 2
    assert result.sorted_position == 2
    assert result.sort_values == ("b",)
    assert result.selected is True
    assert result.position == 2
    assert result.reason == "selected"
    assert result.limit_result == "no count cap"


def test_records_dedupe_exclusion_and_winner(
    genplis_db: sqlite3.Connection,
    make_args: Callable[..., Args],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tracks: dict[str, Tags] = {
        "a.mp3": {"artist": ["A"], "title": ["A"]},
        "b.mp3": {"artist": ["A"], "title": ["B"]},
    }

    _, result = _run_selection(
        genplis_db,
        make_args,
        tmp_path,
        monkeypatch,
        tracks,
        "@SORT title\n@DEDUPE artist\nartist = A\n",
        "b.mp3",
    )

    assert result.sorted_position == 2
    assert result.dedupe_result == "excluded: duplicate key"
    assert result.dedupe_winner == tmp_path / "a.mp3"
    assert result.selected is False
    assert result.considered is False
    assert result.reason == "excluded: duplicate key"


def test_records_count_limit(
    genplis_db: sqlite3.Connection,
    make_args: Callable[..., Args],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tracks: dict[str, Tags] = {
        "a.mp3": {"artist": ["A"], "title": ["A"]},
        "b.mp3": {"artist": ["A"], "title": ["B"]},
        "c.mp3": {"artist": ["A"], "title": ["C"]},
    }

    _, result = _run_selection(
        genplis_db,
        make_args,
        tmp_path,
        monkeypatch,
        tracks,
        "@SORT title\n@LIMIT 2\nartist = A\n",
        "c.mp3",
    )

    assert result.sorted_position == 3
    assert result.selected is False
    assert result.limit_result == "excluded: count cap 2 reached"
    assert result.reason == "excluded: count cap 2 reached"


def test_records_per_tag_limit(
    genplis_db: sqlite3.Connection,
    make_args: Callable[..., Args],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tracks: dict[str, Tags] = {
        "a.mp3": {"artist": ["A"], "title": ["A"]},
        "b.mp3": {"artist": ["A"], "title": ["B"]},
    }

    _, result = _run_selection(
        genplis_db,
        make_args,
        tmp_path,
        monkeypatch,
        tracks,
        "@SORT title\n@LIMIT 1 PER artist\nartist = A\n",
        "b.mp3",
    )

    assert result.limit_key == "a"
    assert result.selected is False
    assert result.per_tag_result == "excluded: per-tag cap 1 per artist reached"
    assert result.reason == result.per_tag_result


def test_records_missing_per_tag_key(
    genplis_db: sqlite3.Connection,
    make_args: Callable[..., Args],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tracks: dict[str, Tags] = {
        "a.mp3": {"artist": ["A"], "title": ["A"]},
        "missing.mp3": {"title": ["B"]},
    }

    _, result = _run_selection(
        genplis_db,
        make_args,
        tmp_path,
        monkeypatch,
        tracks,
        "@SORT title\n@LIMIT 1 PER artist\n",
        "missing.mp3",
    )

    assert result.limit_key is None
    assert result.selected is False
    assert result.per_tag_result == "excluded: missing artist key"


def test_records_duration_limit(
    genplis_db: sqlite3.Connection,
    make_args: Callable[..., Args],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tracks: dict[str, Tags] = {
        "a.mp3": {"artist": ["A"], "title": ["A"], "duration": 10},
        "b.mp3": {"artist": ["A"], "title": ["B"], "duration": 10},
        "c.mp3": {"artist": ["A"], "title": ["C"], "duration": 10},
    }

    _, result = _run_selection(
        genplis_db,
        make_args,
        tmp_path,
        monkeypatch,
        tracks,
        "@SORT title\n@MAX-DURATION 20\nartist = A\n",
        "c.mp3",
    )

    assert result.selected is False
    assert result.duration_result == "excluded: 10s would exceed 20s cap"
    assert result.reason == result.duration_result


def test_dry_run_writes_no_playlist(
    genplis_db: sqlite3.Connection,
    make_args: Callable[..., Args],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tracks: dict[str, Tags] = {
        "song.mp3": {"artist": ["A"], "title": ["A"]},
    }

    filter_file, result = _run_selection(
        genplis_db,
        make_args,
        tmp_path,
        monkeypatch,
        tracks,
        "artist = A\n",
        "song.mp3",
        dry_run=True,
    )

    assert result.selected is True
    assert not filter_file.with_suffix(".m3u").exists()


def test_normal_run_without_trace_still_writes_playlist(
    genplis_db: sqlite3.Connection,
    make_args: Callable[..., Args],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tracks: dict[str, Tags] = {
        "song.mp3": {"artist": ["A"], "title": ["A"]},
    }
    for name in tracks:
        (tmp_path / name).write_bytes(b"")
    filter_file = tmp_path / "favorites.m3ug"
    filter_file.write_text("artist = A\n", encoding="utf-8")

    def fake_get_tags(path: Path, *_args: object, **_kwargs: object) -> Tags | None:
        return tracks.get(path.name)

    monkeypatch.setattr("genplis.core.get_tags", fake_get_tags)
    process_directory(
        genplis_db,
        genplis_db.cursor(),
        tmp_path,
        make_args(
            str(tmp_path),
            include_source=False,
            extended_m3u=False,
        ),
    )

    assert filter_file.with_suffix(".m3u").read_text() == "song.mp3\n"
