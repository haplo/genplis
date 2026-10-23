"""Validate a stable release tag and print its curated GitHub Release notes."""

import argparse
import re
import tomllib
from datetime import date
from pathlib import Path


def release_notes(root: Path, tag: str) -> str:
    """Reject inconsistent release metadata and return the changelog entry."""
    if not re.fullmatch(r"v(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)", tag):
        raise ValueError(f"Expected a stable version tag such as v1.0.0, got {tag!r}")
    version = tag[1:]
    project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    if project["project"]["version"] != version:
        raise ValueError(f"Tag {tag} does not match the version in pyproject.toml")

    changelog = (root / "CHANGELOG.md").read_text(encoding="utf-8")
    headings = list(re.finditer(r"^## .*?$", changelog, re.MULTILINE))
    matching = [
        (index, heading)
        for index, heading in enumerate(headings)
        if heading[0].startswith(f"## [{version}]")
    ]
    if len(matching) != 1:
        raise ValueError(f"Expected exactly one changelog entry for {version}")
    index, heading = matching[0]
    dated = re.fullmatch(r"## \[[^\]]+\] - (\d{4}-\d{2}-\d{2})", heading[0])
    if dated is None:
        raise ValueError(f"Changelog entry for {version} needs an ISO release date")
    date.fromisoformat(dated[1])
    end = headings[index + 1].start() if index + 1 < len(headings) else len(changelog)
    body = changelog[heading.end() : end]
    # Reference definitions live at the end of the file, not inside a release.
    reference_pattern = r"^\[[^\]\n]+\]:[^\n]*$"
    body = re.sub(reference_pattern, "", body, flags=re.MULTILINE).strip()
    if not body or not re.search(r"^[-*] \S", body, re.MULTILINE):
        raise ValueError(f"Changelog entry for {version} must list notable changes")
    references = re.findall(reference_pattern, changelog, re.MULTILINE)
    if references:
        body += "\n\n" + "\n".join(references)
    return body + "\n"


def main() -> None:
    """Print notes only after the tag, version, and changelog agree."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tag", help="Stable tag to validate, e.g. v1.0.0")
    args = parser.parse_args()
    try:
        notes = release_notes(Path(__file__).resolve().parents[1], args.tag)
    except ValueError as exc:
        parser.error(str(exc))
    print(notes, end="")


if __name__ == "__main__":
    main()
