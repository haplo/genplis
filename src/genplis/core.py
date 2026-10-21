import argparse
import os
import re
import sqlite3
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from timeit import default_timer as timer

import psutil

from . import db
from .config import Config, load_config
from .exceptions import GenplisConfigError, GenplisError
from .executors import (
    ParseItem,
    ProcessExecutor,
    auto_workers,
    make_executor,
)
from .m3u import create_m3u
from .m3ug import RuleNode, get_rating, parse_m3ug
from .tags import AUDIO_PROPERTY_TAGS, get_audio_property_tags, get_tags
from .types import Tags, TagValue, Verbosity

# User-facing description of each cache state.
CACHE_STATUS_MESSAGES = {
    db.CacheStatus.MISS: "not present",
    db.CacheStatus.STALE: "stale",
    db.CacheStatus.HIT: "valid",
}

# Commit cache writes every N rows during a directory scan. Benchmarked on a
# 50k-file cold scan: 128 was within 0.7% of the best median and far ahead of
# committing after every write.
COMMIT_EVERY = 128


@dataclass(frozen=True, slots=True)
class Args:
    path: Path | None
    exclude: tuple[re.Pattern[str], ...]
    verbosity: Verbosity
    overwrite: bool
    db_path: Path
    config: Config
    include_source: bool = True
    clean: bool = False
    config_disabled: bool = False
    jobs: int = 1


@dataclass(frozen=True, slots=True)
class CleanStats:
    """Result of a cache cleaning operation."""

    removed: tuple[Path, ...]
    size_before: int
    size_after: int

    @property
    def bytes_saved(self) -> int:
        """Return how many bytes the database shrank."""
        return max(0, self.size_before - self.size_after)


_SIZE_UNITS = ("B", "KiB", "MiB", "GiB", "TiB")


def format_size(size: int) -> str:
    """Format a byte count using binary units."""
    value = float(size)
    for unit in _SIZE_UNITS[:-1]:
        if value < 1024:
            return f"{int(value)} B" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} {_SIZE_UNITS[-1]}"


def regex_type(arg_value: str) -> re.Pattern[str]:
    """"""
    return re.compile(arg_value)


def non_negative_int(arg_value: str) -> int:
    """Parse a command-line integer that must be zero or greater."""
    try:
        value = int(arg_value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"expected an integer, got {arg_value!r}"
        ) from exc
    if value < 0:
        raise argparse.ArgumentTypeError(f"must be at least 0, got {value}")
    return value


def setup_argparse() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate music playlists from your own filters."
    )
    parser.add_argument(
        "path",
        nargs="?",
        type=Path,
        help=(
            "Path to parse (directory with music collection or individual file). "
            "Defaults to [collection] path from the config file."
        ),
        metavar="PATH",
    )
    parser.add_argument(
        "-e",
        "--exclude",
        help=(
            "Exclude files matching this regex. Replaces the config file's "
            "exclude list when used."
        ),
        action="append",
        default=None,
        type=regex_type,
    )

    config_group = parser.add_mutually_exclusive_group()
    config_group.add_argument(
        "--config",
        help="Read settings from this file instead of the XDG default",
        type=Path,
        metavar="FILE",
    )
    config_group.add_argument(
        "--no-config",
        help="Do not read any configuration file",
        action="store_true",
    )

    parser.add_argument(
        "-v",
        "--verbose",
        help="Print verbose diagnostics",
        action=argparse.BooleanOptionalAction,
        default=None,
    )
    parser.add_argument(
        "-q",
        "--quiet",
        help=(
            "Reduce output. Repeat (-qq) to print nothing except errors. "
            "Cannot be combined with --verbose."
        ),
        action="count",
        default=0,
    )
    parser.add_argument(
        "--db",
        help="Use this database file instead of the XDG cache default",
        type=Path,
        metavar="PATH",
    )
    parser.add_argument(
        "-j",
        "--jobs",
        help=(
            "Parse cache misses with N worker processes "
            "(0 = one per CPU, capped at 8; 1 = no pool)"
        ),
        type=non_negative_int,
        default=None,
        metavar="N",
    )
    parser.add_argument(
        "--clean",
        help=(
            "Remove cache entries for files that no longer exist. With PATH, "
            "process it normally first and clean only entries under it; "
            "without PATH, clean the whole database."
        ),
        action="store_true",
    )
    parser.add_argument(
        "--overwrite",
        help="Overwrite existing generated playlists",
        action=argparse.BooleanOptionalAction,
        default=None,
    )
    parser.add_argument(
        "--include-source",
        help="Embed the M3UG filter source as comments in generated playlists",
        action=argparse.BooleanOptionalAction,
        default=None,
    )
    return parser


