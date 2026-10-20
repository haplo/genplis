import argparse
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
from .m3u import create_m3u
from .m3ug import RuleNode, parse_m3ug
from .tags import get_tags
from .types import Tags

# User-facing description of each cache state.
CACHE_STATUS_MESSAGES = {
    db.CacheStatus.MISS: "not present",
    db.CacheStatus.STALE: "stale",
    db.CacheStatus.HIT: "valid",
}


@dataclass(frozen=True, slots=True)
class Args:
    path: Path
    exclude: tuple[re.Pattern[str], ...]
    verbose: bool
    overwrite: bool
    db_path: Path
    config: Config


def regex_type(arg_value: str) -> re.Pattern[str]:
    """"""
    return re.compile(arg_value)


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
        "--db",
        help="Use this database file instead of the XDG cache default",
        type=Path,
        metavar="PATH",
    )
    parser.add_argument(
        "--overwrite",
        help="Overwrite existing generated playlists",
        action=argparse.BooleanOptionalAction,
        default=None,
    )
    return parser


def resolve_args(args: argparse.Namespace, config: Config) -> Args:
    """Combine command-line arguments with configuration file values.

    Command-line values take precedence. Excludes are special: when any
    --exclude option is present, it replaces the config file's exclude list.
    """
    if args.path is not None:
        path = args.path
    elif config.collection.path is not None:
        path = config.collection.path
    else:
        raise GenplisConfigError(
            "PATH is required unless [collection] path is set in the config file"
        )

    exclude = (
        tuple(args.exclude) if args.exclude is not None else config.collection.exclude
    )
    verbose = args.verbose if args.verbose is not None else config.general.verbose
    overwrite = (
        args.overwrite if args.overwrite is not None else config.output.overwrite
    )
    db_path = db.get_db_path(args.db if args.db is not None else config.database.path)

    return Args(
        path=path,
        exclude=exclude,
        verbose=verbose,
        overwrite=overwrite,
        db_path=db_path,
        config=config,
    )


def is_excluded(path: Path, args: Args) -> bool:
    for pattern in args.exclude:
        if pattern.search(str(path)):
            return True
    return False


