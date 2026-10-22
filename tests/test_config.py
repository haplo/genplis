import re
from pathlib import Path

import pytest

from genplis.config import (
    CollectionConfig,
    Config,
    GeneralConfig,
    OutputConfig,
    TagsConfig,
    get_config_path,
    load_config,
)
from genplis.exceptions import GenplisConfigError
from genplis.output import Theme
from genplis.sorting import SortKey


def test_get_config_path_uses_xdg_config_home(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))

    assert get_config_path() == tmp_path / "genplis" / "config.ini"


def test_get_config_path_defaults_to_home(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)

    assert get_config_path() == Path.home() / ".config" / "genplis" / "config.ini"


def test_missing_default_config_returns_defaults(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))

    assert load_config() == Config()


def test_missing_explicit_config_raises(tmp_path: Path) -> None:
    with pytest.raises(GenplisConfigError, match="config file not found"):
        load_config(tmp_path / "missing.ini")


def test_empty_config_returns_defaults(tmp_path: Path) -> None:
    config_file = tmp_path / "config.ini"
    config_file.write_text("")

    config = load_config(config_file)

    assert config == Config(source=config_file)


def test_load_full_config(tmp_path: Path) -> None:
    config_file = tmp_path / "config.ini"
    config_file.write_text("""
[general]
verbose = true

[collection]
path = ~/Music
exclude =
    \\.Trash/
    \\.tmp$

[tags]
max_size = 2048
ignore =
    filename
    FILESIZE

[database]
path = cache/genplis.db

[output]
overwrite = false
include_source = false
extended_m3u = false
""")

    config = load_config(config_file)

    assert config.general == GeneralConfig(verbose=True)
    assert config.collection.path == Path.home() / "Music"
    assert [pattern.pattern for pattern in config.collection.exclude] == [
        r"\.Trash/",
        r"\.tmp$",
    ]
    assert config.tags == TagsConfig(
        max_size=2048,
        ignore=frozenset({"filename", "filesize"}),
    )
    assert config.database.path == tmp_path / "cache" / "genplis.db"
    assert config.output == OutputConfig(
        overwrite=False, include_source=False, extended_m3u=False
    )
    assert config.source == config_file


def test_load_quiet_general_config(tmp_path: Path) -> None:
    config_file = tmp_path / "config.ini"
    config_file.write_text("[general]\nquiet = yes\n")

    config = load_config(config_file)

    assert config.general == GeneralConfig(quiet=True)


def test_load_jobs_general_config(tmp_path: Path) -> None:
    config_file = tmp_path / "config.ini"
    config_file.write_text("[general]\njobs = 4\n")

    config = load_config(config_file)

    assert config.general == GeneralConfig(jobs=4)


def test_load_color_and_theme_general_config(tmp_path: Path) -> None:
    config_file = tmp_path / "config.ini"
    config_file.write_text("[general]\ncolor = false\ntheme = light\n")

    config = load_config(config_file)

    assert config.general.color is False
    assert config.general.theme is Theme.LIGHT


def test_theme_defaults_to_auto(tmp_path: Path) -> None:
    config_file = tmp_path / "config.ini"
    config_file.write_text("[general]\n")

    config = load_config(config_file)

    assert config.general.color is True
    assert config.general.theme is Theme.AUTO


def test_reject_verbose_and_quiet_together(tmp_path: Path) -> None:
    config_file = tmp_path / "config.ini"
    config_file.write_text("[general]\nverbose = true\nquiet = true\n")

    with pytest.raises(
        GenplisConfigError, match=r"\[general\] verbose and quiet cannot both be true"
    ):
        load_config(config_file)


def test_examples_config_loads() -> None:
    """The config example linked from the docs must remain valid."""
    examples_dir = Path(__file__).resolve().parent.parent / "examples"
    config_file = examples_dir / "config.ini"

    config = load_config(config_file)

    assert config.general == GeneralConfig(verbose=False)
    assert config.collection.path == Path.home() / "Music"
    assert [pattern.pattern for pattern in config.collection.exclude] == [
        r"/\.Trash/",
        r"/@eaDir/",
        r"\.tmp$",
    ]
    assert config.tags == TagsConfig(
        ignore=frozenset({"comment", "encoder", "encoder_settings", "lyrics"}),
    )
    assert config.database.path is None
    assert config.output == OutputConfig()
    assert config.source == config_file


def test_output_sort_defaults_to_filename() -> None:
    assert OutputConfig().sort == (SortKey("filename"),)


def test_load_output_sort(tmp_path: Path) -> None:
    config_file = tmp_path / "config.ini"
    config_file.write_text("[output]\nsort = artist, album desc\n")

    config = load_config(config_file)

    assert config.output.sort == (
        SortKey("artist"),
        SortKey("album", descending=True),
    )


def test_load_output_sort_with_random(tmp_path: Path) -> None:
    config_file = tmp_path / "config.ini"
    config_file.write_text("[output]\nsort = artist, random 42\n")

    config = load_config(config_file)

    assert config.output.sort == (
        SortKey("artist"),
        SortKey("random", seed=42),
    )


