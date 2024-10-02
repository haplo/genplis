import argparse
import json
import pathlib
import sqlite3
import sys
from datetime import datetime

from tinytag import TinyTag

from .json import GenplisJSONEncoder

DB_NAME = "genplis.db"


def setup_argparse():
    parser = argparse.ArgumentParser(
        description="Generate music playlists from your own filters."
    )
    parser.add_argument(
        "directory",
        type=pathlib.Path,
        help="The path to the directory to process.",
        metavar="DIR",
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


def get_tags(file_path):
    tag = TinyTag.get(file_path)
    # remove all extra tags larger than 1 KB, they are likely images or lyrics
    for key in list(tag.extra.keys()):
        value = tag.extra[key]
        if sys.getsizeof(value) > 1000:
            del tag.extra[key]
    return tag.as_dict()


def process_directory(conn, cursor, args):
    all_tags = {}
    all_filters = {}
    for file in args.directory.rglob("*"):
        if file.is_file():
            file_path = file.absolute()

            if not TinyTag.is_supported(file_path):
                print(f"Skipping {file_path}: not supported by tinytag")
                continue

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
                    all_tags[file] = json.loads(cached_tags)
                    continue

                print(f"Refreshing tags for file: {file_path}")
                tags = get_tags(file_path)
                cursor.execute(
                    """
                    UPDATE files SET last_modified = ?, tags = ?
                    WHERE path = ?
                    """,
                    (file_last_modified, json.dumps(tags, cls=GenplisJSONEncoder), str(file_path)),
                )
                conn.commit()
                print(f"Updated cache for file: {file_path}")
                all_tags[file] = tags
            else:
                tags = get_tags(file_path)
                # Insert the new file path and timestamp into the database
                cursor.execute(
                    """
                    INSERT INTO files (path, last_modified, tags)
                    VALUES (?, ?, ?)
                """,
                    (str(file_path), file_last_modified, json.dumps(tags, cls=GenplisJSONEncoder)),
                )
                conn.commit()
                print(f"Processed new file: {file_path}")
                all_tags[file] = tags

    return all_tags, all_filters


def main():
    # Set up argparse
    parser = setup_argparse()
    args = parser.parse_args()

    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()

        # Create a DB for caching results if it doesn't exist
        create_files_table(cursor)
        conn.commit()

        # Traverse the directory and process tags for all files
        all_tags, all_filters = process_directory(conn, cursor, args)


if __name__ == "__main__":
    main()