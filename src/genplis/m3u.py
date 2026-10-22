import math
import os
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

from .output import Output
from .types import TagValue, Verbosity

# RFC 8216 section 4.1 forbids control characters in playlist text. Titles can
# contain newlines when they come from sloppy tags, so flatten them instead of
# corrupting the line-oriented playlist format.
_CONTROL_CHARACTERS = {code: " " for code in (*range(0x20), *range(0x7F, 0xA0))}


@dataclass(frozen=True, slots=True)
class PlaylistEntry:
    """A file to write, with optional extended-M3U metadata."""

    path: Path
    duration: float | None = None
    title: str | None = None


def playlist_entry(path: Path, tags: Mapping[str, TagValue]) -> PlaylistEntry:
    """Build a playlist entry from cached tags.

    The title is ``artist - title``, falling back to whichever one exists and
    finally to the file name. Multi-valued tags use their first non-empty
    value. The duration is the cached value in seconds; clients that cannot
    determine it get ``None`` and the writer emits ``-1``.
    """
    return PlaylistEntry(
        path=path,
        duration=duration_seconds(tags.get("duration")),
        title=_entry_title(path, tags),
    )


def create_m3u(
    playlist_path: Path,
    entries: Iterable[Path | PlaylistEntry],
    comments: Iterable[str] = (),
    overwrite: bool = False,
    verbosity: Verbosity = Verbosity.NORMAL,
    *,
    extended: bool = True,
    output: Output | None = None,
) -> None:
    """Write an M3U playlist.

    Comments are written before the entries, one "#" line per item. Every
    line is prefixed with "# " so that filter source containing extended M3U
    directives (for example "#EXTINF") cannot be mistaken for playlist
    metadata belonging to the next entry.

    With ``extended`` (the default), the file starts with ``#EXTM3U`` and
    every entry is preceded by an ``#EXTINF:<seconds>,<title>`` line. Entries
    passed as plain paths use the file name as their title and ``-1`` as their
    duration. Pass ``extended=False`` to write a plain path-only playlist.
    """
    out = Output.plain() if output is None else output
    if playlist_path.exists() and not overwrite:
        if verbosity.shows_normal_output:
            out.line(
                f"{out.palette.warning('WARNING:')} "
                f"{out.palette.title(str(playlist_path))} "
                f"{out.palette.source('already exists, skipping...')}"
            )
        return

    playlist_dir = playlist_path.parent
    with open(playlist_path, "w", encoding="utf-8") as playlist_file:
        if extended:
            playlist_file.write("#EXTM3U\n")
        for comment in comments:
            playlist_file.write(f"# {comment}\n" if comment else "#\n")
        for raw_entry in entries:
            entry = (
                raw_entry
                if isinstance(raw_entry, PlaylistEntry)
                else PlaylistEntry(raw_entry)
            )
            try:
                playlist_entry_path = entry.path.relative_to(playlist_dir, walk_up=True)
            except ValueError:
                # A mix of relative and absolute paths has no common form;
                # normalize both against the current directory first.
                try:
                    playlist_entry_path = Path(os.path.abspath(entry.path)).relative_to(
                        Path(os.path.abspath(playlist_dir)), walk_up=True
                    )
                except ValueError:
                    # Paths with no common root (for example different Windows
                    # drives) cannot be relative; fall back to the absolute path.
                    playlist_entry_path = entry.path
            if extended:
                playlist_file.write(_format_extinf(entry))
                playlist_file.write("\n")
            playlist_file.write(str(playlist_entry_path))
            playlist_file.write("\n")


def _format_extinf(entry: PlaylistEntry) -> str:
    """Format the EXTINF line for an entry, including an unknown duration."""
    duration = entry.duration
    if duration is None or not math.isfinite(duration) or duration < 0:
        duration_text = "-1"
    else:
        duration_text = f"{duration:.3f}"
    title = (
        _sanitize_text(entry.title)
        if entry.title is not None
        else _sanitize_text(entry.path.stem)
    )
    return f"#EXTINF:{duration_text},{title}"


def _entry_title(path: Path, tags: Mapping[str, TagValue]) -> str:
    artist = _first_text(tags.get("artist"))
    title = _first_text(tags.get("title"))
    if artist and title:
        return f"{artist} - {title}"
    return title or artist or _sanitize_text(path.stem)


def _first_text(value: TagValue) -> str:
    """Return the first non-empty text value from a possibly multi-valued tag."""
    if isinstance(value, list):
        for item in value:
            text = _sanitize_text(item)
            if text:
                return text
        return ""
    return _sanitize_text(value)


def _sanitize_text(value: object) -> str:
    """Flatten control characters and trim surrounding whitespace."""
    if value is None or isinstance(value, bool):
        return ""
    return str(value).translate(_CONTROL_CHARACTERS).strip()


def duration_seconds(value: TagValue) -> float | None:
    """Return a usable duration in seconds, or None when the tag is unusable."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        duration = float(value)
    elif isinstance(value, str):
        try:
            duration = float(value)
        except ValueError:
            return None
    else:
        return None
    if not math.isfinite(duration) or duration < 0:
        return None
    return duration
