"""The portable skill installs safely without touching a music collection."""

import re
import sys
import tomllib
from importlib.resources import files
from pathlib import Path

import pytest

from genplis.core import main
from genplis.exceptions import GenplisError
from genplis.m3ug import parse_m3ug
from genplis.skill import install_skill
from scripts.sync_skill import skill_payload


@pytest.fixture
def skill_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Keep all installation writes in a test-owned home directory."""
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    return tmp_path


@pytest.mark.parametrize("target", ["agents", "claude"])
def test_install_skill_copies_packaged_resources(skill_home: Path, target: str) -> None:
    destination = install_skill(target)
    assert destination == skill_home / f".{target}" / "skills" / "genplis"
    resource = files("genplis").joinpath("skills", "genplis")
    assert (destination / "SKILL.md").read_bytes() == resource.joinpath(
        "SKILL.md"
    ).read_bytes()
    assert (destination / "references/m3ug.md").read_bytes() == resource.joinpath(
        "references", "m3ug.md"
    ).read_bytes()
    assert sorted(path.name for path in (destination / "references").iterdir()) == [
        "m3ug.md",
        "tags.md",
        "usage.md",
    ]


def test_install_skill_is_idempotent_and_preserves_extra_files(
    skill_home: Path,
) -> None:
    destination = install_skill()
    skill = destination / "SKILL.md"
    mtime = skill.stat().st_mtime_ns
    extra = destination / "notes.txt"
    extra.write_text("Personal notes", encoding="utf-8")

    assert install_skill() == destination
    assert skill.stat().st_mtime_ns == mtime
    assert extra.read_text() == "Personal notes"


def test_install_skill_refuses_changes_before_writing_anything(
    skill_home: Path,
) -> None:
    destination = install_skill()
    skill = destination / "SKILL.md"
    reference = destination / "references/tags.md"
    skill.unlink()
    reference.write_text("Customized reference", encoding="utf-8")

    with pytest.raises(GenplisError, match="--force"):
        install_skill()

    assert not skill.exists()
    assert reference.read_text() == "Customized reference"


def test_force_replaces_only_bundled_files(skill_home: Path) -> None:
    destination = install_skill()
    skill = destination / "SKILL.md"
    expected = skill.read_bytes()
    skill.write_text("Custom skill", encoding="utf-8")
    (destination / "notes.txt").write_text("Keep me", encoding="utf-8")

    assert install_skill(force=True) == destination
    assert skill.read_bytes() == expected
    assert (destination / "notes.txt").read_text() == "Keep me"


@pytest.mark.parametrize(
    "relative", [".", "SKILL.md", "references", "references/tags.md"]
)
@pytest.mark.parametrize("force", [False, True])
def test_install_skill_refuses_symlinks(
    skill_home: Path, relative: str, force: bool
) -> None:
    destination = install_skill()
    original = destination / relative
    outside = skill_home / "outside"
    original.rename(outside)
    original.symlink_to(outside, target_is_directory=outside.is_dir())
    before = (
        (outside / "SKILL.md").read_bytes()
        if relative == "."
        else outside.read_bytes()
        if outside.is_file()
        else (outside / "tags.md").read_bytes()
    )

    with pytest.raises(GenplisError, match="symbolic link"):
        install_skill(force=force)

    assert original.is_symlink()
    after = (
        (outside / "SKILL.md").read_bytes()
        if relative == "."
        else outside.read_bytes()
        if outside.is_file()
        else (outside / "tags.md").read_bytes()
    )
    assert after == before


@pytest.mark.parametrize("relative", [".", "references"])
def test_install_skill_refuses_file_in_place_of_directory(
    skill_home: Path, relative: str
) -> None:
    destination = skill_home / ".agents/skills/genplis"
    collision = destination / relative
    collision.parent.mkdir(parents=True, exist_ok=True)
    collision.write_text("Unrelated file", encoding="utf-8")

    with pytest.raises(GenplisError, match="directory"):
        install_skill(force=True)

    assert collision.read_text() == "Unrelated file"


def test_install_skill_refuses_directory_in_place_of_file(skill_home: Path) -> None:
    destination = skill_home / ".agents/skills/genplis"
    collision = destination / "SKILL.md"
    collision.mkdir(parents=True)
    (collision / "notes").write_text("Keep me", encoding="utf-8")

    with pytest.raises(GenplisError, match="regular file"):
        install_skill(force=True)

    assert (collision / "notes").read_text() == "Keep me"


def test_install_skill_refuses_broken_symlink(skill_home: Path) -> None:
    destination = skill_home / ".agents/skills/genplis"
    destination.parent.mkdir(parents=True)
    destination.symlink_to(skill_home / "missing", target_is_directory=True)
    with pytest.raises(GenplisError, match="symbolic link"):
        install_skill(force=True)
    assert not (skill_home / "missing").exists()


def test_install_skill_rejects_unknown_target(skill_home: Path) -> None:
    with pytest.raises(GenplisError, match="Unknown skill target"):
        install_skill("unknown")
    assert not list(skill_home.iterdir())


def test_install_skill_reports_filesystem_errors(
    skill_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def denied(*_args: object, **_kwargs: object) -> None:
        raise PermissionError("Permission denied")

    monkeypatch.setattr(Path, "mkdir", denied)
    with pytest.raises(GenplisError, match=r"Cannot install skill.*Permission denied"):
        install_skill()


@pytest.mark.parametrize("target", [None, "agents", "claude"])
def test_cli_installs_without_config_or_cache(
    skill_home: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    target: str | None,
) -> None:
    def unexpected(*_args: object, **_kwargs: object) -> None:
        raise AssertionError(
            "Skill installation must not load config or open the cache"
        )

    monkeypatch.setattr("genplis.core.load_config", unexpected)
    monkeypatch.setattr("genplis.core.db.setup_database_connection", unexpected)
    argv = ["genplis", "--install-skill"]
    if target:
        argv.append(target)
    monkeypatch.setattr(sys, "argv", argv)
    main()

    destination = skill_home / f".{target or 'agents'}" / "skills/genplis"
    assert (destination / "SKILL.md").is_file()
    output = capsys.readouterr().out
    assert str(destination) in output
    assert "genplis" in output
    assert "restart" in output.lower()


def test_cli_force_updates_skill(
    skill_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    destination = install_skill()
    (destination / "SKILL.md").write_text("Old skill", encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["genplis", "--install-skill", "--force"])
    main()
    assert (destination / "SKILL.md").read_text().startswith("---\nname: genplis\n")


@pytest.mark.parametrize(
    "arguments",
    [
        ["--force"],
        ["--install-skill", "unknown"],
        ["--install-skill", "agents", "music"],
        ["--install-skill", "--show-rules"],
        ["--install-skill", "--tag-stats"],
        ["--install-skill", "--filter", "mix.m3ug"],
        ["--install-skill", "--config", "missing.ini"],
        ["--install-skill", "--db", "cache.db"],
        ["--install-skill", "--no-overwrite"],
    ],
)
def test_cli_rejects_conflicting_options_without_installing(
    skill_home: Path, monkeypatch: pytest.MonkeyPatch, arguments: list[str]
) -> None:
    monkeypatch.setattr(sys, "argv", ["genplis", *arguments])
    with pytest.raises(SystemExit) as exc_info:
        main()
    assert exc_info.value.code == 2
    assert not list(skill_home.iterdir())


def test_cli_reports_existing_skill_conflict(
    skill_home: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    destination = install_skill()
    (destination / "SKILL.md").write_text("Customized", encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["genplis", "--install-skill"])
    with pytest.raises(SystemExit) as exc_info:
        main()
    assert exc_info.value.code == 1
    assert "--force" in capsys.readouterr().err
    assert (destination / "SKILL.md").read_text() == "Customized"


def test_cli_quiet_install(
    skill_home: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(sys, "argv", ["genplis", "--install-skill=claude", "-qq"])
    main()
    assert (skill_home / ".claude/skills/genplis/SKILL.md").is_file()
    assert capsys.readouterr().out == ""


def test_skill_generator_rewrites_links_and_adds_version(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text('[project]\nversion = "1.2.3"\n')
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "agent-instructions.md").write_text(
        "---\nname: genplis\n---\n\n[Language](m3ug.md#syntax)\n",
        encoding="utf-8",
    )
    for name in ("m3ug.md", "tags.md", "usage.md"):
        (docs / name).write_text(
            "[Tags](tags.md#rating)\n[Config\nsettings](config.md#sort)\n"
            "[Online](https://example.com/config.md)\n",
            encoding="utf-8",
        )
    payload = skill_payload(tmp_path)
    assert payload[Path("SKILL.md")] == (
        b'---\nname: genplis\nmetadata:\n  genplis-version: "1.2.3"\n---\n\n'
        b"[Language](references/m3ug.md#syntax)\n"
    )
    assert payload[Path("references/tags.md")] == (
        b"[Tags](tags.md#rating)\n"
        b"[Config\nsettings](https://github.com/haplo/genplis/blob/main/docs/config.md#sort)\n"
        b"[Online](https://example.com/config.md)\n"
    )


def test_packaged_skill_matches_documentation() -> None:
    root = Path(__file__).resolve().parents[1]
    resource = root / "src/genplis/skills/genplis"
    expected = skill_payload(root)
    actual = {
        path.relative_to(resource): path.read_bytes()
        for path in resource.rglob("*")
        if path.is_file()
    }
    assert actual == expected, "Run uv run python scripts/sync_skill.py"
    for relative, data in actual.items():
        for target in re.findall(r"\]\(([^)]+)\)", data.decode("utf-8")):
            name = target.split("#", 1)[0]
            if name.endswith(".md") and "://" not in name:
                assert relative.parent / name in actual, f"Unbundled link: {target}"
    skill = actual[Path("SKILL.md")].decode("utf-8")
    assert skill.startswith("---\nname: genplis\ndescription:")
    version = tomllib.loads((root / "pyproject.toml").read_text())["project"]["version"]
    assert f'genplis-version: "{version}"' in skill
    assert len(skill.splitlines()) < 500
    assert "](references/m3ug.md" in skill
    assert "](config.md" not in actual[Path("references/m3ug.md")].decode("utf-8")
    assert "https://github.com/haplo/genplis/blob/main/docs/config.md" in actual[
        Path("references/m3ug.md")
    ].decode("utf-8")


def test_skill_examples_use_supported_syntax_and_rules() -> None:
    skill = (
        files("genplis")
        .joinpath("skills", "genplis", "SKILL.md")
        .read_text(encoding="utf-8")
    )
    examples = re.findall(r"```m3ug\n(.*?)```", skill, flags=re.DOTALL)
    assert len(examples) == 2
    favorites, eighties = [parse_m3ug(example, "SKILL.md") for example in examples]
    assert favorites.expression is not None
    assert favorites.expression.apply(
        {"genre": ["Heavy Metal"], "fmps_rating": ["0.9"]}
    )
    assert not favorites.expression.apply({"genre": ["Metal"]})
    assert not favorites.expression.apply({"genre": ["Pop"], "fmps_rating": ["1.0"]})
    assert favorites.max_duration == 3600
    assert favorites.limit_per is not None
    assert favorites.limit_per.count == 3
    assert eighties.expression is not None
    assert eighties.expression.apply({"year": ["1985"], "title": ["Studio version"]})
    assert not eighties.expression.apply(
        {"year": ["1990"], "title": ["Studio version"]}
    )
    assert not eighties.expression.apply(
        {"year": ["1985"], "title": ["Live in London"]}
    )
