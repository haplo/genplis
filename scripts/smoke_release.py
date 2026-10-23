"""Exercise an installed distribution, including real worker processes.

Run with ``uv run --isolated --no-project --with <wheel-or-sdist>
python scripts/smoke_release.py <version>``. Do not run through pytest:
its source-tree pythonpath would hide packaging mistakes.
"""

import argparse
import os
import shutil
import subprocess
import sys
from importlib.metadata import version
from pathlib import Path
from tempfile import TemporaryDirectory


def _run(*args: str, env: dict[str, str] | None = None) -> str:
    return subprocess.run(  # noqa: S603 - fixed interpreter, test-owned arguments
        [sys.executable, "-m", "genplis", *args],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    ).stdout


def _smoke_skill(root: Path) -> None:
    """Install packaged resources without writing to the real user home."""
    home = root / "home"
    home.mkdir()
    env = {**os.environ, "HOME": str(home), "USERPROFILE": str(home)}
    for target, arguments in (
        ("agents", ("--install-skill",)),
        ("claude", ("--install-skill", "claude")),
    ):
        _run(*arguments, env=env)
        destination = home / f".{target}" / "skills/genplis"
        if (
            not (destination / "SKILL.md")
            .read_text(encoding="utf-8")
            .startswith("---\nname: genplis\n")
        ):
            raise RuntimeError("Installed skill is missing its instructions")
        for name in ("m3ug.md", "tags.md", "usage.md"):
            if not (destination / "references" / name).read_text(encoding="utf-8"):
                raise RuntimeError(f"Installed skill is missing reference {name}")
        _run(*arguments, env=env)  # Identical reinstalls must succeed.


def smoke_test(expected_version: str) -> None:
    """Verify metadata, both entry points, and cold/warm playlist generation."""
    if version("genplis") != expected_version:
        raise RuntimeError("Installed distribution has the wrong version")
    expected_output = f"genplis {expected_version}\n"
    if _run("--version") != expected_output:
        raise RuntimeError("python -m genplis reports the wrong version")
    executable = shutil.which("genplis")
    if executable is None:
        raise RuntimeError("genplis console entry point was not installed")
    result = subprocess.run(  # noqa: S603 - installed console entry point
        [executable, "--version"], check=True, capture_output=True, text=True
    )
    if result.stdout != expected_output:
        raise RuntimeError("Console entry point reports the wrong version")
    _run("--help")

    fixture = Path(__file__).resolve().parents[1] / "tests/files/test.mp3"
    with TemporaryDirectory(prefix="genplis-smoke-") as temp:
        root = Path(temp)
        _smoke_skill(root)
        music = root / "music"
        music.mkdir()
        # Exceed MIN_PARALLEL_FILES so --jobs 2 actually launches workers.
        for index in range(70):
            shutil.copyfile(fixture, music / f"song-{index:03}.mp3")
        (music / "all.m3ug").write_text('artist = "Test Artist"\n', encoding="utf-8")
        common = ["--no-config", "--no-color", str(music)]
        playlist = music / "all.m3u"
        _run(*common, "--jobs", "1", "--db", str(root / "sequential.db"))
        expected = playlist.read_bytes()
        text = expected.decode("utf-8")
        if not text.startswith("#EXTM3U\n") or text.count("#EXTINF:") != 70:
            raise RuntimeError("Smoke playlist is missing songs or extended metadata")
        for _ in range(2):  # cold parallel parse, then warm cache
            _run(*common, "--jobs", "2", "--db", str(root / "parallel.db"))
            if playlist.read_bytes() != expected:
                raise RuntimeError("Sequential, parallel, and cached playlists differ")
    print(
        f"Installed genplis {expected_version}: entry points, skills, and playlists OK"
    )


def main() -> None:
    """Run the installed-package smoke test."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("version")
    args = parser.parse_args()
    smoke_test(args.version)


if __name__ == "__main__":
    main()