def _resolve_verbosity(args: argparse.Namespace, config: Config) -> Verbosity:
    """Combine command-line and config output settings.

    Command-line verbosity flags override the config file. A quiet flag and a
    verbose flag from the same source are rejected before this is called.
    """
    if args.quiet:
        return Verbosity.REALLY_QUIET if args.quiet >= 2 else Verbosity.QUIET
    if args.verbose:
        return Verbosity.VERBOSE
    if config.general.quiet:
        return Verbosity.QUIET
    if args.verbose is False:
        return Verbosity.NORMAL
    if config.general.verbose:
        return Verbosity.VERBOSE
    return Verbosity.NORMAL


def _resolve_jobs(args: argparse.Namespace, config: Config) -> int:
    """Resolve the worker count from the CLI, config, or CPU count."""
    raw_jobs = args.jobs if args.jobs is not None else config.general.jobs
    if raw_jobs < 0:
        raise GenplisConfigError(f"jobs must be at least 0, got {raw_jobs}")
    return auto_workers() if raw_jobs == 0 else raw_jobs


def resolve_args(args: argparse.Namespace, config: Config) -> Args:
    """Combine command-line arguments with configuration file values.

    Command-line values take precedence. Excludes are special: when any
    --exclude option is present, it replaces the config file's exclude list.
    """
    if args.path is not None:
        path = args.path
    elif args.clean:
        # Cleaning without a CLI path removes entries from the whole database,
        # even when a collection path is configured.
        path = None
    elif config.collection.path is not None:
        path = config.collection.path
    else:
        raise GenplisConfigError(
            "PATH is required unless [collection] path is set in the config file"
        )

    exclude = (
        tuple(args.exclude) if args.exclude is not None else config.collection.exclude
    )
    verbosity = _resolve_verbosity(args, config)
    overwrite = (
        args.overwrite if args.overwrite is not None else config.output.overwrite
    )
    include_source = (
        args.include_source
        if args.include_source is not None
        else config.output.include_source
    )
    raw_db_path = args.db if args.db is not None else config.database.path
    if raw_db_path is not None:
        raw_db_path = raw_db_path.expanduser()
    db_path = db.get_db_path(raw_db_path)

    return Args(
        path=path,
        exclude=exclude,
        verbosity=verbosity,
        overwrite=overwrite,
        db_path=db_path,
        config=config,
        include_source=include_source,
        clean=args.clean,
        config_disabled=args.no_config,
        jobs=_resolve_jobs(args, config),
    )


def is_excluded(path: Path, args: Args, *, is_dir: bool = False) -> bool:
    """Return whether any exclude pattern matches the given path.

    Directory paths are also matched with a trailing separator so that
    patterns written for folders (e.g. ``/@eaDir/``) match the folder itself
    and not just the files inside it.
    """
    text = str(path)
    candidates = (text, text + os.sep) if is_dir else (text,)
    return any(
        pattern.search(candidate)
        for pattern in args.exclude
        for candidate in candidates
    )


def get_calculated_tags(tags: Mapping[str, TagValue]) -> Tags:
    """Return calculated tags for display.

    Calculated tag names are prefixed with ``*`` to distinguish them from
    tags that are embedded in the original file.
    """
    calculated = get_audio_property_tags(tags)
    rating = get_rating(tags)
    if rating is not None:
        calculated["*rating"] = rating
    return calculated


