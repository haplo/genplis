import sys
from pathlib import Path

from tinytag import TinyTag, TinyTagException

from .types import Tags

LARGE_TAG = 1000


def get_tags(file_path: Path, verbose: bool = False) -> Tags | None:
    """Return music tags as a dictionary, or None if not a music file."""
    if not TinyTag.is_supported(file_path):
        if verbose:
            print(f"Skipping {file_path}: not supported by tinytag")
        return None

    try:
        raw_tags = TinyTag.get(file_path).as_dict()
    except TinyTagException as exc:
        if verbose:
            print(f"Skipping {file_path}: {exc}")
        return None
    tags: Tags = {}

    # Sanitize tags:
    # Remove large tags, they are likely images or lyrics
    for key, value in raw_tags.items():
        if get_tag_size(value) > LARGE_TAG:
            if verbose:
                print(f"Removing tag {key} because it's larger than {LARGE_TAG} bytes")
            continue
        tags[key] = value
    return tags


def get_tag_size(value: object) -> int:
    if isinstance(value, list):
        return sum(get_tag_size(v) for v in value)
    return sys.getsizeof(value)