def process_path(conn: sqlite3.Connection, cursor: sqlite3.Cursor, args: Args) -> None:
    """Process an arbitrary path through genplis.

    It will use process_file or process_directory depending on the type of the path.

    """
    if args.path.is_dir():
        process_directory(conn, cursor, args.path, args)
    elif args.path.is_file():
        tags, filters, cache_status = process_file(conn, cursor, args.path, args)
        if tags:
            print(f"{args.path} detected as music file")
            print(f"Cache status: {CACHE_STATUS_MESSAGES[cache_status]}")

            print("Parsed tags:")
            for key, value in sorted(tags.items(), key=lambda t: t[0]):
                print(f"    {key} = {value}")
        if filters:
            print(f"{args.path} detected as M3UG file")
            print("Parsed filters:")
            for f in filters:
                print(f"    {f}")
        if is_excluded(args.path, args):
            print("WARNING: This file is excluded by current configuration.")
    else:
        print(f"{args.path} must be either a directory or a file. Exiting...")
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
    that matches at least one song.

    """
    if not directory.is_dir():
        raise GenplisError(
            f"Attempted to process {directory} as a directory but it's not a directory"
        )

    start_time = timer()

    all_tags: dict[Path, Tags] = {}
    all_filters: dict[Path, list[RuleNode]] = {}
    for file in directory.rglob("*"):
        if is_excluded(file, args):
            if args.verbose:
                print(f"Skipping {file} because of exclude pattern.")
            continue

        if file.is_file():
            tags, filters, _ = process_file(conn, cursor, file, args)
            if tags:
                all_tags[file] = tags
            if filters:
                all_filters[file] = filters

    # Apply each filter to all songs to generate playlists
    for filter_file, rules in all_filters.items():
        files = filter_songs(all_tags, filter_file, rules, args.verbose)
        print(f"Filter file {filter_file} matched {len(files)} songs")
        if len(files) > 0:
            playlist_file = filter_file.with_suffix(".m3u")
            print(f"Creating playlist {playlist_file}")
            create_m3u(
                playlist_file,
                files,
                overwrite=args.overwrite,
            )

    end_time = timer()
    process_time = end_time - start_time
    used_memory = psutil.Process().memory_info().rss / (1024 * 1024)
    print(f"Processed {len(all_tags)} files in {process_time:.3f} seconds")
    print(f"Total RAM usage: {used_memory} MiB")

    return all_tags, all_filters


def process_file(
    conn: sqlite3.Connection, cursor: sqlite3.Cursor, file: Path, args: Args
) -> tuple[Tags, list[RuleNode], db.CacheStatus]:
    """Process a single file.

    Returns a tuple in the form (tags, filters, cache_status), where tags is a
    dictionary, filters is always a list (empty for non-M3UG files) and
    cache_status is the state of the tag cache when the file was found.

    If it's an M3UG file, parse it as such and return its filters.
    See m3ug module.

    Music files are parsed with tinytag, detected tags are returned as a
    dictionary. Up-to-date cached tags are reused instead of parsing again;
    M3UG files are never cached, so they always report CacheStatus.MISS.

    """
    if not file.is_file():
        raise GenplisError(f"Attempted to process {file} as a file but it's not a file")

    if file.suffix.lower() == ".m3ug":
        content = file.read_text()
        rules = parse_m3ug(content, str(file), args.verbose)
        return {}, rules, db.CacheStatus.MISS

    cache_status = db.get_cache_status(cursor, file)
    if cache_status is db.CacheStatus.HIT:
        # reuse cached tags from DB instead of parsing them again
        # empty tags mean the file is not a supported music file and
        # should be ignored
        cached_tags = db.get_cached_tags(cursor, file)
        return cached_tags, [], cache_status

    tags = get_tags(
        file,
        args.verbose,
        max_size=args.config.tags.max_size,
        ignore=args.config.tags.ignore,
    )
    if tags:
        db.cache_tags_for_file(cursor, file, tags)
        conn.commit()
    return tags or {}, [], cache_status


def filter_songs(
    files_and_tags: Mapping[Path, Tags],
    filter_file: Path,
    rules: Sequence[RuleNode],
    verbose: bool = False,
) -> list[Path]:
    if verbose:
        print(f"\nFiltering songs and generating playlist for {filter_file}")

    filtered_songs: list[Path] = []
    for file, tags in files_and_tags.items():
        for rule in rules:
            if not rule.apply(tags):
                break
        else:
            # only executed if all rules pass
            filtered_songs.append(file)

    if verbose:
        print(f"Files that match the filter {filter_file}:")
        for song in filtered_songs:
            print(f"  {song}")

    return filtered_songs


def main() -> None:
    # Set up argparse
    parser = setup_argparse()
    raw_args = parser.parse_args()

    try:
        config = Config() if raw_args.no_config else load_config(raw_args.config)
        args = resolve_args(raw_args, config)
    except GenplisConfigError as exc:
        parser.exit(1, f"genplis: error: {exc}\n")

    if args.verbose:
        if config.source is not None:
            print(f"Using config file {config.source}")
        else:
            print("No config file found; using defaults")
        print(f"Using {args.db_path} for genplis DB")

    try:
        args.db_path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise GenplisError(
            f"Cannot create database directory {args.db_path.parent}: {exc}"
        ) from exc

    with sqlite3.connect(args.db_path) as conn:
        cursor = conn.cursor()

        # Create a DB for caching results if it doesn't exist
        db.create_files_table(cursor, db.get_cache_version(config.tags))
        conn.commit()

        process_path(conn, cursor, args)


if __name__ == "__main__":
    main()
