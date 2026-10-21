"""Load and validate genplis configuration files."""

import configparser
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

from xdg_base_dirs import xdg_config_home

from .exceptions import GenplisConfigError
from .sorting import DEFAULT_SORT_SPEC, SortSpec, SortSpecError, parse_sort_spec
from .tags import DEFAULT_MAX_TAG_SIZE

CONFIG_FILENAME = "config.ini"

_KNOWN_SECTIONS: Final[dict[str, frozenset[str]]] = {
    "general": frozenset({"verbose", "quiet", "jobs"}),
    "collection": frozenset({"path", "exclude"}),
    "tags": frozenset({"max_size", "ignore"}),
    "database": frozenset({"path"}),
    "output": frozenset({"overwrite", "include_source", "extended_m3u", "sort"}),
}


@dataclass(frozen=True, slots=True)
class GeneralConfig:
    verbose: bool = False
    quiet: bool = False
    jobs: int = 0


@dataclass(frozen=True, slots=True)
class CollectionConfig:
    path: Path | None = None
    exclude: tuple[re.Pattern[str], ...] = ()


@dataclass(frozen=True, slots=True)
class TagsConfig:
    max_size: int = DEFAULT_MAX_TAG_SIZE
    ignore: frozenset[str] = frozenset()


@dataclass(frozen=True, slots=True)
class DatabaseConfig:
    path: Path | None = None


@dataclass(frozen=True, slots=True)
class OutputConfig:
    overwrite: bool = True
    include_source: bool = True
    extended_m3u: bool = True
    sort: SortSpec = DEFAULT_SORT_SPEC


@dataclass(frozen=True, slots=True)
class Config:
    general: GeneralConfig = field(default_factory=GeneralConfig)
    collection: CollectionConfig = field(default_factory=CollectionConfig)
    tags: TagsConfig = field(default_factory=TagsConfig)
    database: DatabaseConfig = field(default_factory=DatabaseConfig)
    output: OutputConfig = field(default_factory=OutputConfig)
    source: Path | None = None


def get_config_path() -> Path:
    """Return the default configuration file path."""
    return xdg_config_home() / "genplis" / CONFIG_FILENAME


def load_config(path: Path | None = None) -> Config:
    """Load configuration from path, or from the XDG default if path is None.

    A missing default file is not an error. A missing explicitly requested
    file is an error, as are malformed files and invalid values.
    """
    explicit_path = path is not None
    config_path = path.expanduser() if path is not None else get_config_path()

    if not config_path.exists():
        if explicit_path:
            raise GenplisConfigError(f"config file not found: {config_path}")
        return Config()

    parser = configparser.ConfigParser(interpolation=None)
    try:
        with config_path.open(encoding="utf-8-sig") as config_file:
            parser.read_file(config_file)
    except configparser.Error as exc:
        raise GenplisConfigError(f"{config_path}: invalid INI: {exc}") from exc
    except UnicodeDecodeError as exc:
        raise GenplisConfigError(f"{config_path}: invalid UTF-8: {exc}") from exc
    except OSError as exc:
        raise GenplisConfigError(f"{config_path}: cannot read file: {exc}") from exc

    sections = _section_names(parser, config_path)
    _validate_sections(parser, sections, config_path)

    general_raw = _get_option(parser, sections, "general", "verbose")
    general_quiet_raw = _get_option(parser, sections, "general", "quiet")
    general_jobs_raw = _get_option(parser, sections, "general", "jobs")
    collection_path_raw = _get_option(parser, sections, "collection", "path")
    collection_exclude_raw = _get_option(parser, sections, "collection", "exclude")
    tags_max_size_raw = _get_option(parser, sections, "tags", "max_size")
    tags_ignore_raw = _get_option(parser, sections, "tags", "ignore")
    database_path_raw = _get_option(parser, sections, "database", "path")
    output_overwrite_raw = _get_option(parser, sections, "output", "overwrite")
    output_include_source_raw = _get_option(
        parser, sections, "output", "include_source"
    )
    output_extended_m3u_raw = _get_option(parser, sections, "output", "extended_m3u")
    output_sort_raw = _get_option(parser, sections, "output", "sort")

    general_verbose = _parse_bool(
        general_raw,
        default=False,
        where=_where(config_path, "general", "verbose"),
    )
    general_quiet = _parse_bool(
        general_quiet_raw,
        default=False,
        where=_where(config_path, "general", "quiet"),
    )
    general_jobs = _parse_int(
        general_jobs_raw,
        default=0,
        minimum=0,
        where=_where(config_path, "general", "jobs"),
    )
    if general_verbose and general_quiet:
        raise GenplisConfigError(
            f"{config_path}: [general] verbose and quiet cannot both be true"
        )

    return Config(
        general=GeneralConfig(
            verbose=general_verbose,
            quiet=general_quiet,
            jobs=general_jobs,
        ),
        collection=CollectionConfig(
            path=_parse_path(
                collection_path_raw,
                default=None,
                config_path=config_path,
                where=_where(config_path, "collection", "path"),
            ),
            exclude=_parse_patterns(
                collection_exclude_raw,
                where=_where(config_path, "collection", "exclude"),
            ),
        ),
        tags=TagsConfig(
            max_size=_parse_int(
                tags_max_size_raw,
                default=DEFAULT_MAX_TAG_SIZE,
                minimum=0,
                where=_where(config_path, "tags", "max_size"),
            ),
            ignore=_parse_names(tags_ignore_raw),
        ),
        database=DatabaseConfig(
            path=_parse_path(
                database_path_raw,
                default=None,
                config_path=config_path,
                where=_where(config_path, "database", "path"),
            )
        ),
        output=OutputConfig(
            overwrite=_parse_bool(
                output_overwrite_raw,
                default=True,
                where=_where(config_path, "output", "overwrite"),
            ),
            include_source=_parse_bool(
                output_include_source_raw,
                default=True,
                where=_where(config_path, "output", "include_source"),
            ),
            extended_m3u=_parse_bool(
                output_extended_m3u_raw,
                default=True,
                where=_where(config_path, "output", "extended_m3u"),
            ),
            sort=_parse_sort(
                output_sort_raw,
                default=DEFAULT_SORT_SPEC,
                where=_where(config_path, "output", "sort"),
            ),
        ),
        source=config_path,
    )