def process_path(conn: sqlite3.Connection, cursor: sqlite3.Cursor, args: Args) -> None:
    """Process an arbitrary path through genplis.

    It will use process_file or process_directory depending on the type of the path.

    """
    path = args.path
    if path is None:
        raise GenplisError("Attempted to process a path but none was given")

    if path.is_dir():
        process_directory(conn, cursor, path, args)
    elif path.is_file():
        tags, filters, cache_status = process_file(conn, cursor, path, args)
        if tags is not None and args.verbosity.shows_normal_output:
            print(f"{path} detected as music file")
            print(f"Cache status: {CACHE_STATUS_MESSAGES[cache_status]}")

            print("Parsed tags:")
            display_tags = {
                key: value
                for key, value in tags.items()
                if key not in AUDIO_PROPERTY_TAGS
            }
            display_tags.update(get_calculated_tags(tags))
            for key, value in sorted(display_tags.items(), key=lambda t: t[0]):
                print(f"    {key} = {value}")
        if (
            filters or path.suffix.lower() == ".m3ug"
        ) and args.verbosity.shows_normal_output:
            print(f"{path} detected as M3UG file")
            print("Parsed filters:")
            for f in filters:
                print(f"    {f}")
        if is_excluded(path, args) and args.verbosity.shows_normal_output:
            print("WARNING: This file is excluded by current configuration.")
    else:
        print(
            f"{path} must be either a directory or a file. Exiting...",
            file=sys.stderr,
        )
        sys.exit(1)


def process_directory(
    conn: sqlite3.Connection,
    cursor: sqlite3.Cursor,
    directory: Path,
    args: Args,
) -> tuple[dict[Path, Tags], dict[Path, list[RuleNode]]]:
    """Traverse the directory and process all files.

    See process_file for how each file is handled.

    Returns a tuple in the form (all_tags, all_filters), both keyed by file
    path: all_tags maps music files to their tags, all_filters maps M3UG
    files to their parsed rules. A playlist is generated for each M3UG file
    that matches at least one song. Unless include_source is disabled, the
    original M3UG text is embedded as comments at the top of the playlist.
    Folders that match an exclude pattern are skipped entirely.

    """
    if not directory.is_dir():
        raise GenplisError(
            f"Attempted to process {directory} as a directory but it's not a directory"
        )

    start_time = timer()

    all_filters: dict[Path, list[RuleNode]] = {}
    tags_by_path: dict[Path, Tags | None] = {}
    pending: list[ParseItem] = []
    batch = db.WriteBatch(conn, every=COMMIT_EVERY)
    try:
        for current_dir, dirnames, filenames in directory.walk():
            current = Path(current_dir)

            kept_dirs: list[str] = []
            for name in dirnames:
                folder = current / name
                if is_excluded(folder, args, is_dir=True):
                    if args.verbosity.is_verbose:
                        print(f"Skipping {folder} because of exclude pattern.")
                    continue
                kept_dirs.append(name)
            dirnames[:] = kept_dirs

            for name in filenames:
                file = current / name
                if is_excluded(file, args):
                    if args.verbosity.is_verbose:
                        print(f"Skipping {file} because of exclude pattern.")
                    continue

                # Path.walk reports symlinks to directories among the filenames.
                if not file.is_file():
                    continue

                if args.jobs <= 1:
                    tags, filters, _ = process_file(
                        conn, cursor, file, args, batch=batch
                    )
                    if tags is not None:
                        tags_by_path[file] = tags
                    if filters or file.suffix.lower() == ".m3ug":
                        all_filters[file] = filters
                    continue

                if file.suffix.lower() == ".m3ug":
                    _, filters, _ = process_file(conn, cursor, file, args)
                    all_filters[file] = filters
                    continue

                # Keep every audio path in walk order; hits replace the
                # placeholder now, misses replace it when their result lands.
                tags_by_path[file] = None
                last_modified = db.get_last_modified(file)
                cache_status = db.get_cache_status(cursor, file, last_modified)
                if cache_status is db.CacheStatus.HIT:
                    tags_by_path[file] = db.get_cached_tags(cursor, file)
                else:
                    pending.append(ParseItem(path=file, last_modified=last_modified))

        if args.jobs > 1:
            executor = make_executor(args.jobs, len(pending), args.config.tags)
            if isinstance(executor, ProcessExecutor) and args.verbosity.is_verbose:
                print(f"Parsing with {executor.workers} worker processes")
            try:
                for result in executor.parse(pending):
                    if args.verbosity.is_verbose:
                        for message in result.messages:
                            print(message)
                    if result.tags is None:
                        continue
                    batch.store(
                        cursor,
                        result.item.path,
                        result.tags,
                        last_modified=result.item.last_modified,
                        verbosity=args.verbosity,
                    )
                    tags_by_path[result.item.path] = result.tags
            except BaseException:
                executor.close(cancel=True)
                raise
            else:
                executor.close()
    finally:
        batch.flush()

    all_tags = {path: tags for path, tags in tags_by_path.items() if tags is not None}

    # Apply each filter to all songs to generate playlists
    for filter_file, rules in all_filters.items():
        files = filter_songs(all_tags, filter_file, rules, args.verbosity)
        if args.verbosity.shows_progress:
            print(f"Filter file {filter_file} matched {len(files)} songs")
        if len(files) > 0:
            playlist_file = filter_file.with_suffix(".m3u")
            if args.verbosity.shows_progress:
                print(f"Creating playlist {playlist_file}")
            comments: list[str] = []
            if args.include_source:
                source = filter_file.read_text(encoding="utf-8-sig")
                comments = [
                    f'Generated by genplis from "{filter_file.name}"',
                    "",
                    *source.splitlines(),
                ]
            create_m3u(
                playlist_file,
                files,
                comments=comments,
                overwrite=args.overwrite,
                verbosity=args.verbosity,
            )

    end_time = timer()
    process_time = end_time - start_time
    used_memory = psutil.Process().memory_info().rss / (1024 * 1024)
    if args.verbosity.shows_normal_output:
        print(f"Processed {len(all_tags)} files in {process_time:.3f} seconds")
        print(f"Total RAM usage: {used_memory} MiB")

    return all_tags, all_filters


