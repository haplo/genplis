import argparse
import json
import re
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from timeit import default_timer as timer

import psutil
from tinytag import TinyTag
from xdg_base_dirs import xdg_cache_home

from .json import GenplisJSONEncoder
from .m3u import create_m3u
from .m3ug import parse_m3ug

DB_NAME = "genplis.db"
LARGE_TAG = 1000


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


def get_tags(file_path, args):
    if not TinyTag.is_supported(file_path):
        print(f"Skipping {file_path}: not supported by tinytag")
        return {}
    tag = TinyTag.get(file_path).as_dict()
    # remove large tags, they are likely images or lyrics
    for key in list(tag.keys()):
        value = tag[key]
        if get_tag_size(value) > LARGE_TAG:
            if args.verbose:
                print(f"Removing tag {key} because it's larger than {LARGE_TAG} bytes")
            del tag[key]
    return tag


def get_tag_size(value):
    if isinstance(value, list):
        return sum(get_tag_size(v) for v in value)
    return sys.getsizeof(value)


def is_excluded(path: Path, args) -> bool:
    for pattern in args.exclude:
        if pattern.search(str(path)):
            return True
    return False


def process_path(conn, cursor, args):
    if args.path.is_dir():
        process_directory(conn, cursor, args.path, args)
    elif args.path.is_file():
        tags, filters = process_file(conn, cursor, args.path, args)
        if tags:
            print(f"{args.path} detected as music file")
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
    """Traverse the directory and process tags for all files"""
    assert directory.is_dir()

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

    Otherwise attempt to parse it as a music file and return its tags.

    """
    assert file.is_file()

    if file.suffix.lower() == ".m3ug":
        content = file.read_text()
        rules = parse_m3ug(file, content, args.verbose)
        return {}, rules

    file_path = file.absolute()
    file_last_modified = datetime.fromtimestamp(file.stat().st_mtime)

    # Check if the file path already exists in the database
    cursor.execute(
        """SELECT last_modified, tags FROM files WHERE path = ?""",
        (str(file_path),),
    )
    row = cursor.fetchone()
    if row:
        cached_timestamp, cached_tags = row
        # Update the timestamp if it's more recent
        db_last_modified = datetime.fromisoformat(cached_timestamp)

        if file_last_modified <= db_last_modified:
            # reuse cached tags from DB instead of parsing them again
            # empty tags mean the file is not a supported music file and
            # should be ignored
            if cached_tags:
                return json.loads(cached_tags), {}

        print(f"Refreshing tags for file: {file_path}")
        tags = get_tags(file_path, args)

        cursor.execute(
            """
            UPDATE files SET last_modified = ?, tags = ?
            WHERE path = ?
            """,
            (
                file_last_modified,
                json.dumps(tags, cls=GenplisJSONEncoder),
                str(file_path),
            ),
        )
        conn.commit()
        print(f"Updated cache for file: {file_path}")
        return tags, {}
    else:
        tags = get_tags(file_path, args)
        # Insert the new file path and timestamp into the database
        cursor.execute(
            """
            INSERT INTO files (path, last_modified, tags)
            VALUES (?, ?, ?)
        """,
            (
                str(file_path),
                file_last_modified,
                json.dumps(tags, cls=GenplisJSONEncoder),
            ),
        )
        conn.commit()
        print(f"Processed new file: {file_path}")
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

    db_path = xdg_cache_home() / "genplis" / DB_NAME

    with sqlite3.connect(db_path) as conn:
        cursor = conn.cursor()

        # Create a DB for caching results if it doesn't exist
        create_files_table(cursor)
        conn.commit()

        process_path(conn, cursor, args)


if __name__ == "__main__":
    main()
