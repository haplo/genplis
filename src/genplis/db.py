import json
import sqlite3
from datetime import datetime
from enum import StrEnum
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
CACHE_SCHEMA_VERSION = 2


class CacheStatus(StrEnum):
    """State of the tag cache for a file, as found before processing it."""

    MISS = "miss"  # file has no entry in the cache
    STALE = "stale"  # file is cached, but it changed since it was cached
    HIT = "hit"  # file is cached and the cache is up to date


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


def vacuum_database(conn: sqlite3.Connection) -> None:
    """Rebuild the database file to reclaim space after deletions."""
    conn.execute("VACUUM")


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


def get_db_key(file_path: Path) -> str:
    """Return the canonical path string used as the key in the files table.

    Paths are stored as absolute paths, so every DB operation must use this
    helper to look up the same key regardless of how the path was given.
    """
    return str(file_path.absolute())


def get_cache_status(cursor: sqlite3.Cursor, file_path: Path) -> CacheStatus:
    """Check whether file_path is cached in DB and whether the entry is fresh.

    Returns CacheStatus.MISS if file_path is not in DB, CacheStatus.STALE if
    the file is more recent than the cached entry (so the cache shouldn't be
    used), and CacheStatus.HIT if the cached entry is up to date.

    Cached tags can then be retrieved with get_cached_tags.

    """
    db_key = get_db_key(file_path)
    file_last_modified = get_last_modified(file_path)

    # Check if the file path already exists in the database
    cursor.execute(
        """SELECT last_modified FROM files WHERE path = ?""",
        (db_key,),
    )
    row = cursor.fetchone()
    if row is None:
        return CacheStatus.MISS

    cached_timestamp = row[0]  # int, UNIX timestamp
    if file_last_modified <= cached_timestamp:
        return CacheStatus.HIT
    return CacheStatus.STALE


def cache_tags_for_file(cursor: sqlite3.Cursor, file_path: Path, tags: Tags) -> None:
    """Save given tags for a music file in DB.

    Caller is responsible for calling commit on the DB connection.

    """
    file_path = file_path.absolute()
    last_modified = get_last_modified(file_path)
    json_tags = json.dumps(tags, cls=GenplisJSONEncoder)
    db_key = get_db_key(file_path)

    # UPSERT: https://www.sqlite.org/lang_upsert.html
    # Attempt to insert entry on DB, if path already exists then update tags and
    # last_modified
    cursor.execute(
        """INSERT INTO files(path, last_modified, tags)
        VALUES (?, ?, ?)
        ON CONFLICT(path) DO
        UPDATE SET last_modified=?, tags=?
        """,
        (db_key, last_modified, json_tags, last_modified, json_tags),
    )
    print(f"Updated cache for file: {file_path}")


def remove_missing_files(
    cursor: sqlite3.Cursor, root: Path | None = None
) -> list[Path]:
    """Remove cached entries whose files no longer exist.

    When root is given, only entries at or below root are considered, so
    cleaning one collection does not remove entries from another. Returns the
    removed paths.

    Caller is responsible for committing to the DB.

    """
    scope = root.absolute() if root is not None else None

    cursor.execute("SELECT path FROM files")
    missing: list[Path] = []
    for (db_key,) in cursor.fetchall():
        file_path = Path(db_key)
        if scope is not None and not file_path.is_relative_to(scope):
            continue
        if not file_path.exists():
            missing.append(file_path)

    if missing:
        cursor.executemany(
            "DELETE FROM files WHERE path = ?",
            ((get_db_key(file_path),) for file_path in missing),
        )
    return missing


def get_cached_tags(cursor: sqlite3.Cursor, file_path: Path) -> Tags:
    """Retrieve cached tags for the given file.

    Should have previously called get_cache_status to check that the file is
    actually cached and that the data is not stale.

    Will raise GenplisDBError if file_path is not actually on DB.

    """
    cursor.execute(
        """SELECT tags FROM files WHERE path = ?""",
        (get_db_key(file_path),),
    )
    row = cursor.fetchone()
    if row:
        return cast(Tags, json.loads(row[0]))

    raise GenplisDBError(f"{file_path} not found on DB")