def _section_names(
    parser: configparser.ConfigParser, config_path: Path
) -> dict[str, str]:
    """Return a mapping of lower-case section names to their spelling."""
    sections: dict[str, str] = {}
    for original in parser.sections():
        lower = original.lower()
        if lower in sections:
            raise GenplisConfigError(
                f"{config_path}: duplicate section [{original}] "
                "(section names are case-insensitive)"
            )
        sections[lower] = original
    return sections


def _validate_sections(
    parser: configparser.ConfigParser,
    sections: Mapping[str, str],
    config_path: Path,
) -> None:
    for lower, original in sections.items():
        if lower not in _KNOWN_SECTIONS:
            raise GenplisConfigError(f"{config_path}: unknown section [{original}]")
        allowed = _KNOWN_SECTIONS[lower]
        for option in parser.options(original):
            if option not in allowed:
                raise GenplisConfigError(
                    f"{config_path}: unknown option '{option}' in section [{original}]"
                )


def _get_option(
    parser: configparser.ConfigParser,
    sections: Mapping[str, str],
    section: str,
    option: str,
) -> str | None:
    original = sections.get(section)
    if original is None:
        return None
    return parser.get(original, option, fallback=None)


def _where(config_path: Path, section: str, option: str) -> str:
    return f"{config_path}: [{section}] {option}"


def _parse_bool(raw: str | None, *, default: bool, where: str) -> bool:
    if raw is None:
        return default
    normalized = raw.strip().lower()
    if normalized in {"1", "yes", "true", "on"}:
        return True
    if normalized in {"0", "no", "false", "off"}:
        return False
    raise GenplisConfigError(
        f"{where}: expected a boolean (true/false, yes/no, on/off, 1/0), got {raw!r}"
    )


def _parse_int(raw: str | None, *, default: int, minimum: int, where: str) -> int:
    if raw is None:
        return default
    try:
        value = int(raw.strip())
    except ValueError as exc:
        raise GenplisConfigError(f"{where}: expected an integer, got {raw!r}") from exc
    if value < minimum:
        raise GenplisConfigError(f"{where}: must be at least {minimum}, got {value}")
    return value


def _parse_path(
    raw: str | None,
    *,
    default: Path | None,
    config_path: Path,
    where: str,
) -> Path | None:
    if raw is None:
        return default
    value = raw.strip()
    if not value:
        raise GenplisConfigError(f"{where}: path must not be empty")
    path = Path(value).expanduser()
    if not path.is_absolute():
        # Relative paths in the config are relative to the config file, not
        # to whatever directory genplis happens to be run from.
        path = config_path.parent / path
    return path


def _parse_sort(raw: str | None, *, default: SortSpec, where: str) -> SortSpec:
    if raw is None:
        return default
    try:
        return parse_sort_spec(raw)
    except SortSpecError as exc:
        raise GenplisConfigError(f"{where}: {exc}") from exc


def _parse_patterns(raw: str | None, *, where: str) -> tuple[re.Pattern[str], ...]:
    if raw is None:
        return ()
    patterns: list[re.Pattern[str]] = []
    for line in raw.splitlines():
        value = line.strip()
        if not value:
            continue
        try:
            patterns.append(re.compile(value))
        except re.error as exc:
            raise GenplisConfigError(
                f"{where}: invalid regular expression {value!r}: {exc}"
            ) from exc
    return tuple(patterns)


def _parse_names(raw: str | None) -> frozenset[str]:
    if raw is None:
        return frozenset()
    return frozenset(line.strip().lower() for line in raw.splitlines() if line.strip())
