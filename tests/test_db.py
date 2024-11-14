from pathlib import Path

from genplis.db import (
    create_files_table,
    get_db_path,
    setup_database_connection,
)


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
