import json
import sqlite3
from datetime import datetime
from pathlib import Path

from xdg_base_dirs import xdg_cache_home

from .exceptions import GenplisDBError
from .json import GenplisJSONEncoder

DB_NAME = "genplis.db"


def get_db_path():
    db_path = xdg_cache_home() / "genplis" / DB_NAME
    return db_path


def setup_database_connection(conn_path):
    conn = sqlite3.connect(conn_path)
    cursor = conn.cursor()
    return conn, cursor


def create_files_table(cursor):
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS files (
            path TEXT PRIMARY KEY,
            last_modified TIMESTAMP,
            tags JSONB
        )
    """)


def is_cache_valid(cursor, file_path: Path) -> bool | None:
    """True if the file is cached in DB and the entry is not stale.

    False if file_path is in DB but the timestamp of the file is
    more recent (i.e. cache is stale and shouldn't be used).

    None if file_path is not in DB.

    Cached tags can then be retrieved with get_cached_tags.

    """
    abs_file_path = file_path.absolute()
    file_last_modified = datetime.fromtimestamp(file_path.stat().st_mtime)

    # Check if the file path already exists in the database
    cursor.execute(
        """SELECT last_modified FROM files WHERE path = ?""",
        (str(abs_file_path),),
    )
    row = cursor.fetchone()
    if row is None:
        return None

    cached_timestamp = row[0]
    db_last_modified = datetime.fromisoformat(cached_timestamp)
    return file_last_modified <= db_last_modified


def cache_tags_for_file(cursor, file_path: Path, tags):
    """Save given tags for a music file in DB.

    Caller is responsible for calling commit on the DB connection.

    """
    file_path = file_path.absolute()
    last_modified = datetime.fromtimestamp(file_path.stat().st_mtime)
    json_tags = json.dumps(tags, cls=GenplisJSONEncoder)

    # UPSERT: https://www.sqlite.org/lang_upsert.html
    # Attempt to insert entry on DB, if path already exists then update tags and
    # last_modified
    cursor.execute(
        """INSERT INTO files(path, last_modified, tags)
        VALUES (?, ?, ?)
        ON CONFLICT(path) DO
        UPDATE SET last_modified=?, tags=?
        """,
        (str(file_path), last_modified, json_tags, last_modified, json_tags),
    )
    print(f"Updated cache for file: {file_path}")


def get_cached_tags(cursor, file_path: Path):
    """Retrieve cached tags for the given file.

    Should have previously called is_cache_valid to check that the file is
    actually cached and that the data is not stale.

    Will raise GenplisDBError if file_path is not actually on DB.

    """
    cursor.execute(
        """SELECT tags FROM files WHERE path = ?""",
        (str(file_path),),
    )
    row = cursor.fetchone()
    if row:
        return json.loads(row[0])

    raise GenplisDBError(f"{file_path} not found on DB")
