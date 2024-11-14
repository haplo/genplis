from pathlib import Path


def get_last_modified(path: Path) -> int:
    """Return time of last modification as UNIX timestamp"""
    # return datetime.fromtimestamp(path.stat().st_mtime)
    return int(path.stat().st_mtime)
