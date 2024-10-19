from pathlib import Path

def create_m3u(playlist_path: Path, entries, comment="", overwrite=False):
    if playlist_path.exists() and not overwrite:
        print(f"WARNING: {playlist_path} already exists, skipping...")
        return

    playlist_dir = playlist_path.parent
    with open(playlist_path, 'w') as playlist_file:
        for entry in entries:
            relative_entry = entry.relative_to(playlist_dir, walk_up=True)
            playlist_file.write(str(relative_entry))
            playlist_file.write('\n')
