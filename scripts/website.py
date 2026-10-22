"""Prepare, build, validate, and preview the GitHub Pages website."""

import argparse
import io
import posixpath
import re
import subprocess
import sys
import time
import tomllib
from html import escape
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath
from urllib.parse import quote, unquote, urljoin, urlsplit, urlunsplit
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES_URL = "https://github.com/haplo/genplis/tree/main/examples"


def _route(source: str) -> PurePosixPath:
    if source == "home.md":
        return PurePosixPath("index.md")
    if source.startswith("assets/"):
        return PurePosixPath(source)
    return PurePosixPath("docs") / source


def _rewrite_links(content: str, source: str) -> str:
    """Keep source links useful on GitHub while accounting for website routes."""

    def replace(match: re.Match[str]) -> str:
        target = urlsplit(match[2])
        if match[2].rstrip("/") == EXAMPLES_URL:
            destination = PurePosixPath("docs/examples.md")
        elif target.scheme or target.netloc or not target.path:
            return match[0]
        else:
            resolved = posixpath.normpath(
                str(PurePosixPath(source).parent / unquote(target.path))
            )
            if resolved.startswith(("../", "/")):
                return match[0]
            destination = _route(resolved)
        relative = posixpath.relpath(destination, _route(source).parent)
        url = urlunsplit(
            ("", "", quote(relative, safe="/"), target.query, target.fragment)
        )
        return f"{match[1]}{url}{match[3]}"

    lines: list[str] = []
    fence = ""
    for line in content.splitlines(keepends=True):
        marker = re.match(r"^\s*(`{3,}|~{3,})", line)
        if marker:
            if not fence:
                fence = marker[1]
            elif marker[1][0] == fence[0] and len(marker[1]) >= len(fence):
                fence = ""
            lines.append(line)
        elif fence:
            lines.append(line)
        else:
            lines.append(re.sub(r"(!?\[[^\]\n]*\]\()([^\s)]+)(\))", replace, line))
    return "".join(lines)


def _source_metadata(content: str, source: str) -> str:
    metadata = f"source_path: docs/{source}\n"
    if content.startswith("---\n"):
        return "---\n" + metadata + content[4:]
    return f"---\n{metadata}---\n\n{content}"


def _examples(files: list[Path]) -> tuple[str, bytes]:
    sections = [
        "---\ngenerated: true\ndescription: Ready-to-copy M3UG playlist filters, "
        "generated directly from the repository examples.\n---\n\n"
        "# M3UG Examples\n\n"
        "A few rules can turn a whole collection into a playlist. "
        "Copy a definition into a `.m3ug` file inside your music collection, "
        "then run `genplis ~/Music` to generate its `.m3u`. "
        "See the [M3UG reference](m3ug.md) for the language and "
        "[Tags](tags.md#rating) for rating-scale caveats.\n\n"
        '<a class="md-button md-button--primary" '
        'href="../downloads/genplis-examples.zip" download>'
        "Download all examples (.zip)</a>\n\n"
        "Some definitions use `@INCLUDE` and need a **companion file**. "
        "For example, `Favorite synth.m3ug` includes `Favorite fragments.m3ug`. "
        "The ZIP preserves every filename, so extracting all its files together "
        "keeps these includes working. Files marked `@NO-PLAYLIST` are shared "
        "fragments, not standalone playlists.\n\n"
    ]
    buffer = io.BytesIO()
    with ZipFile(buffer, "w", compression=ZIP_DEFLATED) as archive:
        for file in files:
            data = file.read_bytes()
            text = data.decode("utf-8")
            code = text if text.endswith("\n") else text + "\n"
            title = re.sub(r"([\\`*_{}\[\]<>()#!|])", r"\\\1", file.stem)
            fence = "`" * max(
                3, 1 + max((len(m[0]) for m in re.finditer(r"`+", text)), default=0)
            )
            sections.append(
                f"## {title}\n\n"
                f'<a href="../downloads/examples/{quote(file.name, safe="")}" '
                f'download="{escape(file.name, quote=True)}">Download '
                f"{escape(file.name)}</a>\n\n"
                f"{fence}text\n{code}{fence}\n\n"
            )
            info = ZipInfo(file.name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, data)
    return "".join(sections), buffer.getvalue()


