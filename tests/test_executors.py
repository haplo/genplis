import os
import shutil
from dataclasses import replace
from pathlib import Path

import pytest

import genplis.executors as executors
from genplis.config import Config
from genplis.core import Args, process_directory
from genplis.db import create_files_table, setup_database_connection
from genplis.executors import (
    MAX_AUTO_WORKERS,
    MIN_PARALLEL_FILES,
    ParseOrder,
    ParseSettings,
    ProcessExecutor,
    SequentialExecutor,
    auto_workers,
    make_executor,
)
from genplis.types import Tags, Verbosity


def _settings() -> ParseSettings:
    return ParseSettings(
        max_size=1000,
        ignore=frozenset(),
        verbosity=Verbosity.NORMAL,
    )


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
    conn, cursor = setup_database_connection(db_path)
    try:
        create_files_table(cursor)
        all_tags, _ = process_directory(
            conn, cursor, root, _make_args(root, db_path, jobs)
        )
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
    executor = make_executor(1, MIN_PARALLEL_FILES, ParseOrder.ORDERED, _settings())
    try:
        assert isinstance(executor, SequentialExecutor)
    finally:
        executor.close()


def test_make_executor_stays_sequential_for_small_runs() -> None:
    executor = make_executor(8, MIN_PARALLEL_FILES - 1, ParseOrder.ORDERED, _settings())
    try:
        assert isinstance(executor, SequentialExecutor)
    finally:
        executor.close()


def test_make_executor_uses_processes_for_enough_work() -> None:
    executor = make_executor(2, MIN_PARALLEL_FILES, ParseOrder.ORDERED, _settings())
    try:
        assert isinstance(executor, ProcessExecutor)
        assert executor.workers == 2
    finally:
        executor.close()


def test_ordered_process_pool_matches_sequential(
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


def test_ordered_process_pool_reports_worker_count(
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


def test_rows_are_visible_after_ordered_run(tmp_path: Path, file_mp3: Path) -> None:
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
