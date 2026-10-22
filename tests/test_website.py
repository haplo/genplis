"""The website reuses repository sources without maintaining generated copies."""

from pathlib import Path
from zipfile import ZipFile

import pytest

from scripts.website import check_site, prepare_site


@pytest.fixture
def website_root(tmp_path: Path) -> Path:
    """Create a small repository containing website sources and examples."""
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "home.md").write_text(
        "---\nsearch:\n  exclude: true\n---\n# Home\n\n[Docs](index.md)\n"
    )
    (docs / "index.md").write_text("# Documentation\n\n[Home](home.md)\n")
    (docs / "usage.md").write_text("# Usage\n\n[Docs](index.md#start)\n")
    (docs / "assets").mkdir()
    (docs / "assets" / "test.svg").write_text("<svg></svg>")
    (docs / "assets" / "README.md").write_text("# Asset maintenance notes\n")
    examples = tmp_path / "examples"
    examples.mkdir()
    (examples / "Zebra.m3ug").write_bytes(b"# Preserve CRLF\r\ngenre = Rock\r\n")
    (examples / "A & B.m3ug").write_text(
        "# Includes and fences\n@INCLUDE Zebra\n# ```\n"
    )
    (examples / "config.ini").write_text("[general]\n")
    return tmp_path


def test_prepare_routes_sources_and_preserves_metadata(website_root: Path) -> None:
    prepare_site(website_root)
    staged = website_root / ".website-src"
    home = (staged / "index.md").read_text()
    assert "source_path: docs/home.md" in home
    assert "search:\n  exclude: true" in home
    assert "[Docs](docs/index.md)" in home
    assert "[Home](../index.md)" in (staged / "docs/index.md").read_text()
    assert "[Docs](index.md#start)" in (staged / "docs/usage.md").read_text()
    assert (staged / "assets/test.svg").is_file()
    assert not (staged / "docs/home.md").exists()
    assert not (staged / "docs/assets").exists()
    assert not (staged / "assets/README.md").exists()
    assert (website_root / "docs/index.md").read_text().endswith("[Home](home.md)\n")


def test_examples_are_sorted_verbatim_and_downloadable(website_root: Path) -> None:
    prepare_site(website_root)
    staged = website_root / ".website-src"
    gallery = (staged / "docs/examples.md").read_text()
    assert gallery.index("## A & B") < gallery.index("## Zebra")
    assert "A%20%26%20B.m3ug" in gallery
    assert 'download="A &amp; B.m3ug"' in gallery
    assert "````text\n# Includes and fences\n@INCLUDE Zebra\n# ```\n````" in gallery
    assert "generated: true" in gallery
    assert "companion" in gallery
    downloads = staged / "downloads/examples"
    with ZipFile(staged / "downloads/genplis-examples.zip") as archive:
        assert archive.namelist() == ["A & B.m3ug", "Zebra.m3ug"]
        for name in archive.namelist():
            original = (website_root / "examples" / name).read_bytes()
            assert (downloads / name).read_bytes() == original
            assert archive.read(name) == original
    assert not (downloads / "config.ini").exists()


def test_regeneration_removes_stale_files_and_is_reproducible(
    website_root: Path,
) -> None:
    prepare_site(website_root)
    staged = website_root / ".website-src"
    archive = staged / "downloads/genplis-examples.zip"
    first = archive.read_bytes()
    mtime = archive.stat().st_mtime_ns
    prepare_site(website_root)
    assert archive.read_bytes() == first
    assert archive.stat().st_mtime_ns == mtime
    (website_root / "examples/Zebra.m3ug").unlink()
    (website_root / "docs/usage.md").unlink()
    prepare_site(website_root)
    assert not (staged / "downloads/examples/Zebra.m3ug").exists()
    assert not (staged / "docs/usage.md").exists()
    assert "## Zebra" not in (staged / "docs/examples.md").read_text()


def test_gallery_cannot_shadow_a_handwritten_page(website_root: Path) -> None:
    (website_root / "docs/examples.md").write_text("# Handwritten\n")
    with pytest.raises(ValueError, match="generated"):
        prepare_site(website_root)


def test_links_are_remapped_without_changing_repository_links_or_code(
    website_root: Path,
) -> None:
    content = """# Guide

[Gallery](https://github.com/haplo/genplis/tree/main/examples)
[Config source](https://github.com/haplo/genplis/blob/main/examples/config.ini)
![Mark](assets/test.svg)
[Home](home.md?source=guide#top)

```markdown
[Home](home.md)
```
"""
    (website_root / "docs/usage.md").write_text(content)
    prepare_site(website_root)
    guide = (website_root / ".website-src/docs/usage.md").read_text()
    assert "[Gallery](examples.md)" in guide
    assert (
        "[Config source](https://github.com/haplo/genplis/blob/main/examples/config.ini)"
        in guide
    )
    assert "![Mark](../assets/test.svg)" in guide
    assert "[Home](../index.md?source=guide#top)" in guide
    assert "```markdown\n[Home](home.md)\n```" in guide


def test_missing_examples_fail_clearly(website_root: Path) -> None:
    for file in (website_root / "examples").glob("*.m3ug"):
        file.unlink()
    with pytest.raises(ValueError, match="No examples"):
        prepare_site(website_root)


def test_missing_landing_page_fails_clearly(website_root: Path) -> None:
    (website_root / "docs/home.md").unlink()
    with pytest.raises(ValueError, match="docs/home.md"):
        prepare_site(website_root)


def test_check_site_resolves_prefix_fragments_and_encoded_downloads(
    tmp_path: Path,
) -> None:
    (tmp_path / "docs").mkdir()
    (tmp_path / "index.html").write_text(
        '<a href="docs/#start">Docs</a><img src="/genplis/logo.svg">'
        '<a href="https://example.com/elsewhere#external">External</a>'
        '<a href="mailto:hello@example.com">Email</a>'
    )
    (tmp_path / "docs/index.html").write_text(
        '<h1 id="start">Start</h1><a href="../A%20%26%20B.m3ug">Download</a>'
        '<a href="https://haplo.github.io/genplis/">Home</a>'
    )
    (tmp_path / "logo.svg").write_text("<svg></svg>")
    (tmp_path / "A & B.m3ug").write_text("genre = Rock\n")
    check_site(tmp_path, "https://haplo.github.io/genplis/")


@pytest.mark.parametrize(
    ("link", "error"),
    [
        ("/assets/missing.svg", "outside the site prefix"),
        ("missing.html", "missing file"),
        ("#missing", "missing anchor"),
        ("/genplis/%2e%2e/secret", "outside the output directory"),
    ],
)
def test_check_site_reports_broken_links(tmp_path: Path, link: str, error: str) -> None:
    (tmp_path / "index.html").write_text(f'<a href="{link}">Broken</a>')
    with pytest.raises(ValueError, match=error):
        check_site(tmp_path, "https://haplo.github.io/genplis/")