def process_file(
    conn: sqlite3.Connection,
    cursor: sqlite3.Cursor,
    file: Path,
    args: Args,
    *,
    batch: db.WriteBatch | None = None,
) -> tuple[Tags | None, list[RuleNode], db.CacheStatus]:
    """Process a single file.

    Returns a tuple in the form (tags, filters, cache_status), where tags is a
    dictionary, filters is always a list (empty for non-M3UG files) and
    cache_status is the state of the tag cache when the file was found.

    When ``batch`` is given, cache writes go through it instead of committing
    immediately. ``None`` preserves the single-file behaviour of committing
    each write before returning.

    ``tags`` is ``None`` when the file is not a supported music file. An empty
    dictionary means the file is supported music but has no usable tags (for
    example because every tag is ignored).

    If it's an M3UG file, parse it as such and return its filters.
    See m3ug module.

    Music files are parsed with tinytag, detected tags are returned as a
    dictionary. Up-to-date cached tags are reused instead of parsing again;
    M3UG files are never cached, so they always report CacheStatus.MISS.

    """
    if not file.is_file():
        raise GenplisError(f"Attempted to process {file} as a file but it's not a file")

    if file.suffix.lower() == ".m3ug":
        content = file.read_text(encoding="utf-8-sig")
        rules = parse_m3ug(content, str(file), args.verbosity)
        return None, rules, db.CacheStatus.MISS

    last_modified = db.get_last_modified(file)
    cache_status = db.get_cache_status(cursor, file, last_modified)
    if cache_status is db.CacheStatus.HIT:
        # reuse cached tags from DB instead of parsing them again
        cached_tags = db.get_cached_tags(cursor, file)
        return cached_tags, [], cache_status

    tags = get_tags(
        file,
        args.verbosity,
        max_size=args.config.tags.max_size,
        ignore=args.config.tags.ignore,
    )
    if tags is None:
        return None, [], cache_status
    # Cache supported files even when every tag was filtered out, so an empty
    # tag dictionary is not confused with "not a music file" next time.
    if batch is not None:
        batch.store(
            cursor,
            file,
            tags,
            last_modified=last_modified,
            verbosity=args.verbosity,
        )
    else:
        db.cache_tags_for_file(
            cursor,
            file,
            tags,
            last_modified=last_modified,
            verbosity=args.verbosity,
        )
        conn.commit()
    return tags, [], cache_status


