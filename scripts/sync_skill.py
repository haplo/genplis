"""Regenerate packaged agent instructions and offline references from docs/."""

import re
import tomllib
from pathlib import Path

REFERENCES = ("m3ug.md", "tags.md", "usage.md")
DOCS_URL = "https://github.com/haplo/genplis/blob/main/docs/"


def _rewrite_links(content: str, *, instructions: bool = False) -> str:
    """Keep bundled links local and point unbundled guides at their sources."""

    def replace(match: re.Match[str]) -> str:
        name = match[2]
        if name in REFERENCES:
            target = f"references/{name}" if instructions else name
        else:
            target = DOCS_URL + name
        return f"{match[1]}{target}{match[3]}"

    return re.sub(r"(\[[^\]]*\]\()([\w-]+\.md)([^)]*\))", replace, content)


def skill_payload(root: Path) -> dict[Path, bytes]:
    """Return the distributable skill, derived only from canonical documentation."""
    docs = root / "docs"
    instructions = (docs / "agent-instructions.md").read_text(encoding="utf-8")
    version = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))[
        "project"
    ]["version"]
    instructions = instructions.replace(
        "\n---\n", f'\nmetadata:\n  genplis-version: "{version}"\n---\n', 1
    )
    payload = {
        Path("SKILL.md"): _rewrite_links(instructions, instructions=True).encode(
            "utf-8"
        )
    }
    for name in REFERENCES:
        content = (docs / name).read_text(encoding="utf-8")
        payload[Path("references") / name] = _rewrite_links(content).encode("utf-8")
    return payload


def main() -> None:
    """Update checked-in resources; tests reject stale copies."""
    root = Path(__file__).resolve().parents[1]
    destination = root / "src/genplis/skills/genplis"
    for relative, content in skill_payload(root).items():
        path = destination / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists() or path.read_bytes() != content:
            path.write_bytes(content)
    print(f"Synchronized skill resources in {destination}")


if __name__ == "__main__":
    main()
