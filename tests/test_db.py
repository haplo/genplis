import sqlite3
from pathlib import Path

import pytest

import genplis.db as db
from genplis.config import TagsConfig
from genplis.db import (
    CacheStatus,
    WriteBatch,
    cache_tags_for_file,
    create_files_table,
    get_cache_status,
    get_cache_version,
    get_cached_tags,
    get_db_path,
    remove_missing_files,
    setup_database_connection,
)
from genplis.exceptions import GenplisDBError
from genplis.files import get_last_modified


def test_get_db_path(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XDG_CACHE_HOME", "/home/user/.cache")
    assert get_db_path() == Path("/home/user/.cache/genplis/genplis.db")


def test_get_db_path_override(tmp_path: Path) -> None:
    custom_path = tmp_path / "custom.db"
    assert get_db_path(custom_path) == custom_path


def test_get_db_key_normalizes_dot_dot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)

    assert db.get_db_key(Path("a/../b")) == db.get_db_key(Path("b"))


def test_db_connection_and_create(tmp_path: Path) -> None:
    db_path = tmp_path / "genplis.db"
    try:
        conn, cursor = setup_database_connection(db_path)
        create_files_table(cursor)
        # check the database schema is as expected
        rows = cursor.execute("select * from sqlite_schema").fetchall()
        assert rows == [
            (
                "table",
                "cache_meta",
                "cache_meta",
                2,
                "CREATE TABLE cache_meta (\n"
                "            key TEXT PRIMARY KEY,\n"
                "            value TEXT NOT NULL\n"
                "        )",
            ),
            (
                "index",
                "sqlite_autoindex_cache_meta_1",
                "cache_meta",
                3,
                None,
            ),
            (
                "table",
                "files",
                "files",
                4,
                "CREATE TABLE files (\n"
                "            path TEXT PRIMARY KEY,\n"
                "            last_modified TIMESTAMP,\n"
                "            tags JSONB\n"
                "        )",
            ),
            (
                "index",
                "sqlite_autoindex_files_1",
                "files",
                5,
                None,
            ),
        ]
    finally:
        conn.close()


