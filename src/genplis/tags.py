import sys
from pathlib import Path

from tinytag import TinyTag

LARGE_TAG = 1000


def get_tags(file_path, args) -> dict | None:
    """Return music tags as a dictionary, or None if not a music file."""
    if not TinyTag.is_supported(file_path):
        if args.verbose:
            print(f"Skipping {file_path}: not supported by tinytag")
        return None

    tag = TinyTag.get(file_path).as_dict()

    # Sanitize tags:
    # 1. Transform Paths into strings, otherwise m3ug rules would fail
    # 2. Remove large tags, they are likely images or lyrics
    for key in list(tag.keys()):
        value = tag[key]
        if isinstance(value, Path):
            value = tag[key] = str(value)
        if get_tag_size(value) > LARGE_TAG:
            if args.verbose:
                print(f"Removing tag {key} because it's larger than {LARGE_TAG} bytes")
            del tag[key]
    return tag


def get_tag_size(value) -> int:
    if isinstance(value, list):
        return sum(get_tag_size(v) for v in value)
    return sys.getsizeof(value)
