import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Final

from tinytag import TinyTag, TinyTagException

from .types import Tags, TagValue

DEFAULT_MAX_TAG_SIZE = 1000
# Backwards-compatible alias for callers that used the old constant name.
LARGE_TAG = DEFAULT_MAX_TAG_SIZE

# Keys that tinytag adds from the file path and audio stream instead of from
# embedded metadata tags. See TinyTag.as_dict().
AUDIO_PROPERTY_TAGS: Final[frozenset[str]] = frozenset(
    {
        "filename",
        "filesize",
        "mime_type",
        "duration",
        "channels",
        "bitrate",
        "bitdepth",
        "samplerate",
        "is_lossless",
    }
)


def get_tags(
    file_path: Path,
    verbose: bool = False,
    *,
    max_size: int = DEFAULT_MAX_TAG_SIZE,
    ignore: frozenset[str] = frozenset(),
) -> Tags | None:
    """Return music tags as a dictionary, or None if not a music file.

    Tag names in ``ignore`` are dropped before size checking. Values larger
    than ``max_size`` bytes are dropped as well; they are usually images or
    lyrics.
    """
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

    ignored = {name.lower() for name in ignore}

    # Sanitize tags:
    # Remove ignored and large tags, they are likely images or lyrics
    for key, value in raw_tags.items():
        if key.lower() in ignored:
            if verbose:
                print(f"Removing tag {key} because it is configured to be ignored")
            continue
        if get_tag_size(value) > max_size:
            if verbose:
                print(f"Removing tag {key} because it's larger than {max_size} bytes")
            continue
        tags[key] = value
    return tags


def get_audio_property_tags(tags: Mapping[str, TagValue]) -> Tags:
    """Return calculated audio properties as display tags.

    Calculated tags are prefixed with ``*`` to distinguish them from tags
    embedded in the file.
    """
    return {f"*{name}": tags[name] for name in AUDIO_PROPERTY_TAGS if name in tags}


def get_tag_size(value: object) -> int:
    if isinstance(value, list):
        return sum(get_tag_size(v) for v in value)
    return sys.getsizeof(value)
