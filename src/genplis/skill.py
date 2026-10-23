"""Install the bundled, portable M3UG authoring skill."""

from importlib.resources import files
from importlib.resources.abc import Traversable
from pathlib import Path
from tempfile import TemporaryDirectory

from .exceptions import GenplisError


def _read_payload(source: Traversable, prefix: Path = Path()) -> dict[Path, bytes]:
    payload: dict[Path, bytes] = {}
    for entry in source.iterdir():
        relative = prefix / entry.name
        if entry.is_dir():
            payload.update(_read_payload(entry, relative))
        else:
            payload[relative] = entry.read_bytes()
    return payload


def _check_destination(destination: Path, payload: dict[Path, bytes]) -> None:
    """Check all owned paths before writing, including when forcing an update."""
    for relative in payload:
        current = destination
        for part in relative.parts:
            if current.is_symlink():
                raise GenplisError(
                    f"Refusing to install through symbolic link: {current}"
                )
            if current.exists() and not current.is_dir():
                raise GenplisError(
                    f"Skill installation requires a directory: {current}"
                )
            current /= part
        path = destination / relative
        if path.is_symlink():
            raise GenplisError(f"Refusing to replace symbolic link: {path}")
        if path.exists() and not path.is_file():
            raise GenplisError(f"Skill installation requires a regular file: {path}")


def install_skill(target: str = "agents", *, force: bool = False) -> Path:
    """Copy the packaged skill to a user's shared or Claude Code skills directory.

    Identical installations are left untouched. Existing, differing bundled
    files require ``force``; extra user files are preserved. Symlinks and
    file/directory collisions inside the skill are always rejected.
    """
    if target not in {"agents", "claude"}:
        raise GenplisError(f"Unknown skill target {target!r}; choose agents or claude")
    destination = Path.home() / f".{target}" / "skills" / "genplis"
    try:
        payload = _read_payload(files("genplis").joinpath("skills", "genplis"))
        _check_destination(destination, payload)
        changed = {
            relative: data
            for relative, data in payload.items()
            if not (destination / relative).is_file()
            or (destination / relative).read_bytes() != data
        }
        if not changed:
            return destination
        if destination.exists() and not force:
            raise GenplisError(
                f"Skill already exists and differs at {destination}; "
                "back up any customizations, then use --install-skill "
                f"{target} --force to replace bundled files"
            )

        destination.parent.mkdir(parents=True, exist_ok=True)
        with TemporaryDirectory(prefix=".genplis-", dir=destination.parent) as temp:
            staged = Path(temp) / "genplis"
            for relative, data in changed.items():
                path = staged / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)
            if not destination.exists():
                staged.rename(destination)
            else:
                for relative in changed:
                    path = destination / relative
                    path.parent.mkdir(parents=True, exist_ok=True)
                    (staged / relative).replace(path)
    except OSError as exc:
        raise GenplisError(f"Cannot install skill at {destination}: {exc}") from exc
    return destination
