"""Release metadata and curated notes must agree before anything is published."""

from pathlib import Path

import pytest

from scripts.release import release_notes


@pytest.fixture
def release_root(tmp_path: Path) -> Path:
    """Create the metadata required to validate a release tag."""
    (tmp_path / "pyproject.toml").write_text('[project]\nversion = "1.0.0"\n')
    (tmp_path / "CHANGELOG.md").write_text(
        "# Changelog\n\n## [Unreleased]\n\n### Added\n\n- Future work.\n\n"
        "## [1.0.0] - 2026-10-23\n\n### Added\n\n- First release.\n\n"
        "## [0.9.0] - 2026-10-01\n\n- Older work.\n\n"
        "[1.0.0]: https://github.com/haplo/genplis/releases/tag/v1.0.0\n"
    )
    return tmp_path


def test_release_notes_extract_only_matching_section(release_root: Path) -> None:
    notes = release_notes(release_root, "v1.0.0")
    assert notes.startswith("### Added\n\n- First release.")
    assert "Future work" not in notes
    assert "Older work" not in notes


@pytest.mark.parametrize("tag", ["1.0.0", "v1.0.0rc1", "v01.0.0", "v1.0.0/other"])
def test_release_rejects_non_stable_tags(release_root: Path, tag: str) -> None:
    with pytest.raises(ValueError, match="stable version tag"):
        release_notes(release_root, tag)


def test_release_rejects_mismatched_version(release_root: Path) -> None:
    with pytest.raises(ValueError, match="does not match"):
        release_notes(release_root, "v1.0.1")


@pytest.mark.parametrize(
    "section",
    [
        "## [Unreleased]\n\n- Work in progress.\n",
        "## [1.0.0] - YYYY-MM-DD\n\n- First release.\n",
        "## [1.0.0] - 2026-02-30\n\n- First release.\n",
        "## [1.0.0] - 2026-10-23\n\n",
        "## [1.0.0] - 2026-10-23\n\n- First.\n\n"
        "## [1.0.0] - 2026-10-23\n\n- Duplicate.\n",
    ],
)
def test_release_requires_one_dated_nonempty_entry(
    release_root: Path, section: str
) -> None:
    (release_root / "CHANGELOG.md").write_text(section)
    with pytest.raises(ValueError):
        release_notes(release_root, "v1.0.0")


def test_release_notes_preserve_reference_links(release_root: Path) -> None:
    (release_root / "CHANGELOG.md").write_text(
        "## [1.0.0] - 2026-10-23\n\n- See [guide].\n\n"
        "[guide]: https://haplo.github.io/genplis/docs/\n"
    )
    notes = release_notes(release_root, "v1.0.0")
    assert "- See [guide]." in notes
    assert "[guide]: https://haplo.github.io/genplis/docs/" in notes
