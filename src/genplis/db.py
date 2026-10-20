import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import cast

import tinytag
from xdg_base_dirs import xdg_cache_home

from .config import TagsConfig
from .exceptions import GenplisDBError
from .files import get_last_modified
from .json import GenplisJSONEncoder
from .types import Tags

DB_NAME = "genplis.db"
# Bump this when the way genplis extracts or stores tags changes.
CACHE_SCHEMA_VERSION = 1


def get_cache_version(tags: TagsConfig | None = None) -> str:
    """Return the version of the cached tag data.

    Includes the tinytag version so upgrading the parser invalidates cached
    tags, which may otherwise keep old values until files are modified. Also
    includes tag filtering settings, because changing them changes which tags
    are stored.
    """
    if tags is None:
        tags = TagsConfig()
    ignored = ",".join(sorted(tags.ignore))
    return f"{CACHE_SCHEMA_VERSION}:{tinytag.__version__}:{tags.max_size}:{ignored}"


def get_db_path(override: Path | None = None) -> Path:
    """Return the DB path, using override if given."""
    if override is not None:
        return override
    db_path = xdg_cache_home() / "genplis" / DB_NAME
    return db_path


def adapt_datetime_epoch(val: datetime) -> int:
    """Adapt datetime to Unix timestamp."""
    return int(val.timestamp())


def convert_timestamp(val: bytes) -> datetime:
    """Convert Unix epoch timestamp to datetime object."""
    return datetime.fromtimestamp(int(val))


def setup_database_connection(
    conn_path: Path,
) -> tuple[sqlite3.Connection, sqlite3.Cursor]:
    sqlite3.register_adapter(datetime, adapt_datetime_epoch)
    sqlite3.register_converter("timestamp", convert_timestamp)
    conn = sqlite3.connect(conn_path)
    cursor = conn.cursor()
    return conn, cursor


def create_files_table(
    cursor: sqlite3.Cursor, cache_version: str | None = None
) -> None:
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS cache_meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
    """)

    if cache_version is None:
        cache_version = get_cache_version()
    row = cursor.execute(
        "SELECT value FROM cache_meta WHERE key = 'tag_version'"
    ).fetchone()
    if row is None or row[0] != cache_version:
        # The cache is disposable, so start over if the parser or the tag
        # schema changed.
        cursor.execute("DROP TABLE IF EXISTS files")
        cursor.execute(
            """INSERT INTO cache_meta(key, value)
            VALUES ('tag_version', ?)
            ON CONFLICT(key) DO UPDATE SET value=excluded.value
            """,
            (cache_version,),
        )

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS files (
            path TEXT PRIMARY KEY,
            last_modified TIMESTAMP,
            tags JSONB
        )
    """)


def is_cache_valid(cursor: sqlite3.Cursor, file_path: Path) -> bool | None:
    """True if the file is cached in DB and the entry is not stale.

    False if file_path is in DB but the timestamp of the file is
    more recent (i.e. cache is stale and shouldn't be used).

    None if file_path is not in DB.

    Cached tags can then be retrieved with get_cached_tags.

    """
    abs_file_path = file_path.absolute()
    file_last_modified = get_last_modified(file_path)

    # Check if the file path already exists in the database
    cursor.execute(
        """SELECT last_modified FROM files WHERE path = ?""",
        (str(abs_file_path),),
    )
    row = cursor.fetchone()
    if row is None:
        return None

    cached_timestamp = row[0]  # int, UNIX timestamp
    return file_last_modified <= cached_timestamp


def cache_tags_for_file(cursor: sqlite3.Cursor, file_path: Path, tags: Tags) -> None:
    """Save given tags for a music file in DB.

    Caller is responsible for calling commit on the DB connection.

    """
    file_path = file_path.absolute()
    last_modified = get_last_modified(file_path)
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


def get_cached_tags(cursor: sqlite3.Cursor, file_path: Path) -> Tags:
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
        return cast(Tags, json.loads(row[0]))

    raise GenplisDBError(f"{file_path} not found on DB")