def test_setup_database_connection_keeps_integer_timestamps(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "genplis.db"
    conn, cursor = setup_database_connection(db_path)
    try:
        create_files_table(cursor)
        cursor.execute(
            "INSERT INTO files(path, last_modified, tags) VALUES ('/x', 12345, '{}')"
        )
        assert cursor.execute("SELECT last_modified FROM files").fetchone() == (12345,)
    finally:
        conn.close()


def test_get_cache_status(genplis_db: sqlite3.Connection, file_mp3: Path) -> None:
    # not present in DB
    assert get_cache_status(genplis_db.cursor(), file_mp3) is CacheStatus.MISS

    # simulate file being cached
    timestamp = get_last_modified(file_mp3)
    genplis_db.execute(
        "INSERT INTO files(path, last_modified, tags) VALUES (?, ?, '{}')",
        [str(file_mp3), timestamp],
    )
    assert get_cache_status(genplis_db.cursor(), file_mp3) is CacheStatus.HIT

    # manually make cached timestamp stale
    genplis_db.execute(
        "UPDATE files SET last_modified=last_modified-1 WHERE path=?",
        [str(file_mp3)],
    )
    assert get_cache_status(genplis_db.cursor(), file_mp3) is CacheStatus.STALE


def test_cache_tags_for_file(genplis_db: sqlite3.Connection, file_mp3: Path) -> None:
    timestamp = get_last_modified(file_mp3)
    cache_tags_for_file(genplis_db.cursor(), file_mp3, {"a": "b"})
    rows = genplis_db.execute("SELECT * from files").fetchall()
    assert rows == [(str(file_mp3), timestamp, '{"a": "b"}')]


def test_cache_lookup_with_relative_path(
    genplis_db: sqlite3.Connection,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cached tags must be retrievable with a relative path.

    Paths are stored as absolute paths, so all DB operations need to
    normalize them the same way.
    """
    song = tmp_path / "song.mp3"
    song.write_bytes(b"")
    monkeypatch.chdir(tmp_path)

    relative_song = Path(song.name)
    cache_tags_for_file(genplis_db.cursor(), relative_song, {"a": "b"})

    assert get_cache_status(genplis_db.cursor(), relative_song) is CacheStatus.HIT
    assert get_cached_tags(genplis_db.cursor(), relative_song) == {"a": "b"}


def test_cache_invalidated_on_version_change(
    genplis_db: sqlite3.Connection,
    file_mp3: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cache_tags_for_file(genplis_db.cursor(), file_mp3, {"a": "b"})
    assert genplis_db.execute("SELECT count(*) FROM files").fetchone() == (1,)

    monkeypatch.setattr(db, "CACHE_SCHEMA_VERSION", 999)
    db.create_files_table(genplis_db.cursor())

    assert genplis_db.execute("SELECT count(*) FROM files").fetchone() == (0,)


def test_cache_version_includes_tag_settings() -> None:
    default_version = get_cache_version()

    assert default_version != get_cache_version(TagsConfig(max_size=1))
    assert default_version != get_cache_version(
        TagsConfig(ignore=frozenset({"artist"}))
    )


def test_cache_invalidated_on_tag_config_change(
    genplis_db: sqlite3.Connection,
    file_mp3: Path,
) -> None:
    cache_tags_for_file(genplis_db.cursor(), file_mp3, {"a": "b"})
    assert genplis_db.execute("SELECT count(*) FROM files").fetchone() == (1,)

    db.create_files_table(
        genplis_db.cursor(),
        get_cache_version(TagsConfig(max_size=1)),
    )

    assert genplis_db.execute("SELECT count(*) FROM files").fetchone() == (0,)


def insert_cached_path(conn: sqlite3.Connection, path: Path) -> None:
    conn.execute(
        "INSERT INTO files(path, last_modified, tags) VALUES (?, 0, '{}')",
        (str(path.absolute()),),
    )


def test_remove_missing_files_removes_only_missing(
    genplis_db: sqlite3.Connection,
    file_mp3: Path,
    tmp_path: Path,
) -> None:
    missing = tmp_path / "gone.mp3"
    cache_tags_for_file(genplis_db.cursor(), file_mp3, {"a": "b"})
    insert_cached_path(genplis_db, missing)

    removed = remove_missing_files(genplis_db.cursor())

    assert removed == [missing.absolute()]
    assert genplis_db.execute("SELECT path FROM files").fetchall() == [(str(file_mp3),)]


def test_remove_missing_files_respects_root(
    genplis_db: sqlite3.Connection,
    tmp_path: Path,
) -> None:
    root = tmp_path / "music"
    root.mkdir()
    outside = tmp_path / "music2"
    outside.mkdir()
    inside = tmp_path / "music" / "gone.mp3"
    outside_file = outside / "gone.mp3"
    existing = root / "keep.mp3"
    existing.write_bytes(b"")

    insert_cached_path(genplis_db, inside)
    insert_cached_path(genplis_db, outside_file)
    insert_cached_path(genplis_db, existing)

    removed = remove_missing_files(genplis_db.cursor(), root)

    assert removed == [inside]
    assert set(genplis_db.execute("SELECT path FROM files").fetchall()) == {
        (str(outside_file),),
        (str(existing),),
    }


def test_remove_missing_files_without_root_cleans_whole_db(
    genplis_db: sqlite3.Connection,
    tmp_path: Path,
) -> None:
    first = tmp_path / "first" / "gone.mp3"
    second = tmp_path / "second" / "gone.mp3"
    insert_cached_path(genplis_db, first)
    insert_cached_path(genplis_db, second)

    removed = remove_missing_files(genplis_db.cursor())

    assert set(removed) == {first.absolute(), second.absolute()}
    assert genplis_db.execute("SELECT count(*) FROM files").fetchone() == (0,)


def test_remove_missing_files_on_empty_db(genplis_db: sqlite3.Connection) -> None:
    assert remove_missing_files(genplis_db.cursor()) == []


def test_get_cached_tags_success(genplis_db: sqlite3.Connection) -> None:
    genplis_db.execute(
        "INSERT INTO files(path, last_modified, tags) VALUES ('/some/path', 12345, '{\"a\": \"b\"}')"
    )
    tags = get_cached_tags(genplis_db.cursor(), Path("/some/path"))
    assert tags == {"a": "b"}


def _row_count(db_path: Path) -> int:
    conn, cursor = setup_database_connection(db_path)
    try:
        return cursor.execute("SELECT count(*) FROM files").fetchone()[0]
    finally:
        conn.close()


def test_write_batch_commits_every_n_writes(tmp_path: Path) -> None:
    db_path = tmp_path / "batch.db"
    conn, cursor = setup_database_connection(db_path)
    try:
        create_files_table(cursor)
        conn.commit()
        batch = WriteBatch(conn, every=3)

        for index in range(2):
            batch.store(
                cursor,
                tmp_path / f"song-{index}.mp3",
                {"title": [str(index)]},
                last_modified=index,
            )
        assert _row_count(db_path) == 0

        batch.store(
            cursor,
            tmp_path / "song-2.mp3",
            {"title": ["2"]},
            last_modified=2,
        )
        assert _row_count(db_path) == 3
        assert batch.seconds > 0
    finally:
        conn.close()


def test_write_batch_with_zero_commits_only_on_flush(tmp_path: Path) -> None:
    db_path = tmp_path / "batch.db"
    conn, cursor = setup_database_connection(db_path)
    try:
        create_files_table(cursor)
        conn.commit()
        batch = WriteBatch(conn, every=0)

        for index in range(5):
            batch.store(
                cursor,
                tmp_path / f"song-{index}.mp3",
                {},
                last_modified=index,
            )
        assert _row_count(db_path) == 0

        batch.flush()
        assert _row_count(db_path) == 5
    finally:
        conn.close()


def test_write_batch_ignores_cache_hits(tmp_path: Path) -> None:
    db_path = tmp_path / "batch.db"
    conn, cursor = setup_database_connection(db_path)
    try:
        create_files_table(cursor)
        conn.commit()
        batch = WriteBatch(conn, every=3)

        for index in range(10):
            assert (
                get_cache_status(
                    cursor,
                    tmp_path / f"song-{index}.mp3",
                    last_modified=index,
                )
                is CacheStatus.MISS
            )

        for index in range(2):
            batch.store(
                cursor,
                tmp_path / f"song-{index}.mp3",
                {},
                last_modified=index,
            )
        assert _row_count(db_path) == 0

        batch.flush()
        assert _row_count(db_path) == 2
    finally:
        conn.close()


def test_get_cached_tags_error_if_missing(genplis_db: sqlite3.Connection) -> None:
    with pytest.raises(GenplisDBError):
        get_cached_tags(genplis_db.cursor(), Path("/invalid/path/"))


@pytest.mark.parametrize("stored_tags", ["not json", None])
def test_get_cached_tags_error_if_data_is_invalid(
    genplis_db: sqlite3.Connection, stored_tags: str | None
) -> None:
    genplis_db.execute(
        "INSERT INTO files(path, last_modified, tags) VALUES (?, 0, ?)",
        ("/some/path", stored_tags),
    )

    with pytest.raises(GenplisDBError, match="invalid cached tag data"):
        get_cached_tags(genplis_db.cursor(), Path("/some/path"))
