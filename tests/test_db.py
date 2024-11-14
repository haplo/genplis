from pathlib import Path

from genplis.db import (
    cache_tags_for_file,
    create_files_table,
    get_db_path,
    is_cache_valid,
    setup_database_connection,
)
from genplis.files import get_last_modified


def test_get_db_path(monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", "/home/user/.cache")
    assert get_db_path() == Path("/home/user/.cache/genplis/genplis.db")


def test_db_connection_and_create(tmp_path):
    db_path = tmp_path / "genplis.db"
    try:
        conn, cursor = setup_database_connection(db_path)
        create_files_table(cursor)
        # check the database schema is as expected
        rows = cursor.execute("select * from sqlite_schema").fetchall()
        assert rows == [
            (
                "table",
                "files",
                "files",
                2,
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
                3,
                None,
            ),
        ]
    finally:
        conn.close()


def test_is_cache_valid(genplis_db, file_mp3):
    # not present in DB
    assert is_cache_valid(genplis_db.cursor(), file_mp3) is None

    # simulate file being cached
    timestamp = get_last_modified(file_mp3)
    genplis_db.execute(
        "INSERT INTO files(path, last_modified, tags) VALUES (?, ?, '{}')",
        [str(file_mp3), timestamp],
    )
    assert is_cache_valid(genplis_db.cursor(), file_mp3) is True

    # manually make cached timestamp stale
    genplis_db.execute(
        "UPDATE files SET last_modified=last_modified-1 WHERE path=?",
        [str(file_mp3)],
    )
    assert is_cache_valid(genplis_db.cursor(), file_mp3) is False


def test_cache_tags_for_file(genplis_db, file_mp3):
    timestamp = get_last_modified(file_mp3)
    cache_tags_for_file(genplis_db.cursor(), file_mp3, {"a": "b"})
    rows = genplis_db.execute("SELECT * from files").fetchall()
    assert rows == [
        ("/home/fidel/Code/genplis/tests/files/test.mp3", timestamp, '{"a": "b"}')
    ]