def prepare_site(root: Path) -> None:
    """Assemble disposable website sources, examples, and byte-exact downloads."""
    docs = root / "docs"
    if (docs / "examples.md").exists():
        raise ValueError("docs/examples.md is generated; do not add a handwritten copy")
    for required in ("home.md", "index.md"):
        if not (docs / required).is_file():
            raise ValueError(f"Missing website source: docs/{required}")
    outputs: dict[PurePosixPath, bytes] = {}
    for file in sorted(docs.rglob("*")):
        if not file.is_file():
            continue
        source = file.relative_to(docs).as_posix()
        if source.startswith("assets/") and file.suffix == ".md":
            continue  # Asset-maintenance notes are not documentation pages.
        if file.suffix == ".md" and not source.startswith("assets/"):
            content = _rewrite_links(file.read_text(encoding="utf-8"), source)
            content = _source_metadata(content, source)
            outputs[_route(source)] = content.encode("utf-8")
        else:
            outputs[_route(source)] = file.read_bytes()
    files = sorted((root / "examples").glob("*.m3ug"), key=lambda p: p.name.casefold())
    if not files:
        raise ValueError("No examples/*.m3ug files found for the generated gallery")
    gallery, archive = _examples(files)
    outputs[PurePosixPath("docs/examples.md")] = gallery.encode("utf-8")
    outputs[PurePosixPath("downloads/genplis-examples.zip")] = archive
    for file in files:
        outputs[PurePosixPath("downloads/examples") / file.name] = file.read_bytes()

    staging = root / ".website-src"
    for path, data in outputs.items():
        destination = staging / path
        destination.parent.mkdir(parents=True, exist_ok=True)
        if not destination.exists() or destination.read_bytes() != data:
            destination.write_bytes(data)
    # Only this fixed, ignored directory is owned by the preparation step.
    for stale in staging.rglob("*"):
        if stale.is_file() and PurePosixPath(stale.relative_to(staging)) not in outputs:
            stale.unlink()


class _HTMLReferences(HTMLParser):
    """Collect local targets and references without a browser dependency."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.ids: set[str] = set()
        self.links: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        for name, value in attrs:
            if not value:
                continue
            if name == "id" or (tag == "a" and name == "name"):
                self.ids.add(value)
            if name in {"href", "src", "poster"}:
                self.links.append(value)
            if name == "srcset":
                self.links.extend(
                    item.strip().split()[0] for item in value.split(",") if item.strip()
                )


def check_site(site: Path, site_url: str) -> None:
    """Reject broken local files, assets, anchors, and project-prefix escapes."""
    base = urlsplit(site_url)
    prefix = base.path.rstrip("/") + "/"
    site = site.resolve()
    if not (site / "index.html").is_file():
        raise ValueError(f"Missing built home page: {site / 'index.html'}")
    pages: dict[Path, _HTMLReferences] = {}
    for file in sorted(site.rglob("*.html")):
        parser = _HTMLReferences()
        parser.feed(file.read_text(encoding="utf-8"))
        pages[file] = parser
    errors: list[str] = []
    for file, page in pages.items():
        current = urljoin(site_url, file.relative_to(site).as_posix())
        for link in page.links:
            target = urlsplit(urljoin(current, link))
            if target.scheme not in {"http", "https"} or target.netloc != base.netloc:
                continue
            path = unquote(target.path)
            if not path.startswith(prefix):
                errors.append(
                    f"{file.relative_to(site)}: {link}: outside the site prefix {prefix}"
                )
                continue
            destination = (site / path[len(prefix) :]).resolve()
            if not destination.is_relative_to(site):
                errors.append(
                    f"{file.relative_to(site)}: {link}: outside the output directory"
                )
                continue
            if destination.is_dir():
                destination /= "index.html"
            if not destination.is_file():
                errors.append(f"{file.relative_to(site)}: {link}: missing file")
            elif target.fragment and destination in pages:
                if unquote(target.fragment) not in pages[destination].ids:
                    errors.append(f"{file.relative_to(site)}: {link}: missing anchor")
    if errors:
        raise ValueError(
            "Website link validation failed:\n" + "\n".join(sorted(set(errors)))
        )
    print(f"Validated {len(pages)} HTML pages, local links, assets, and anchors.")


def _snapshot(root: Path) -> dict[Path, tuple[int, int]]:
    return {
        file: (stat.st_mtime_ns, stat.st_size)
        for directory in ("docs", "examples")
        for file in (root / directory).rglob("*")
        if file.is_file()
        for stat in (file.stat(),)
    }


def _preview(root: Path) -> None:
    """Regenerate original sources as Zensical watches and reloads staged files."""
    snapshot = _snapshot(root)
    command = [sys.executable, "-m", "zensical", "serve"]
    with subprocess.Popen(command, cwd=root) as process:  # noqa: S603
        try:
            while process.poll() is None:
                time.sleep(0.5)
                current = _snapshot(root)
                if current != snapshot:
                    try:
                        prepare_site(root)
                    except (OSError, ValueError) as error:
                        print(f"Website preparation failed: {error}", file=sys.stderr)
                    snapshot = current
        except KeyboardInterrupt:
            pass
        finally:
            if process.poll() is None:
                process.terminate()
            process.wait()
        if process.returncode not in (0, -15, -2, 130):
            raise SystemExit(process.returncode)


def main() -> None:
    """Run the same preparation and validation locally and in GitHub Actions."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "build", "check", "serve"))
    args = parser.parse_args()
    config = tomllib.loads((ROOT / "zensical.toml").read_text())["project"]
    try:
        if args.command != "check":
            prepare_site(ROOT)
        if args.command == "serve":
            _preview(ROOT)
        elif args.command == "build":
            subprocess.run(  # noqa: S603
                [sys.executable, "-m", "zensical", "build", "--clean", "--strict"],
                cwd=ROOT,
                check=True,
            )
        if args.command in {"build", "check"}:
            check_site(ROOT / config["site_dir"], config["site_url"])
    except ValueError as error:
        parser.exit(1, f"{error}\n")


if __name__ == "__main__":
    main()
