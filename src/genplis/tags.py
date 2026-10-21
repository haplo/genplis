from collections.abc import Mapping
from pathlib import Path
from typing import Final, cast

from tinytag import TinyTag, TinyTagException

from .types import Tags, TagValue, Verbosity

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


def parse_tags(
    file_path: Path,
    *,
    max_size: int = DEFAULT_MAX_TAG_SIZE,
    ignore: frozenset[str] = frozenset(),
) -> tuple[Tags | None, tuple[str, ...]]:
    """Return music tags and verbose diagnostics, without printing anything.

    The tags are ``None`` when the file is not a music file or cannot be read
    or parsed. Tag names in ``ignore`` are dropped before size checking.
    Values whose combined UTF-8 encoded length exceeds ``max_size`` bytes are
    dropped as well; they are usually lyrics or long comments. A ``max_size``
    of 0 disables size filtering.

    Calculated audio properties are never dropped by the size limit.

    The messages are the lines that ``get_tags`` prints in verbose mode.
    """
    messages: list[str] = []
    if not TinyTag.is_supported(file_path):
        messages.append(f"Skipping {file_path}: not supported by tinytag")
        return None, tuple(messages)

    try:
        tags = cast(Tags, TinyTag.get(file_path).as_dict())
    except (TinyTagException, OSError) as exc:
        messages.append(f"Skipping {file_path}: {exc}")
        return None, tuple(messages)

    ignored = {name.lower() for name in ignore}

    # Sanitize tags in place so rejected values (often lyrics or long
    # comments) are released immediately instead of being kept alive in a
    # second dictionary until the end of the scan.
    for key in tuple(tags):
        if key.lower() in ignored:
            messages.append(
                f"Removing tag {key} because it is configured to be ignored"
            )
            del tags[key]
            continue
        value = tags[key]
        if (
            max_size > 0
            and key not in AUDIO_PROPERTY_TAGS
            and exceeds_tag_size(value, max_size)
        ):
            messages.append(
                f"Removing tag {key} because it's larger than {max_size} UTF-8 bytes"
            )
            del tags[key]
            del value
    return tags, tuple(messages)


def get_tags(
    file_path: Path,
    verbosity: Verbosity = Verbosity.NORMAL,
    *,
    max_size: int = DEFAULT_MAX_TAG_SIZE,
    ignore: frozenset[str] = frozenset(),
) -> Tags | None:
    """Return music tags as a dictionary, or None if not a music file.

    Also returns None when the file cannot be read or parsed.

    Tag names in ``ignore`` are dropped before size checking. Values whose
    combined UTF-8 encoded length exceeds ``max_size`` bytes are dropped as
    well; they are usually lyrics or long comments. A ``max_size`` of 0
    disables size filtering.

    Calculated audio properties are never dropped by the size limit.
    """
    tags, messages = parse_tags(file_path, max_size=max_size, ignore=ignore)
    if verbosity.is_verbose:
        for message in messages:
            print(message)
    return tags


def get_audio_property_tags(tags: Mapping[str, TagValue]) -> Tags:
    """Return calculated audio properties as display tags.

    Calculated tags are prefixed with ``*`` to distinguish them from tags
    embedded in the file.
    """
    return {f"*{name}": tags[name] for name in AUDIO_PROPERTY_TAGS if name in tags}


def get_tag_size(value: object) -> int:
    """Return the UTF-8 encoded size of a tag value in bytes.

    Multi-valued tags are measured as the sum of their values.
    """
    if isinstance(value, list):
        return sum(get_tag_size(item) for item in value)
    if isinstance(value, str):
        return len(value.encode("utf-8"))
    return len(str(value).encode("utf-8"))


def exceeds_tag_size(value: object, max_size: int) -> bool:
    """Return whether a tag value is larger than max_size UTF-8 bytes.

    Avoids encoding large strings when their character count already proves
    the answer. UTF-8 uses at most four bytes per code point, so a string with
    more characters than the limit is always too large, and a string whose
    length times four fits the limit can never exceed it.
    """
    if isinstance(value, list):
        total = 0
        for item in value:
            if exceeds_tag_size(item, max_size - total):
                return True
            total += get_tag_size(item)
        return False
    if isinstance(value, str):
        if len(value) > max_size:
            return True
        if len(value) * 4 <= max_size:
            return False
        return len(value.encode("utf-8")) > max_size
    return len(str(value).encode("utf-8")) > max_size
