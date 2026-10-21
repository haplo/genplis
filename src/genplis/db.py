import json
import os
import sqlite3
from enum import StrEnum
from pathlib import Path
from typing import cast

import tinytag
from xdg_base_dirs import xdg_cache_home

from .config import TagsConfig
from .exceptions import GenplisDBError
from .files import get_last_modified
from .json import GenplisJSONEncoder
from .types import Tags, Verbosity

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


def vacuum_database(conn: sqlite3.Connection) -> None:
    """Rebuild the database file to reclaim space after deletions."""
    conn.execute("VACUUM")


def setup_database_connection(
    conn_path: Path,
) -> tuple[sqlite3.Connection, sqlite3.Cursor]:
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
    """Return the normalized absolute path string used as the files key.

    ``.`` and ``..`` components are collapsed, so different spellings of the
    same path share one cache row. Symlinks are not resolved, so a symlinked
    path and its target remain distinct entries.
    """
    return os.path.normpath(file_path.absolute())


def get_cache_status(
    cursor: sqlite3.Cursor,
    file_path: Path,
    last_modified: int | None = None,
) -> CacheStatus:
    """Check whether file_path is cached in DB and whether the entry is fresh.

    Returns CacheStatus.MISS if file_path is not in DB, CacheStatus.STALE if
    the file is more recent than the cached entry (so the cache shouldn't be
    used), and CacheStatus.HIT if the cached entry is up to date.

    Pass ``last_modified`` when the caller already read the file's timestamp,
    so it is not read again.

    Cached tags can then be retrieved with get_cached_tags.

    """
    db_key = get_db_key(file_path)
    if last_modified is None:
        last_modified = get_last_modified(file_path)

    # Check if the file path already exists in the database
    cursor.execute(
        """SELECT last_modified FROM files WHERE path = ?""",
        (db_key,),
    )
    row = cursor.fetchone()
    if row is None:
        return CacheStatus.MISS

    cached_timestamp = row[0]  # int, UNIX timestamp
    if last_modified <= cached_timestamp:
        return CacheStatus.HIT
    return CacheStatus.STALE


def cache_tags_for_file(
    cursor: sqlite3.Cursor,
    file_path: Path,
    tags: Tags,
    *,
    last_modified: int | None = None,
    verbosity: Verbosity = Verbosity.NORMAL,
) -> None:
    """Save given tags for a music file in DB.

    Pass ``last_modified`` to store the timestamp captured before parsing, so
    a file modified during parsing is detected as stale on the next run.

    Caller is responsible for calling commit on the DB connection.

    """
    file_path = file_path.absolute()
    if last_modified is None:
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
    if verbosity.shows_normal_output:
        print(f"Updated cache for file: {file_path}")


class WriteBatch:
    """Own the commit cadence for cache writes.

    ``every`` is the number of writes between commits. A value of 1 commits
    after each write, matching the historical behaviour. A value of 0 commits
    only when :meth:`flush` is called. Cache hits and unsupported files do not
    advance the counter because they do not call :meth:`store`.

    """

    def __init__(self, conn: sqlite3.Connection, every: int = 1) -> None:
        self._conn = conn
        self._every = every
        self._pending = 0

    def store(
        self,
        cursor: sqlite3.Cursor,
        file_path: Path,
        tags: Tags,
        *,
        last_modified: int,
        verbosity: Verbosity = Verbosity.NORMAL,
    ) -> None:
        """Write one cache row and commit when the batch is full."""
        cache_tags_for_file(
            cursor,
            file_path,
            tags,
            last_modified=last_modified,
            verbosity=verbosity,
        )
        self._pending += 1
        if self._every and self._pending >= self._every:
            self.flush()

    def flush(self) -> None:
        """Commit any pending writes and reset the counter."""
        self._conn.commit()
        self._pending = 0


def remove_missing_files(
    cursor: sqlite3.Cursor, root: Path | None = None
) -> list[Path]:
    """Remove cached entries whose files no longer exist.

    When root is given, only entries at or below root are considered, so
    cleaning one collection does not remove entries from another. Returns the
    removed paths.

    Caller is responsible for committing to the DB.

    """
    scope = Path(get_db_key(root)) if root is not None else None

    cursor.execute("SELECT path FROM files")
    missing: list[Path] = []
    for (db_key,) in cursor:
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
        try:
            tags = json.loads(row[0])
        except (TypeError, json.JSONDecodeError) as exc:
            raise GenplisDBError(f"{file_path}: invalid cached tag data") from exc
        if not isinstance(tags, dict):
            raise GenplisDBError(f"{file_path}: invalid cached tag data")
        return cast(Tags, tags)

    raise GenplisDBError(f"{file_path} not found on DB")