def test_empty_output_sort_disables_ordering(tmp_path: Path) -> None:
    config_file = tmp_path / "config.ini"
    config_file.write_text("[output]\nsort =\n")

    config = load_config(config_file)

    assert config.output.sort == ()


def test_invalid_output_sort_is_an_error(tmp_path: Path) -> None:
    config_file = tmp_path / "config.ini"
    config_file.write_text("[output]\nsort = artist sideways\n")

    with pytest.raises(GenplisConfigError, match=r"\[output\] sort"):
        load_config(config_file)


def test_relative_path_is_relative_to_config_file(tmp_path: Path) -> None:
    config_dir = tmp_path / "genplis"
    config_dir.mkdir()
    config_file = config_dir / "config.ini"
    config_file.write_text("[collection]\npath = music\n")

    config = load_config(config_file)

    assert config.collection.path == config_dir / "music"


def test_sections_and_options_are_case_insensitive(tmp_path: Path) -> None:
    config_file = tmp_path / "config.ini"
    config_file.write_text("""
[Collection]
PATH = /music

[Tags]
MAX_SIZE = 42
""")

    config = load_config(config_file)

    assert config.collection == CollectionConfig(path=Path("/music"))
    assert config.tags.max_size == 42


def test_percent_sign_is_literal(tmp_path: Path) -> None:
    config_file = tmp_path / "config.ini"
    config_file.write_text("[collection]\nexclude =\n    /100%/\n")

    config = load_config(config_file)

    assert [pattern.pattern for pattern in config.collection.exclude] == ["/100%/"]


@pytest.mark.parametrize(
    ("content", "match"),
    [
        ("[unknown]\nkey = value\n", "unknown section"),
        ("[collection]\nexlude = value\n", "unknown option"),
        ("[tags]\nmax_size = many\n", "expected an integer"),
        ("[tags]\nmax_size = -1\n", "at least 0"),
        ("[general]\njobs = many\n", "expected an integer"),
        ("[general]\njobs = -1\n", "at least 0"),
        ("[general]\ncolor = maybe\n", "expected a boolean"),
        ("[general]\ntheme = neon\n", "expected one of"),
        ("[output]\noverwrite = maybe\n", "expected a boolean"),
        ("[output]\ninclude_source = maybe\n", "expected a boolean"),
        ("[output]\nextended_m3u = maybe\n", "expected a boolean"),
        ("[collection]\nexclude = [\n", "invalid regular expression"),
        ("[collection\npath = /music\n", "invalid INI"),
        (
            "[tags]\nmax_size = 1\n[Tags]\nmax_size = 2\n",
            "duplicate section",
        ),
        ("[tags]\nmax_size = 1\nmax_size = 2\n", "invalid INI"),
    ],
)
def test_invalid_config(tmp_path: Path, content: str, match: str) -> None:
    config_file = tmp_path / "config.ini"
    config_file.write_text(content)

    with pytest.raises(GenplisConfigError, match=match):
        load_config(config_file)


def test_empty_path_is_rejected(tmp_path: Path) -> None:
    config_file = tmp_path / "config.ini"
    config_file.write_text("[collection]\npath =   \n")

    with pytest.raises(GenplisConfigError, match="must not be empty"):
        load_config(config_file)


def test_invalid_utf8_is_rejected(tmp_path: Path) -> None:
    config_file = tmp_path / "config.ini"
    config_file.write_bytes(b"\xff")

    with pytest.raises(GenplisConfigError, match="invalid UTF-8"):
        load_config(config_file)


def test_exclude_patterns_are_not_split_on_commas(tmp_path: Path) -> None:
    config_file = tmp_path / "config.ini"
    config_file.write_text("[collection]\nexclude =\n    /a{1,2}/\n")

    config = load_config(config_file)

    assert [pattern.pattern for pattern in config.collection.exclude] == ["/a{1,2}/"]


def test_empty_ignore_lines_are_dropped(tmp_path: Path) -> None:
    config_file = tmp_path / "config.ini"
    config_file.write_text("[tags]\nignore =\n    filename\n\n    filesize\n")

    config = load_config(config_file)

    assert config.tags.ignore == frozenset({"filename", "filesize"})


def test_regex_search_matches_paths(tmp_path: Path) -> None:
    config_file = tmp_path / "config.ini"
    config_file.write_text("[collection]\nexclude =\n    \\.tmp$\n")

    config = load_config(config_file)

    assert any(
        pattern.search("/music/song.tmp") for pattern in config.collection.exclude
    )
    assert not any(
        pattern.search("/music/song.mp3") for pattern in config.collection.exclude
    )


def test_exclude_regex_is_compiled(tmp_path: Path) -> None:
    config_file = tmp_path / "config.ini"
    config_file.write_text("[collection]\nexclude = from-config\n")

    config = load_config(config_file)

    assert all(isinstance(pattern, re.Pattern) for pattern in config.collection.exclude)
