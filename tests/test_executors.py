import os
import shutil
from collections import Counter
from collections.abc import Iterator, Sequence
from dataclasses import replace
from pathlib import Path

import pytest

import genplis.executors as executors
from genplis.config import Config, TagsConfig
from genplis.core import Args, process_directory
from genplis.db import (
    create_files_table,
    get_cache_version,
    setup_database_connection,
)
from genplis.executors import (
    MAX_AUTO_WORKERS,
    MIN_PARALLEL_FILES,
    ParseItem,
    ParseResult,
    ProcessExecutor,
    SequentialExecutor,
    auto_workers,
    make_executor,
)
from genplis.types import Tags, Verbosity


def _settings() -> TagsConfig:
    return TagsConfig()


def _make_args(root: Path, db_path: Path, jobs: int) -> Args:
    return Args(
        path=root,
        exclude=(),
        verbosity=Verbosity.NORMAL,
        overwrite=True,
        db_path=db_path,
        config=Config(),
        jobs=jobs,
    )


def _run(
    root: Path,
    db_path: Path,
    jobs: int,
) -> tuple[dict[Path, Tags], list[tuple[str, int, str]]]:
    args = _make_args(root, db_path, jobs)
    conn, cursor = setup_database_connection(db_path)
    try:
        create_files_table(cursor)
        all_tags, _ = process_directory(conn, cursor, root, args, retain_tags=True)
        rows = cursor.execute(
            "SELECT path, last_modified, tags FROM files ORDER BY path"
        ).fetchall()
    finally:
        conn.close()
    return all_tags, rows


def test_auto_workers_caps_at_eight(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        os,
        "sched_getaffinity",
        lambda _pid: set(range(32)),
        raising=False,
    )

    assert auto_workers() == MAX_AUTO_WORKERS


def test_make_executor_stays_sequential_for_one_worker() -> None:
    executor = make_executor(1, MIN_PARALLEL_FILES, _settings())
    try:
        assert isinstance(executor, SequentialExecutor)
    finally:
        executor.close()


def test_make_executor_stays_sequential_for_small_runs() -> None:
    executor = make_executor(8, MIN_PARALLEL_FILES - 1, _settings())
    try:
        assert isinstance(executor, SequentialExecutor)
    finally:
        executor.close()


def test_make_executor_uses_processes_for_enough_work() -> None:
    executor = make_executor(2, MIN_PARALLEL_FILES, _settings())
    try:
        assert isinstance(executor, ProcessExecutor)
        assert executor.workers == 2
    finally:
        executor.close()


