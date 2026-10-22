from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Final, cast

from tinytag import TinyTag, TinyTagException

from .output import ColorRole, Output, Palette
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


class TagDiagnosticKind(StrEnum):
    """Kind of verbose message produced while parsing a file's tags."""

    SKIP = "skip"
    REMOVE = "remove"


@dataclass(frozen=True, slots=True)
class TagDiagnostic:
    """One verbose tag-parsing diagnostic, independent of terminal colors."""

    kind: TagDiagnosticKind
    path: Path
    reason: str
    tag: str | None = None


def format_tag_diagnostic(diagnostic: TagDiagnostic, palette: Palette) -> str:
    """Render one tag diagnostic with semantic colors."""
    if diagnostic.kind is TagDiagnosticKind.SKIP:
        return (
            f"{palette.paint(ColorRole.SKIP, 'Skipping')} "
            f"{palette.title(str(diagnostic.path))}: "
            f"{palette.source(diagnostic.reason)}"
        )
    return (
        f"{palette.warning('Removing tag')} "
        f"{palette.tag(diagnostic.tag or '')} "
        f"{palette.source(f'because {diagnostic.reason}')}"
    )


def parse_tags(
    file_path: Path,
    *,
    max_size: int = DEFAULT_MAX_TAG_SIZE,
    ignore: frozenset[str] = frozenset(),
) -> tuple[Tags | None, tuple[TagDiagnostic, ...]]:
    """Return music tags and verbose diagnostics, without printing anything.

    The tags are ``None`` when the file is not a music file or cannot be read
    or parsed. Tag names in ``ignore`` are dropped before size checking.
    Values whose combined UTF-8 encoded length exceeds ``max_size`` bytes are
    dropped as well; they are usually lyrics or long comments. A ``max_size``
    of 0 disables size filtering.

    Calculated audio properties are never dropped by the size limit.

    The diagnostics are rendered by ``get_tags`` in verbose mode.
    """
    diagnostics: list[TagDiagnostic] = []
    if not TinyTag.is_supported(file_path):
        diagnostics.append(
            TagDiagnostic(
                TagDiagnosticKind.SKIP,
                file_path,
                "not supported by tinytag",
            )
        )
        return None, tuple(diagnostics)

    try:
        audio = TinyTag.get(file_path)
        tags = cast(Tags, audio.as_dict())
        # as_dict() can replace an audio property with embedded metadata of
        # the same name. Preserve the calculated value for explicit lookup.
        for name in AUDIO_PROPERTY_TAGS:
            if name in tags and hasattr(audio, name):
                value = cast(TagValue, getattr(audio, name))
                if tags[name] != value:
                    tags[f"*{name}"] = value
    except (TinyTagException, OSError) as exc:
        diagnostics.append(TagDiagnostic(TagDiagnosticKind.SKIP, file_path, str(exc)))
        return None, tuple(diagnostics)

    ignored = {name.lower() for name in ignore}

    # Sanitize tags in place so rejected values (often lyrics or long
    # comments) are released immediately instead of being kept alive in a
    # second dictionary until the end of the scan.
    for key in tuple(tags):
        if key.lower().removeprefix("*") in ignored:
            diagnostics.append(
                TagDiagnostic(
                    TagDiagnosticKind.REMOVE,
                    file_path,
                    "it is configured to be ignored",
                    tag=key,
                )
            )
            del tags[key]
            continue
        value = tags[key]
        if (
            max_size > 0
            and key.removeprefix("*") not in AUDIO_PROPERTY_TAGS
            and exceeds_tag_size(value, max_size)
        ):
            diagnostics.append(
                TagDiagnostic(
                    TagDiagnosticKind.REMOVE,
                    file_path,
                    f"it's larger than {max_size} UTF-8 bytes",
                    tag=key,
                )
            )
            del tags[key]
            del value
    return tags, tuple(diagnostics)


def is_supported_file(file_path: Path) -> bool:
    """Return whether tinytag recognizes the file as supported music."""
    return TinyTag.is_supported(file_path)


def get_tags(
    file_path: Path,
    verbosity: Verbosity = Verbosity.NORMAL,
    *,
    max_size: int = DEFAULT_MAX_TAG_SIZE,
    ignore: frozenset[str] = frozenset(),
    output: Output | None = None,
) -> Tags | None:
    """Return music tags as a dictionary, or None if not a music file.

    Also returns None when the file cannot be read or parsed.

    Tag names in ``ignore`` are dropped before size checking. Values whose
    combined UTF-8 encoded length exceeds ``max_size`` bytes are dropped as
    well; they are usually lyrics or long comments. A ``max_size`` of 0
    disables size filtering.

    Calculated audio properties are never dropped by the size limit.
    """
    out = Output.plain() if output is None else output
    tags, diagnostics = parse_tags(file_path, max_size=max_size, ignore=ignore)
    if verbosity.is_verbose:
        for diagnostic in diagnostics:
            out.line(format_tag_diagnostic(diagnostic, out.palette))
    return tags


def get_audio_property_tags(tags: Mapping[str, TagValue]) -> Tags:
    """Return calculated audio properties as display tags.

    Calculated tags are prefixed with ``*`` to distinguish them from tags
    embedded in the file.
    """
    calculated: Tags = {}
    for name in AUDIO_PROPERTY_TAGS:
        value = tags.get(f"*{name}", tags.get(name))
        if value is not None and not isinstance(value, list):
            calculated[f"*{name}"] = value
    return calculated


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
