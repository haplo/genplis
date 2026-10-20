from collections.abc import Iterable
from pathlib import Path

from .types import Verbosity


def create_m3u(
    playlist_path: Path,
    entries: Iterable[Path],
    comments: Iterable[str] = (),
    overwrite: bool = False,
    verbosity: Verbosity = Verbosity.NORMAL,
) -> None:
    """Write an M3U playlist.

    Comments are written before the entries, one "#" line per item. Every
    line is prefixed with "# " so that filter source containing extended M3U
    directives (for example "#EXTINF") cannot be mistaken for playlist
    metadata belonging to the next entry.

    """
    if playlist_path.exists() and not overwrite:
        if verbosity.shows_normal_output:
            print(f"WARNING: {playlist_path} already exists, skipping...")
        return

    playlist_dir = playlist_path.parent
    with open(playlist_path, "w", encoding="utf-8") as playlist_file:
        for comment in comments:
            playlist_file.write(f"# {comment}\n" if comment else "#\n")
        for entry in entries:
            relative_entry = entry.relative_to(playlist_dir, walk_up=True)
            playlist_file.write(str(relative_entry))
            playlist_file.write("\n")