def test_process_pool_matches_sequential(
    tmp_path: Path,
    file_mp3: Path,
    file_ogg: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "music"
    root.mkdir()
    for index in range(4):
        source = file_mp3 if index % 2 == 0 else file_ogg
        shutil.copy2(source, root / f"song-{index}.{source.suffix[1:]}")
    filter_file = root / "favorites.m3ug"
    filter_file.write_text('artist = "Test Artist"\n', encoding="utf-8")

    monkeypatch.setattr(executors, "MIN_PARALLEL_FILES", 4)
    sequential_tags, sequential_rows = _run(root, tmp_path / "seq.db", jobs=1)
    playlist = filter_file.with_suffix(".m3u").read_bytes()
    parallel_tags, parallel_rows = _run(root, tmp_path / "parallel.db", jobs=2)

    assert list(parallel_tags) == list(sequential_tags)
    assert parallel_tags == sequential_tags
    assert filter_file.with_suffix(".m3u").read_bytes() == playlist
    assert parallel_rows == sequential_rows


def test_process_pool_reports_worker_count(
    tmp_path: Path,
    file_mp3: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = tmp_path / "music"
    root.mkdir()
    for index in range(4):
        shutil.copy2(file_mp3, root / f"song-{index}.mp3")

    monkeypatch.setattr(executors, "MIN_PARALLEL_FILES", 4)
    args = replace(
        _make_args(root, tmp_path / "cache.db", jobs=2),
        verbosity=Verbosity.VERBOSE,
    )
    conn, cursor = setup_database_connection(tmp_path / "cache.db")
    try:
        create_files_table(cursor)
        process_directory(conn, cursor, root, args)
    finally:
        conn.close()

    assert "Parsing with 2 worker processes" in capsys.readouterr().out


def test_warm_directory_does_not_spawn_pool(
    tmp_path: Path,
    file_mp3: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "music"
    root.mkdir()
    for index in range(4):
        shutil.copy2(file_mp3, root / f"song-{index}.mp3")

    monkeypatch.setattr(executors, "MIN_PARALLEL_FILES", 4)
    db_path = tmp_path / "cache.db"
    _run(root, db_path, jobs=1)

    def fail_process_executor(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("a fully cached run must not create a process pool")

    monkeypatch.setattr(executors, "ProcessExecutor", fail_process_executor)
    tags, _ = _run(root, db_path, jobs=2)

    assert len(tags) == 4


def test_rows_are_visible_after_inline_run(tmp_path: Path, file_mp3: Path) -> None:
    root = tmp_path / "music"
    root.mkdir()
    song = root / "song.mp3"
    shutil.copy2(file_mp3, song)

    _run(root, tmp_path / "cache.db", jobs=1)

    conn, cursor = setup_database_connection(tmp_path / "cache.db")
    try:
        assert cursor.execute("SELECT count(*) FROM files").fetchone() == (1,)
    finally:
        conn.close()


def test_parallel_refreshes_only_stale_rows(
    tmp_path: Path,
    file_mp3: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "music"
    root.mkdir()
    for index in range(8):
        shutil.copy2(file_mp3, root / f"song-{index}.mp3")
    (root / "notes.txt").write_text("not music\n", encoding="utf-8")
    filter_file = root / "favorites.m3ug"
    filter_file.write_text('artist = "Test Artist"\n', encoding="utf-8")

    monkeypatch.setattr(executors, "MIN_PARALLEL_FILES", 4)
    db_path = tmp_path / "cache.db"
    first_tags, first_rows = _run(root, db_path, jobs=1)
    playlist = filter_file.with_suffix(".m3u").read_bytes()

    for index in range(4, 8):
        song = root / f"song-{index}.mp3"
        mtime = song.stat().st_mtime + 10
        os.utime(song, (mtime, mtime))

    second_tags, second_rows = _run(root, db_path, jobs=2)

    first = {Path(path).name: (modified, tags) for path, modified, tags in first_rows}
    second = {Path(path).name: (modified, tags) for path, modified, tags in second_rows}
    for index in range(4):
        name = f"song-{index}.mp3"
        assert second[name] == first[name]
    for index in range(4, 8):
        name = f"song-{index}.mp3"
        assert second[name][0] > first[name][0]
        assert second[name][1] == first[name][1]
    assert "notes.txt" not in second
    assert list(second_tags) == list(first_tags)
    assert filter_file.with_suffix(".m3u").read_bytes() == playlist


def test_parallel_rebuilds_tags_in_walk_order(
    tmp_path: Path,
    file_mp3: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "music"
    root.mkdir()
    for index in range(4):
        shutil.copy2(file_mp3, root / f"song-{index}.mp3")
    filter_file = root / "favorites.m3ug"
    filter_file.write_text('artist = "Test Artist"\n', encoding="utf-8")

    audio_order = [
        Path(current) / name
        for current, _dirs, names in root.walk()
        for name in names
        if name.endswith(".mp3")
    ]
    monkeypatch.setattr(executors, "MIN_PARALLEL_FILES", 2)
    db_path = tmp_path / "cache.db"
    _run(root, db_path, jobs=1)

    for song in audio_order[-2:]:
        mtime = song.stat().st_mtime + 10
        os.utime(song, (mtime, mtime))

    tags, _ = _run(root, db_path, jobs=2)

    assert list(tags) == audio_order
    playlist_entries = [
        line
        for line in filter_file.with_suffix(".m3u").read_text().splitlines()
        if not line.startswith("#")
    ]
    assert playlist_entries == [path.name for path in audio_order]


def test_pipeline_caches_empty_tags_and_skips_unsupported(
    tmp_path: Path,
    file_mp3: Path,
) -> None:
    root = tmp_path / "music"
    root.mkdir()
    songs = [root / "one.mp3", root / "two.mp3"]
    for song in songs:
        shutil.copy2(file_mp3, song)
    unsupported = root / "notes.txt"
    unsupported.write_text("not music\n", encoding="utf-8")

    ignored = frozenset(
        {
            "artist",
            "bitrate",
            "channels",
            "duration",
            "encoder_settings",
            "filename",
            "filesize",
            "genre",
            "is_lossless",
            "mime_type",
            "samplerate",
            "title",
        }
    )
    args = replace(
        _make_args(root, tmp_path / "cache.db", jobs=2),
        config=Config(tags=TagsConfig(ignore=ignored)),
    )
    conn, cursor = setup_database_connection(tmp_path / "cache.db")
    try:
        create_files_table(cursor, get_cache_version(args.config.tags))
        all_tags, _ = process_directory(conn, cursor, root, args, retain_tags=True)
        rows = cursor.execute("SELECT path, tags FROM files ORDER BY path").fetchall()
    finally:
        conn.close()

    assert all_tags == {song: {} for song in songs}
    assert [Path(path).name for path, _tags in rows] == ["one.mp3", "two.mp3"]
    assert [tags for _path, tags in rows] == ["{}", "{}"]
    assert str(unsupported) not in {path for path, _tags in rows}


def test_parallel_verbose_diagnostics_are_preserved(
    tmp_path: Path,
    file_mp3: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = tmp_path / "music"
    root.mkdir()
    for index in range(4):
        shutil.copy2(file_mp3, root / f"song-{index}.mp3")

    monkeypatch.setattr(executors, "MIN_PARALLEL_FILES", 4)
    config = Config(tags=TagsConfig(max_size=1, ignore=frozenset({"artist"})))
    args = replace(
        _make_args(root, tmp_path / "cache.db", jobs=2),
        verbosity=Verbosity.VERBOSE,
        config=config,
    )

    conn, cursor = setup_database_connection(tmp_path / "cache.db")
    try:
        create_files_table(cursor, get_cache_version(config.tags))
        process_directory(conn, cursor, root, args)
    finally:
        conn.close()

    diagnostics = Counter(
        line
        for line in capsys.readouterr().out.splitlines()
        if line.startswith(("Removing tag", "Skipping", "Updated cache"))
    )
    assert (
        diagnostics["Removing tag artist because it is configured to be ignored"] == 4
    )
    assert diagnostics["Removing tag title because it's larger than 1 UTF-8 bytes"] == 4
    assert (
        sum(
            count
            for line, count in diagnostics.items()
            if line.startswith("Updated cache")
        )
        == 4
    )


class _InterruptingExecutor:
    def __init__(self) -> None:
        self.cancelled = False

    def parse(self, items: Sequence[ParseItem]) -> Iterator[ParseResult]:
        item = items[0]
        yield ParseResult(item, {"title": ["Interrupted"]}, ())
        raise KeyboardInterrupt

    def close(self, *, cancel: bool = False) -> None:
        self.cancelled = cancel


class _FailingExecutor(_InterruptingExecutor):
    def parse(self, items: Sequence[ParseItem]) -> Iterator[ParseResult]:
        item = items[0]
        yield ParseResult(item, {"title": ["Failed"]}, ())
        raise RuntimeError("parse failed")


def test_interrupt_flushes_stored_rows(
    tmp_path: Path,
    file_mp3: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "music"
    root.mkdir()
    song = root / "song.mp3"
    shutil.copy2(file_mp3, song)

    executor = _InterruptingExecutor()
    monkeypatch.setattr(
        "genplis.core.make_executor",
        lambda *_args, **_kwargs: executor,
    )
    args = _make_args(root, tmp_path / "cache.db", jobs=2)

    conn, cursor = setup_database_connection(tmp_path / "cache.db")
    try:
        create_files_table(cursor)
        with pytest.raises(KeyboardInterrupt):
            process_directory(conn, cursor, root, args)
    finally:
        conn.close()

    assert executor.cancelled
    conn, cursor = setup_database_connection(tmp_path / "cache.db")
    try:
        assert cursor.execute("SELECT path FROM files").fetchall() == [(str(song),)]
    finally:
        conn.close()


def test_error_flushes_stored_rows(
    tmp_path: Path,
    file_mp3: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "music"
    root.mkdir()
    song = root / "song.mp3"
    shutil.copy2(file_mp3, song)

    executor = _FailingExecutor()
    monkeypatch.setattr(
        "genplis.core.make_executor",
        lambda *_args, **_kwargs: executor,
    )
    args = _make_args(root, tmp_path / "cache.db", jobs=2)

    conn, cursor = setup_database_connection(tmp_path / "cache.db")
    try:
        create_files_table(cursor)
        with pytest.raises(RuntimeError, match="parse failed"):
            process_directory(conn, cursor, root, args)
    finally:
        conn.close()

    assert executor.cancelled
    conn, cursor = setup_database_connection(tmp_path / "cache.db")
    try:
        assert cursor.execute("SELECT path FROM files").fetchall() == [(str(song),)]
    finally:
        conn.close()
