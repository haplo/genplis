import argparse
import re
import sqlite3
import sys
from pathlib import Path
from timeit import default_timer as timer

import psutil

from . import db
from .exceptions import GenplisError
from .m3u import create_m3u
from .m3ug import parse_m3ug
from .tags import get_tags


def regex_type(arg_value):
    """"""
    return re.compile(arg_value)


def setup_argparse():
    parser = argparse.ArgumentParser(
        description="Generate music playlists from your own filters."
    )
    parser.add_argument(
        "path",
        type=Path,
        help="Path to parse (directory with music collection or individual file)",
        metavar="PATH",
    )
    parser.add_argument(
        "-e",
        "--exclude",
        help="Exclude files matching this regex",
        action="append",
        type=regex_type,
    )
    parser.add_argument(
        "-v",
        "--verbose",
        help="Print verbose diagnostics",
        action="store_true",
    )
    return parser


def is_excluded(path: Path, args) -> bool:
    for pattern in args.exclude:
        if pattern.search(str(path)):
            return True
    return False


def process_path(conn, cursor, args):
    """Process an arbitrary path through genplis.

    It will use process_file or process_directory depending on the type of the path.

    """
    if args.path.is_dir():
        process_directory(conn, cursor, args.path, args)
    elif args.path.is_file():
        tags, filters = process_file(conn, cursor, args.path, args)
        if tags:
            print(f"{args.path} detected as music file")

            cache_status = db.is_cache_valid(cursor, args.path)
            match cache_status:
                case None:
                    print("Cache status: not present")
                case True:
                    print("Cache status: valid")
                case True:
                    print("Cache status: stale")

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


def process_directory(conn, cursor, directory, args):
    """Traverse the directory and process all files.

    See process_file for how each file is handled.

    """
    if not directory.is_dir():
        raise GenplisError(
            f"Attempted to process {directory} as a directory but it's not a directory"
        )

    start_time = timer()

    all_tags = {}
    all_filters = {}
    for file in directory.rglob("*"):
        if is_excluded(file, args):
            if args.verbose:
                print(f"Skipping {file} because of exclude pattern.")
            continue

        if file.is_file():
            tags, filters = process_file(conn, cursor, file, args)
            if tags:
                all_tags[file] = tags
            if filters:
                all_filters[file] = filters

    # Apply each filter to all songs to generate playlists
    for filter_file, rules in all_filters.items():
        files = filter_songs(all_tags, filter_file, rules, args)
        print(f"Filter file {filter_file} matched {len(files)} songs")
        if len(files) > 0:
            playlist_file = filter_file.with_suffix(".m3u")
            print(f"Creating playlist {playlist_file}")
            create_m3u(playlist_file, files, overwrite=True)

    end_time = timer()
    process_time = end_time - start_time
    used_memory = psutil.Process().memory_info().rss / (1024 * 1024)
    print(f"Processed {len(all_tags)} files in {process_time:.3f} seconds")
    print(f"Total RAM usage: {used_memory} MiB")

    return all_tags, all_filters


def process_file(conn, cursor, file, args):
    """Process a single file.

    Returns a tuple in the form (tags, filters)

    If it's an M3UG file, parse it as such and return its filters.
    See m3ug module.

    Music files are parsed with tinytag, detected tags are returned as a
    dictionary.

    """
    if not file.is_file():
        raise GenplisError(f"Attempted to process {file} as a file but it's not a file")

    if file.suffix.lower() == ".m3ug":
        content = file.read_text()
        rules = parse_m3ug(file, content, args.verbose)
        return {}, rules

    if db.is_cache_valid(cursor, file):
        # reuse cached tags from DB instead of parsing them again
        # empty tags mean the file is not a supported music file and
        # should be ignored
        cached_tags = db.get_cached_tags(cursor, file)
        return cached_tags, {}

    tags = get_tags(file, args)
    db.cache_tags_for_file(cursor, file, tags)
    conn.commit()
    return tags, {}


def filter_songs(files_and_tags, filter_file, rules, args):
    if args.verbose:
        print(f"\nFiltering songs and generating playlist for {filter_file}")

    filtered_songs = []
    for file, tags in files_and_tags.items():
        for rule in rules:
            if not rule.apply(tags):
                break
        else:
            # only executed if all rules pass
            filtered_songs.append(file)

    if args.verbose:
        print(f"Files that match the filter {filter_file}:")
        for song in filtered_songs:
            print(f"  {song}")

    return filtered_songs


def main():
    # Set up argparse
    parser = setup_argparse()
    args = parser.parse_args()

    db_path = db.get_db_path()
    if args.verbose:
        print(f"Using {db_path} for genplis DB")

    with sqlite3.connect(db_path) as conn:
        cursor = conn.cursor()

        # Create a DB for caching results if it doesn't exist
        db.create_files_table(cursor)
        conn.commit()

        process_path(conn, cursor, args)


if __name__ == "__main__":
    main()