def filter_songs(
    files_and_tags: Mapping[Path, Tags],
    filter_file: Path,
    rules: Sequence[RuleNode],
    verbosity: Verbosity = Verbosity.NORMAL,
) -> list[Path]:
    if verbosity.is_verbose:
        print(f"\nFiltering songs and generating playlist for {filter_file}")

    filtered_songs: list[Path] = []
    for file, tags in files_and_tags.items():
        for rule in rules:
            if not rule.apply(tags):
                break
        else:
            # only executed if all rules pass
            filtered_songs.append(file)

    if verbosity.is_verbose:
        print(f"Files that match the filter {filter_file}:")
        for song in filtered_songs:
            print(f"  {song}")

    return filtered_songs


def clean_database(
    conn: sqlite3.Connection,
    cursor: sqlite3.Cursor,
    root: Path | None,
    db_path: Path,
    verbosity: Verbosity = Verbosity.NORMAL,
) -> CleanStats:
    """Remove cache entries for missing files and reclaim their space.

    When root is given, only entries under root are considered. VACUUM runs
    only when something was removed, so the reported size reduction is the
    actual change on disk.

    """
    conn.commit()
    size_before = db_path.stat().st_size

    removed = db.remove_missing_files(cursor, root)
    conn.commit()
    if removed:
        db.vacuum_database(conn)
    size_after = db_path.stat().st_size

    if verbosity.is_verbose:
        for path in removed:
            print(f"Removed stale cache entry for {path}")

    stats = CleanStats(
        removed=tuple(removed),
        size_before=size_before,
        size_after=size_after,
    )
    entry_word = "entry" if len(removed) == 1 else "entries"
    if verbosity.shows_normal_output:
        print(f"Removed {len(removed)} stale {entry_word} from the cache database.")
        print(
            "Database size: "
            f"{format_size(size_before)} -> {format_size(size_after)} "
            f"({format_size(stats.bytes_saved)} saved)."
        )
    return stats


def _run(args: Args) -> None:
    """Run genplis with resolved arguments."""
    if args.verbosity.is_verbose:
        if args.config_disabled:
            print("Configuration disabled with --no-config")
        elif args.config.source is not None:
            print(f"Using config file {args.config.source}")
        else:
            print("No config file found; using defaults")
        print(f"Using {args.db_path} for genplis DB")

    if args.path is None and not args.db_path.exists():
        if args.verbosity.shows_normal_output:
            print("Database does not exist; nothing to clean.")
        return

    try:
        args.db_path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise GenplisError(
            f"Cannot create database directory {args.db_path.parent}: {exc}"
        ) from exc

    conn, cursor = db.setup_database_connection(args.db_path)
    try:
        with conn:
            # Create a DB for caching results if it doesn't exist
            db.create_files_table(cursor, db.get_cache_version(args.config.tags))
            conn.commit()

            if args.path is not None:
                process_path(conn, cursor, args)
            if args.clean:
                clean_database(
                    conn,
                    cursor,
                    args.path,
                    args.db_path,
                    verbosity=args.verbosity,
                )
    finally:
        conn.close()


def main() -> None:
    # Set up argparse
    parser = setup_argparse()
    raw_args = parser.parse_args()

    if raw_args.quiet and raw_args.verbose:
        parser.error("--quiet cannot be combined with --verbose")

    try:
        config = Config() if raw_args.no_config else load_config(raw_args.config)
        args = resolve_args(raw_args, config)
    except GenplisConfigError as exc:
        parser.exit(1, f"genplis: error: {exc}\n")

    try:
        _run(args)
    except GenplisError as exc:
        print(f"genplis: error: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
