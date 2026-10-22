import argparse
import os
import random
import re
import sqlite3
import sys
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, replace
from enum import Enum, auto
from functools import cmp_to_key
from pathlib import Path
from timeit import default_timer as timer

import psutil

from . import db
from .config import Config, load_config
from .diagnostics import (
    FileTrace,
    FilterSelectionTrace,
    PlaylistInput,
    SelectionTrace,
    format_file_trace,
    format_filter_tree,
    format_playlist_input,
    format_selection_trace,
    format_tags_consulted,
    trace_file,
)
from .exceptions import GenplisConfigError, GenplisError
from .executors import (
    ParseItem,
    ProcessExecutor,
    auto_workers,
    make_executor,
)
from .m3u import PlaylistEntry, create_m3u, duration_seconds, playlist_entry
from .m3ug import (
    EvaluationTags,
    FilterNode,
    LimitPerTag,
    M3UGFile,
    NameNode,
    PredicateCache,
    get_rating,
    parse_m3ug,
)
from .output import ColorRole, Output, Palette, Progress, Theme
from .sorting import (
    SortSpec,
    SortValue,
    SortValues,
    compare_sort_values,
    format_sort_spec,
    normalize_sort_value,
)
from .stats import (
    TagStatsCollector,
    full_tag_names,
    render_tag_details,
    render_tag_stats,
)
from .tags import (
    AUDIO_PROPERTY_TAGS,
    format_tag_diagnostic,
    get_audio_property_tags,
    get_tags,
    is_supported_file,
)
from .types import Tags, TagValue, Verbosity

# User-facing description of each cache state.
CACHE_STATUS_MESSAGES = {
    db.CacheStatus.MISS: "not present",
    db.CacheStatus.STALE: "stale",
    db.CacheStatus.HIT: "valid",
}

_CACHE_STATUS_ROLES = {
    db.CacheStatus.MISS: ColorRole.SOURCE,
    db.CacheStatus.STALE: ColorRole.WARNING,
    db.CacheStatus.HIT: ColorRole.PASS,
}


def _format_cache_status(
    cache_status: db.CacheStatus,
    palette: Palette,
) -> str:
    """Render a cache state with a semantic color."""
    return palette.paint(
        _CACHE_STATUS_ROLES[cache_status],
        CACHE_STATUS_MESSAGES[cache_status],
    )


# Commit cache writes every N rows during a directory scan. Benchmarked on a
# 50k-file cold scan: 128 was within 0.7% of the best median and far ahead of
# committing after every write.
COMMIT_EVERY = 128


class Mode(Enum):
    """The primary operation selected on the command line."""

    PROCESS = auto()
    TAG_STATS = auto()
    SHOW_RULES = auto()
    TRACE = auto()
    TRACE_FULL = auto()


@dataclass(frozen=True, slots=True)
class Args:
    path: Path | None
    exclude: tuple[re.Pattern[str], ...]
    verbosity: Verbosity
    overwrite: bool
    db_path: Path
    config: Config
    include_source: bool = True
    extended_m3u: bool = True
    clean: bool = False
    config_disabled: bool = False
    jobs: int = 1
    mode: Mode = Mode.PROCESS
    tags: tuple[str, ...] = ()
    trace_path: Path | None = None
    filters: tuple[Path, ...] = ()
    color: bool | None = None
    theme: Theme = Theme.AUTO


@dataclass(frozen=True, slots=True)
class Match:
    """A matching playlist entry with its keys and walk position."""

    order: int
    entry: Path | PlaylistEntry
    sort_values: SortValues = ()
    duration: float | None = None
    dedupe_values: SortValues = ()
    limit_key: SortValue | None = None


@dataclass(frozen=True, slots=True)
class CleanStats:
    """Result of a cache cleaning operation."""

    removed: tuple[Path, ...]
    size_before: int
    size_after: int

    @property
    def bytes_saved(self) -> int:
        """Return how many bytes the database shrank."""
        return max(0, self.size_before - self.size_after)


_SIZE_UNITS = ("B", "KiB", "MiB", "GiB", "TiB")


def format_size(size: int) -> str:
    """Format a byte count using binary units."""
    value = float(size)
    for unit in _SIZE_UNITS[:-1]:
        if value < 1024:
            return f"{int(value)} B" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} {_SIZE_UNITS[-1]}"


def regex_type(arg_value: str) -> re.Pattern[str]:
    """"""
    return re.compile(arg_value)


def non_negative_int(arg_value: str) -> int:
    """Parse a command-line integer that must be zero or greater."""
    try:
        value = int(arg_value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"expected an integer, got {arg_value!r}"
        ) from exc
    if value < 0:
        raise argparse.ArgumentTypeError(f"must be at least 0, got {value}")
    return value


def setup_argparse() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate music playlists from your own filters."
    )
    parser.add_argument(
        "path",
        nargs="?",
        type=Path,
        help=(
            "Path to parse (directory with music collection or individual file). "
            "Defaults to [collection] path from the config file."
        ),
        metavar="PATH",
    )
    parser.add_argument(
        "-e",
        "--exclude",
        help=(
            "Exclude files matching this regex. Replaces the config file's "
            "exclude list when used."
        ),
        action="append",
        default=None,
        type=regex_type,
    )

    config_group = parser.add_mutually_exclusive_group()
    config_group.add_argument(
        "--config",
        help="Read settings from this file instead of the XDG default",
        type=Path,
        metavar="FILE",
    )
    config_group.add_argument(
        "--no-config",
        help="Do not read any configuration file",
        action="store_true",
    )

    parser.add_argument(
        "-v",
        "--verbose",
        help="Print verbose diagnostics",
        action=argparse.BooleanOptionalAction,
        default=None,
    )
    parser.add_argument(
        "-q",
        "--quiet",
        help=(
            "Reduce output. Repeat (-qq) to print nothing except errors. "
            "Cannot be combined with --verbose."
        ),
        action="count",
        default=0,
    )
    parser.add_argument(
        "--color",
        help=(
            "Force colored output. Use --no-color to disable it; by default "
            "color follows the terminal and the config file."
        ),
        action=argparse.BooleanOptionalAction,
        default=None,
    )
    parser.add_argument(
        "--theme",
        help="Color theme for the terminal background",
        choices=[theme.value for theme in Theme],
        default=None,
        metavar="THEME",
    )
    parser.add_argument(
        "--db",
        help="Use this database file instead of the XDG cache default",
        type=Path,
        metavar="PATH",
    )
    parser.add_argument(
        "-f",
        "--filter",
        dest="filters",
        help=(
            "Process only this .m3ug filter. PATH (or the configured "
            "collection) is the scan root. May be repeated."
        ),
        action="append",
        default=None,
        type=Path,
        metavar="FILE",
    )
    parser.add_argument(
        "-j",
        "--jobs",
        help=(
            "Parse cache misses with N worker processes "
            "(0 = one per CPU, capped at 8; 1 = no pool)"
        ),
        type=non_negative_int,
        default=None,
        metavar="N",
    )
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument(
        "--clean",
        help=(
            "Remove cache entries for files that no longer exist. With a "
            "directory PATH, process it normally first and clean only entries "
            "under it; without PATH, clean the whole database."
        ),
        action="store_true",
    )
    mode_group.add_argument(
        "--show-rules",
        help=(
            "Parse .m3ug files and print their rule trees without scanning "
            "audio or writing playlists."
        ),
        action="store_true",
    )
    mode_group.add_argument(
        "--trace",
        dest="trace_path",
        type=Path,
        metavar="SONG",
        help=(
            "Trace how every selected filter evaluates SONG. No playlists are written."
        ),
    )
    mode_group.add_argument(
        "--trace-full",
        dest="trace_full_path",
        type=Path,
        metavar="SONG",
        help=(
            "Trace SONG and simulate its exact playlist selection. No "
            "playlists are written."
        ),
    )
    mode_group.add_argument(
        "--tag-stats",
        dest="tag_stats",
        help=(
            "Show every tag found in the collection with file counts. "
            "No playlists are written."
        ),
        action="store_true",
    )
    parser.add_argument(
        "-t",
        "--tag",
        dest="tags",
        help=(
            "Show every distinct value of TAG with file counts. Implies "
            "--tag-stats and may be repeated."
        ),
        action="append",
        default=None,
        metavar="TAG",
    )
    parser.add_argument(
        "--overwrite",
        help="Overwrite existing generated playlists",
        action=argparse.BooleanOptionalAction,
        default=None,
    )
    parser.add_argument(
        "--include-source",
        help="Embed the M3UG filter source as comments in generated playlists",
        action=argparse.BooleanOptionalAction,
        default=None,
    )
    parser.add_argument(
        "--extended-m3u",
        help="Write #EXTM3U and #EXTINF metadata (artist, title, duration)",
        action=argparse.BooleanOptionalAction,
        default=None,
    )
    return parser


def _resolve_verbosity(args: argparse.Namespace, config: Config) -> Verbosity:
    """Combine command-line and config output settings.

    Command-line verbosity flags override the config file. A quiet flag and a
    verbose flag from the same source are rejected before this is called.
    """
    if args.quiet:
        return Verbosity.REALLY_QUIET if args.quiet >= 2 else Verbosity.QUIET
    if args.verbose:
        return Verbosity.VERBOSE
    if config.general.quiet:
        return Verbosity.QUIET
    if args.verbose is False:
        return Verbosity.NORMAL
    if config.general.verbose:
        return Verbosity.VERBOSE
    return Verbosity.NORMAL


def _resolve_jobs(args: argparse.Namespace, config: Config) -> int:
    """Resolve the worker count from the CLI, config, or CPU count."""
    raw_jobs = args.jobs if args.jobs is not None else config.general.jobs
    if raw_jobs < 0:
        raise GenplisConfigError(f"jobs must be at least 0, got {raw_jobs}")
    return auto_workers() if raw_jobs == 0 else raw_jobs


def _normalize_filters(raw_filters: Sequence[Path] | None) -> tuple[Path, ...]:
    """Expand, validate and deduplicate filters selected with --filter."""
    filters: list[Path] = []
    for raw_path in raw_filters or ():
        filter_path = raw_path.expanduser()
        if filter_path.suffix.lower() != ".m3ug":
            raise GenplisConfigError(
                f"--filter expects a .m3ug file, got {filter_path}"
            )
        if not filter_path.is_file():
            raise GenplisConfigError(f"filter file not found: {filter_path}")
        filters.append(filter_path)
    return tuple(dict.fromkeys(filters))


def resolve_args(args: argparse.Namespace, config: Config) -> Args:
    """Combine command-line arguments with configuration file values.

    Command-line values take precedence. Excludes are special: when any
    --exclude option is present, it replaces the config file's exclude list.
    """
    if args.clean and args.tags:
        raise GenplisConfigError("--tag cannot be combined with --clean")
    if args.clean and args.filters:
        raise GenplisConfigError("--filter cannot be combined with --clean")
    if args.show_rules and args.tags:
        raise GenplisConfigError("--tag cannot be combined with --show-rules")
    if (args.trace_path is not None or args.trace_full_path is not None) and args.tags:
        raise GenplisConfigError(
            "--tag cannot be combined with --trace or --trace-full"
        )
    if args.filters and (args.tag_stats or args.tags):
        raise GenplisConfigError(
            "--filter cannot be combined with --tag-stats or --tag"
        )

    requested_tags: list[str] = []
    for raw_tag in args.tags or ():
        name = raw_tag.strip().lower()
        if not name:
            raise GenplisConfigError("tag name must not be empty")
        requested_tags.append(name)
    tags = tuple(dict.fromkeys(requested_tags))
    raw_trace_path = (
        args.trace_path if args.trace_path is not None else args.trace_full_path
    )
    if args.show_rules:
        mode = Mode.SHOW_RULES
    elif args.trace_full_path is not None:
        mode = Mode.TRACE_FULL
    elif args.trace_path is not None:
        mode = Mode.TRACE
    elif args.tag_stats or tags:
        mode = Mode.TAG_STATS
    else:
        mode = Mode.PROCESS
    trace_path = raw_trace_path.expanduser() if raw_trace_path is not None else None
    filters = _normalize_filters(args.filters)

    if args.path is not None:
        path = args.path
    elif args.clean:
        # Cleaning without a CLI path removes entries from the whole database,
        # even when a collection path is configured.
        path = None
    elif config.collection.path is not None:
        path = config.collection.path
    elif mode is Mode.SHOW_RULES and filters:
        # Showing selected filters does not need a scan root.
        path = None
    else:
        raise GenplisConfigError(
            "PATH is required unless [collection] path is set in the config file"
        )

    if path is not None and not path.is_dir():
        if args.clean:
            raise GenplisConfigError(f"--clean requires a directory, got {path}")
        if path.suffix.lower() == ".m3ug":
            if mode is Mode.TAG_STATS:
                raise GenplisConfigError(
                    f"{path} is a .m3ug filter; --tag-stats requires a directory "
                    "or an audio file"
                )
            raise GenplisConfigError(
                f"{path} is a .m3ug filter; pass the collection directory as PATH "
                "and use --filter FILE to process that filter"
            )
    if filters and path is not None and path.exists() and not path.is_dir():
        raise GenplisConfigError(
            f"PATH must be a directory when --filter is used, got {path}"
        )

    exclude = (
        tuple(args.exclude) if args.exclude is not None else config.collection.exclude
    )
    verbosity = _resolve_verbosity(args, config)
    color = (
        args.color
        if args.color is not None
        else (None if config.general.color else False)
    )
    theme = Theme(args.theme) if args.theme is not None else config.general.theme
    overwrite = (
        args.overwrite if args.overwrite is not None else config.output.overwrite
    )
    include_source = (
        args.include_source
        if args.include_source is not None
        else config.output.include_source
    )
    extended_m3u = (
        args.extended_m3u
        if args.extended_m3u is not None
        else config.output.extended_m3u
    )
    raw_db_path = args.db if args.db is not None else config.database.path
    if raw_db_path is not None:
        raw_db_path = raw_db_path.expanduser()
    db_path = db.get_db_path(raw_db_path)

    return Args(
        path=path,
        exclude=exclude,
        verbosity=verbosity,
        overwrite=overwrite,
        db_path=db_path,
        config=config,
        include_source=include_source,
        extended_m3u=extended_m3u,
        clean=args.clean,
        config_disabled=args.no_config,
        jobs=_resolve_jobs(args, config),
        mode=mode,
        tags=tags,
        trace_path=trace_path,
        filters=filters,
        color=color,
        theme=theme,
    )


def is_excluded(path: Path, args: Args, *, is_dir: bool = False) -> bool:
    """Return whether any exclude pattern matches the given path.

    Directory paths are also matched with a trailing separator so that
    patterns written for folders (e.g. ``/@eaDir/``) match the folder itself
    and not just the files inside it.
    """
    text = str(path)
    candidates = (text, text + os.sep) if is_dir else (text,)
    return any(
        pattern.search(candidate)
        for pattern in args.exclude
        for candidate in candidates
    )


def get_calculated_tags(tags: Mapping[str, TagValue]) -> Tags:
    """Return calculated tags for display.

    Calculated tag names are prefixed with ``*`` to distinguish them from
    tags that are embedded in the original file.
    """
    calculated = get_audio_property_tags(tags)
    rating = get_rating(tags)
    if rating is not None:
        calculated["*rating"] = rating
    return calculated


def _select_requested_tags(
    tag_values: Mapping[str, TagValue],
    requested: Sequence[str],
) -> tuple[Tags, tuple[str, ...]]:
    """Limit displayed tags to the requested names and report misses."""
    names = tuple(
        dict.fromkeys(name.strip().lower() for name in requested if name.strip())
    )
    wanted: set[str] = set()
    for name in names:
        wanted.add(name)
        if not name.startswith("*"):
            wanted.add(f"*{name}")

    selected: Tags = {
        key: value for key, value in tag_values.items() if key.lower() in wanted
    }
    found: set[str] = set()
    for key in selected:
        lowered = key.lower()
        found.add(lowered)
        if lowered.startswith("*"):
            found.add(lowered[1:])
    missing = tuple(name for name in names if name not in found)
    return selected, missing


def display_file_tags(
    path: Path,
    tags: Mapping[str, TagValue],
    cache_status: db.CacheStatus,
    requested: Sequence[str] = (),
    output: Output | None = None,
) -> None:
    """Print the tags of a single music file, optionally filtered by name."""
    out = Output.plain() if output is None else output
    palette = out.palette
    out.line(f"{palette.title(str(path))} detected as music file")
    out.line(f"Cache status: {_format_cache_status(cache_status, palette)}")
    out.line(palette.title("Parsed tags:"))
    shown_tags: Tags = {
        key: value for key, value in tags.items() if key not in AUDIO_PROPERTY_TAGS
    }
    shown_tags.update(get_calculated_tags(tags))
    missing: tuple[str, ...] = ()
    if requested:
        shown_tags, missing = _select_requested_tags(shown_tags, requested)
    for key, value in sorted(shown_tags.items(), key=lambda tag: tag[0]):
        out.line(f"    {palette.tag(key)} = {palette.value(str(value))}")
    for name in missing:
        out.line(
            f"Tag '{palette.tag(name)}' {palette.warning('was not found.')} "
            f"{palette.source('It may be hidden by [tags] ignore.')}"
        )


def _parse_filter_file(
    filter_file: Path,
    args: Args,
    output: Output | None = None,
) -> M3UGFile:
    """Parse one .m3ug filter without touching the cache."""
    if filter_file.suffix.lower() != ".m3ug":
        raise GenplisError(f"{filter_file} is not a .m3ug filter")
    if not filter_file.is_file():
        raise GenplisError(f"filter file not found: {filter_file}")
    return parse_m3ug(
        filter_file.read_text(encoding="utf-8-sig"),
        str(filter_file),
        args.verbosity,
        output=output,
    )


def _parse_selected_filters(
    args: Args,
    output: Output,
) -> dict[Path, M3UGFile] | None:
    """Parse the filters selected with --filter and show their rule trees."""
    if not args.filters:
        return None

    parsed_filters: dict[Path, M3UGFile] = {}
    for filter_file in args.filters:
        parsed = _parse_filter_file(filter_file, args, output)
        parsed_filters[filter_file] = parsed
        if args.verbosity.shows_normal_output:
            output.line(
                format_filter_tree(
                    parsed,
                    title=f"{filter_file} detected as M3UG file",
                    default_sort=args.config.output.sort,
                    palette=output.palette,
                )
            )
            if is_excluded(filter_file, args):
                output.line(
                    output.palette.warning(
                        "WARNING: This file is excluded by current configuration."
                    )
                )
    return parsed_filters


def process_path(
    conn: sqlite3.Connection,
    cursor: sqlite3.Cursor,
    args: Args,
    output: Output | None = None,
) -> None:
    """Process an arbitrary path through genplis.

    It will use process_file or process_directory depending on the type of the path.

    """
    out = Output.plain() if output is None else output
    path = args.path
    if path is None:
        raise GenplisError("Attempted to process a path but none was given")
    if args.filters and path.exists() and not path.is_dir():
        raise GenplisError("PATH must be a directory when --filter is used")

    if path.is_dir():
        process_directory(
            conn,
            cursor,
            path,
            args,
            filters=_parse_selected_filters(args, out),
            output=out,
        )
    elif path.is_file():
        if path.suffix.lower() == ".m3ug":
            raise GenplisError(
                f"{path} is a .m3ug filter; pass the collection directory as "
                "PATH and use --filter FILE to process that filter"
            )
        tags, _, cache_status = process_file(conn, cursor, path, args, output=out)
        if tags is not None and args.verbosity.shows_normal_output:
            display_file_tags(path, tags, cache_status, output=out)
        if is_excluded(path, args) and args.verbosity.shows_normal_output:
            out.line(
                out.palette.warning(
                    "WARNING: This file is excluded by current configuration."
                )
            )
    else:
        raise GenplisError(f"{path} must be either a directory or a file.")


def show_rules(args: Args, output: Output | None = None) -> None:
    """Print parsed rule trees without touching the cache or audio files."""
    out = Output.plain() if output is None else output
    if args.filters:
        for filter_file in args.filters:
            parsed = _parse_filter_file(filter_file, args, out)
            if args.verbosity is not Verbosity.REALLY_QUIET:
                out.line(
                    format_filter_tree(
                        parsed,
                        title=str(filter_file),
                        default_sort=args.config.output.sort,
                        palette=out.palette,
                    )
                )
        return

    if args.path is None:
        raise GenplisError("Attempted to show rules but no path or --filter was given")
    path = args.path.expanduser()
    if not path.is_dir():
        raise GenplisError(
            f"{path} must be a directory; use --filter FILE to show a single "
            ".m3ug filter"
        )

    found = 0
    for filter_file in _walk_files(path, args, report_skips=False, only_m3ug=True):
        parsed = parse_m3ug(
            filter_file.read_text(encoding="utf-8-sig"),
            str(filter_file),
            args.verbosity,
            output=out,
        )
        if args.verbosity is not Verbosity.REALLY_QUIET:
            out.line(
                format_filter_tree(
                    parsed,
                    title=str(filter_file),
                    default_sort=args.config.output.sort,
                    palette=out.palette,
                )
            )
        found += 1
    if found == 0 and args.verbosity is not Verbosity.REALLY_QUIET:
        out.line(
            f"{out.palette.warning('No filters found in')} "
            f"{out.palette.title(str(path))}"
        )


def _trace_filters(
    conn: sqlite3.Connection,
    cursor: sqlite3.Cursor,
    args: Args,
    output: Output,
) -> dict[Path, M3UGFile]:
    """Resolve the filters a trace should evaluate."""
    if args.filters:
        return {
            filter_file: _parse_filter_file(filter_file, args, output)
            for filter_file in args.filters
        }

    path = args.path
    if path is None:
        raise GenplisError("Attempted to trace a file but no filter path was given")
    if not path.is_dir():
        raise GenplisError(
            f"{path} must be a directory; use --filter FILE to trace a single "
            ".m3ug filter"
        )
    return _discover_filters(conn, cursor, path, args, output)


def build_playlist_input(
    filter_file: Path,
    parsed: M3UGFile,
    target: Path,
    tags: Tags,
    args: Args,
) -> PlaylistInput:
    """Resolve the deterministic playlist inputs for a traced file."""
    spec = parsed.sort if parsed.sort is not None else args.config.output.sort
    dedupe_values: SortValues = ()
    if parsed.dedupe:
        dedupe_values = _tag_values(target, tags, parsed.dedupe)
    limit_key: SortValue | None = None
    exclusion: str | None = None
    if parsed.limit_per is not None and parsed.limit_per.count > 0:
        tag = parsed.limit_per.tag
        limit_key = _tag_values(target, tags, (tag,))[0]
        if limit_key is None:
            exclusion = f"per-tag limit key {tag!r} is missing; file would be skipped"
    return PlaylistInput(
        filter_file=filter_file,
        sort=spec,
        sort_values=_sort_values(target, tags, spec),
        sort_is_default=parsed.sort is None,
        dedupe=parsed.dedupe,
        dedupe_values=dedupe_values,
        limit=parsed.limit,
        limit_per=parsed.limit_per,
        limit_key=limit_key,
        max_duration=parsed.max_duration,
        duration=duration_seconds(tags.get("duration")),
        no_playlist=parsed.no_playlist,
        exclusion=exclusion,
    )


type FilterTraceItem = tuple[Path, FileTrace, PlaylistInput]


def _scan_root(args: Args) -> Path:
    path = args.path
    if path is None:
        raise GenplisError("Attempted to trace a file but no filter path was given")
    if args.filters and not path.is_dir():
        raise GenplisError("PATH must be a directory when --filter is used")
    return path if path.is_dir() else path.parent


def _load_trace_target(
    conn: sqlite3.Connection,
    cursor: sqlite3.Cursor,
    args: Args,
    output: Output,
) -> tuple[Tags, db.CacheStatus]:
    target = args.trace_path
    if target is None:
        raise GenplisError("Attempted to trace a file but none was given")
    if target.is_dir():
        raise GenplisError(f"Trace target {target} is a directory")
    if target.suffix.lower() == ".m3ug":
        raise GenplisError(f"Trace target {target} is a .m3ug filter, not audio")
    if not target.is_file():
        raise GenplisError(f"Trace target {target} does not exist")

    tags, _, cache_status = process_file(conn, cursor, target, args, output=output)
    if tags is None:
        raise GenplisError(f"Trace target {target} is not a supported music file")
    return tags, cache_status


def _prepare_traces(
    conn: sqlite3.Connection,
    cursor: sqlite3.Cursor,
    args: Args,
    target: Path,
    tags: Tags,
    output: Output,
) -> tuple[dict[Path, M3UGFile], list[FilterTraceItem]] | None:
    all_filters = _trace_filters(conn, cursor, args, output)
    if not all_filters:
        if args.verbosity is not Verbosity.REALLY_QUIET:
            output.line(
                f"{output.palette.warning('No filters found in')} "
                f"{output.palette.title(str(args.path))}"
            )
        return None
    traces = [
        (
            filter_file,
            trace_file(parsed, tags),
            build_playlist_input(filter_file, parsed, target, tags, args),
        )
        for filter_file, parsed in all_filters.items()
    ]
    return all_filters, traces


def _print_filter_traces(
    args: Args,
    target: Path,
    cache_status: db.CacheStatus,
    traces: list[FilterTraceItem],
    output: Output,
    *,
    selection_simulated: bool = False,
) -> None:
    if args.verbosity is Verbosity.REALLY_QUIET:
        return
    palette = output.palette
    output.line(f"Trace target: {palette.title(str(target))}")
    output.line(f"Cache status: {_format_cache_status(cache_status, palette)}")
    output.line(f"Filters: {palette.value(str(len(traces)))}")
    if is_excluded(target, args):
        output.line(
            palette.warning("WARNING: This file is excluded by current configuration.")
        )
    scan_root = _scan_root(args)
    try:
        target.relative_to(scan_root)
    except ValueError:
        output.line(
            palette.warning(f"WARNING: {target} is outside the scan root {scan_root}.")
        )

    for filter_file, traced, playlist_input in traces:
        output.line()
        output.line(f"Filter: {palette.title(str(filter_file))}")
        output.line(format_tags_consulted(traced.consulted, palette=palette))
        output.line(
            format_file_trace(
                traced,
                title=str(filter_file),
                palette=palette,
            )
        )
        output.line(
            format_playlist_input(
                playlist_input,
                selection_simulated=selection_simulated,
                palette=palette,
            )
        )
        output.line(
            palette.paint(
                ColorRole.PASS if traced.passed else ColorRole.FAIL,
                "MATCH" if traced.passed else "NO MATCH",
            )
        )

    if len(traces) > 1:
        output.line()
        output.line(palette.title("Summary:"))
        for filter_file, traced, _playlist_input in traces:
            result = palette.paint(
                ColorRole.PASS if traced.passed else ColorRole.FAIL,
                "MATCH" if traced.passed else "NO MATCH",
            )
            output.line(f"  {result} {palette.title(str(filter_file))}")


def trace_path(
    conn: sqlite3.Connection,
    cursor: sqlite3.Cursor,
    args: Args,
    output: Output | None = None,
) -> None:
    """Print an annotated evaluation of one audio file against filters."""
    out = Output.plain() if output is None else output
    target = args.trace_path
    if target is None:
        raise GenplisError("Attempted to trace a file but none was given")
    tags, cache_status = _load_trace_target(conn, cursor, args, out)
    prepared = _prepare_traces(conn, cursor, args, target, tags, out)
    if prepared is None:
        return
    _all_filters, traces = prepared
    _print_filter_traces(args, target, cache_status, traces, out)


def _selection_without_scan(
    target: Path,
    traces: list[FilterTraceItem],
    reason: str,
) -> SelectionTrace:
    selection = SelectionTrace(target=target)
    for filter_file, traced, playlist_input in traces:
        entry = FilterSelectionTrace(
            filter_file=filter_file,
            sort=playlist_input.sort,
            sort_is_default=playlist_input.sort_is_default,
            no_playlist=playlist_input.no_playlist,
        )
        if playlist_input.no_playlist:
            entry.considered = False
            entry.reason = "@NO-PLAYLIST"
        elif not traced.passed:
            entry.considered = False
            entry.reason = "no match"
        else:
            entry.considered = False
            entry.skipped = True
            entry.reason = reason
        selection.filters[filter_file] = entry
    return selection


def trace_full_path(
    conn: sqlite3.Connection,
    cursor: sqlite3.Cursor,
    args: Args,
    output: Output | None = None,
) -> None:
    """Trace a file and simulate its exact selection in every playlist."""
    out = Output.plain() if output is None else output
    target = args.trace_path
    if target is None:
        raise GenplisError("Attempted to trace a file but none was given")
    tags, cache_status = _load_trace_target(conn, cursor, args, out)
    prepared = _prepare_traces(conn, cursor, args, target, tags, out)
    if prepared is None:
        return
    all_filters, traces = prepared
    _print_filter_traces(
        args,
        target,
        cache_status,
        traces,
        out,
        selection_simulated=True,
    )

    scan_root = _scan_root(args)
    matching = [item for item in traces if item[1].passed]
    skip_reason: str | None = None
    if is_excluded(target, args):
        skip_reason = "target is excluded by current configuration"
    else:
        try:
            target.relative_to(scan_root)
        except ValueError:
            skip_reason = f"target is outside the scan root {scan_root}"
    if skip_reason is None and not matching:
        skip_reason = "no filter expression matches the target"
    if skip_reason is None and all(item[2].no_playlist for item in matching):
        skip_reason = "every matching filter has @NO-PLAYLIST"

    if skip_reason is not None:
        selection = _selection_without_scan(target, traces, skip_reason)
        if args.verbosity is not Verbosity.REALLY_QUIET:
            out.line()
            out.line(
                f"{out.palette.directive('Selection scan skipped:')} "
                f"{out.palette.source(skip_reason)}"
            )
    else:
        selection = SelectionTrace(target=target)
        simulation_args = replace(args, verbosity=Verbosity.REALLY_QUIET)
        process_directory(
            conn,
            cursor,
            scan_root,
            simulation_args,
            filters=all_filters,
            dry_run=True,
            selection_trace=selection,
            output=out,
        )

    if args.verbosity is not Verbosity.REALLY_QUIET:
        out.line()
        out.line(format_selection_trace(selection, palette=out.palette))


def display_tag_stats(
    conn: sqlite3.Connection,
    cursor: sqlite3.Cursor,
    args: Args,
    output: Output | None = None,
) -> None:
    """Print tag statistics for a collection or a single audio file."""
    out = Output.plain() if output is None else output
    palette = out.palette
    path = args.path
    if path is None:
        raise GenplisError("Attempted to display tag statistics but no path was given")

    if path.is_dir():
        collector = TagStatsCollector(full_tags=full_tag_names(args.tags))
        if args.verbosity is not Verbosity.REALLY_QUIET:
            out.line(f"Tag statistics for {palette.title(str(path))}")
        process_directory(
            conn,
            cursor,
            path,
            args,
            filters={},
            stats=collector,
            output=out,
        )
        if args.verbosity is not Verbosity.REALLY_QUIET:
            report = collector.report()
            out.line(
                render_tag_details(report, args.tags, palette=palette)
                if args.tags
                else render_tag_stats(report, palette=palette)
            )
        return

    if not path.is_file():
        raise GenplisError(f"{path} must be either a directory or a file")

    if path.suffix.lower() == ".m3ug":
        raise GenplisError(
            "Tag statistics require a directory or an audio file, not a .m3ug filter"
        )

    tags, _, cache_status = process_file(conn, cursor, path, args, output=out)
    if tags is None:
        if args.verbosity is not Verbosity.REALLY_QUIET:
            out.line(
                f"{palette.title(str(path))} "
                f"{palette.warning('is not a supported music file')}"
            )
        return
    if args.verbosity is not Verbosity.REALLY_QUIET:
        display_file_tags(path, tags, cache_status, args.tags, output=out)
    if is_excluded(path, args) and args.verbosity.shows_normal_output:
        out.line(
            palette.warning("WARNING: This file is excluded by current configuration.")
        )


def matches_rules(tags: Mapping[str, TagValue], expression: FilterNode | None) -> bool:
    """Return True when the filter expression matches the given tags."""
    return expression is None or expression.apply(tags)


def _tag_values(
    file: Path, tags: Mapping[str, TagValue], names: Sequence[str]
) -> SortValues:
    """Resolve normalized values for tag names and the filename pseudo-tag."""
    values: list[SortValue | None] = []
    for name in names:
        if name.lower() == "filename":
            raw: TagValue = os.path.abspath(file)
        else:
            _, raw = NameNode(name).find(tags)
        values.append(normalize_sort_value(raw))
    return tuple(values)


def _sort_values(
    file: Path, tags: Mapping[str, TagValue], spec: SortSpec
) -> SortValues:
    """Resolve the sort values for one file.

    ``filename`` is always the absolute path being processed, independent of
    the cached tag value. Other keys use normal M3UG tag lookup, including the
    special handling for ``rating``.
    """
    names = [key.name for key in spec if not key.is_random]
    return _tag_values(file, tags, names)


def _compare_matches(first: Match, second: Match, spec: SortSpec) -> int:
    """Compare matches by the sort spec, then by directory-walk order."""
    result = compare_sort_values(first.sort_values, second.sort_values, spec)
    if result:
        return result
    if first.order < second.order:
        return -1
    if first.order > second.order:
        return 1
    return 0


def _sort_matches(matched: list[Match], spec: SortSpec) -> None:
    """Sort matches in place, then shuffle random runs when requested."""
    random_key = spec[-1] if spec and spec[-1].is_random else None
    prefix = spec[:-1] if random_key is not None else spec
    if prefix:
        matched.sort(
            key=cmp_to_key(
                lambda first, second: _compare_matches(first, second, prefix)
            )
        )
    else:
        matched.sort(key=lambda item: item.order)

    if random_key is None:
        return
    rng = random.Random(random_key.seed)  # noqa: S311 - playlist order is not secret
    if not prefix:
        rng.shuffle(matched)
        return

    start = 0
    while start < len(matched):
        end = start + 1
        while (
            end < len(matched)
            and matched[end].sort_values == matched[start].sort_values
        ):
            end += 1
        if end - start > 1:
            run = matched[start:end]
            rng.shuffle(run)
            matched[start:end] = run
        start = end


def _match_path(match: Match) -> Path:
    """Return the filesystem path behind a playlist match."""
    return match.entry.path if isinstance(match.entry, PlaylistEntry) else match.entry


def _dedupe_matches(
    matched: list[Match],
    *,
    trace: FilterSelectionTrace | None = None,
    target: Path | None = None,
) -> list[Match]:
    """Keep the first entry for each normalized key after ordering."""
    seen: set[tuple[SortValue, ...]] = set()
    winners: dict[tuple[SortValue, ...], Match] | None = (
        {} if trace is not None else None
    )
    kept: list[Match] = []
    for match in matched:
        values = match.dedupe_values
        if not values or any(value is None for value in values):
            if trace is not None and target == _match_path(match):
                trace.dedupe_result = "kept: missing dedupe key"
            kept.append(match)
            continue
        key = tuple(value for value in values if value is not None)
        if key in seen:
            if trace is not None and target == _match_path(match):
                trace.dedupe_result = "excluded: duplicate key"
                if winners is not None and key in winners:
                    trace.dedupe_winner = _match_path(winners[key])
            continue
        seen.add(key)
        if winners is not None:
            winners[key] = match
        if trace is not None and target == _match_path(match):
            trace.dedupe_result = "kept: unique key"
        kept.append(match)
    return kept


def _select_matches(
    matched: list[Match],
    limit: int | None,
    limit_per: LimitPerTag | None,
    max_duration: float | None,
    *,
    trace: FilterSelectionTrace | None = None,
    target: Path | None = None,
) -> list[Match]:
    """Apply the count, per-tag, and duration caps in order."""
    count_cap = limit if limit is not None and limit > 0 else None
    per_tag_cap = limit_per if limit_per is not None and limit_per.count > 0 else None
    duration_cap = (
        max_duration if max_duration is not None and max_duration > 0 else None
    )
    if (
        count_cap is None
        and per_tag_cap is None
        and duration_cap is None
        and trace is None
    ):
        return matched

    if trace is not None:
        trace.limit_result = (
            "no count cap" if count_cap is None else f"count cap {count_cap}"
        )
        trace.per_tag_result = (
            "no per-tag cap"
            if per_tag_cap is None
            else f"per-tag cap {per_tag_cap.count} per {per_tag_cap.tag}"
        )
        trace.duration_result = (
            "no duration cap"
            if duration_cap is None
            else f"duration cap {duration_cap:g}s"
        )

    selected: list[Match] = []
    per_tag_counts: dict[SortValue, int] = {}
    total_duration = 0.0
    for match in matched:
        is_target = trace is not None and target == _match_path(match)
        if count_cap is not None and len(selected) >= count_cap:
            if trace is not None and not trace.selected:
                trace.limit_result = f"excluded: count cap {count_cap} reached"
            break
        limit_key: SortValue | None = None
        if per_tag_cap is not None:
            limit_key = match.limit_key
            if limit_key is None:
                if is_target and trace is not None:
                    trace.per_tag_result = f"excluded: missing {per_tag_cap.tag} key"
                continue
            if per_tag_counts.get(limit_key, 0) >= per_tag_cap.count:
                if is_target and trace is not None:
                    trace.per_tag_result = (
                        f"excluded: per-tag cap {per_tag_cap.count} per "
                        f"{per_tag_cap.tag} reached"
                    )
                continue
        duration = match.duration if match.duration is not None else 0.0
        if (
            duration_cap is not None
            and selected
            and total_duration + duration > duration_cap
        ):
            if trace is not None and not trace.selected:
                trace.duration_result = (
                    f"excluded: {duration:g}s would exceed {duration_cap:g}s cap"
                )
            break
        selected.append(match)
        total_duration += duration
        if per_tag_cap is not None and limit_key is not None:
            per_tag_counts[limit_key] = per_tag_counts.get(limit_key, 0) + 1
        if is_target and trace is not None:
            trace.selected = True
            trace.position = len(selected)
            if count_cap is not None:
                trace.limit_result = f"selected within count cap {count_cap}"
            if per_tag_cap is not None:
                trace.per_tag_result = (
                    f"selected within per-tag cap {per_tag_cap.count} per "
                    f"{per_tag_cap.tag}"
                )
            if duration_cap is not None:
                trace.duration_result = (
                    f"selected within duration cap {duration_cap:g}s"
                )
    return selected


def _walk_files(
    directory: Path,
    args: Args,
    *,
    report_skips: bool = True,
    only_m3ug: bool = False,
    output: Output | None = None,
) -> Iterator[Path]:
    """Yield included files in directory walk order.

    ``only_m3ug`` restricts the first scan to filter files without stat'ing
    every audio file. ``report_skips`` is disabled for that scan so verbose
    exclusion messages are printed once, by the audio scan.
    """
    out = Output.plain() if output is None else output
    palette = out.palette
    for current_dir, dirnames, filenames in directory.walk():
        current = Path(current_dir)

        kept_dirs: list[str] = []
        for name in dirnames:
            folder = current / name
            if is_excluded(folder, args, is_dir=True):
                if report_skips and args.verbosity.is_verbose:
                    out.line(
                        f"{palette.paint(ColorRole.SKIP, 'Skipping')} "
                        f"{palette.title(str(folder))} "
                        f"{palette.source('because of exclude pattern.')}"
                    )
                continue
            kept_dirs.append(name)
        dirnames[:] = kept_dirs

        for name in filenames:
            file = current / name
            if only_m3ug and file.suffix.lower() != ".m3ug":
                continue
            if is_excluded(file, args):
                if report_skips and args.verbosity.is_verbose:
                    out.line(
                        f"{palette.paint(ColorRole.SKIP, 'Skipping')} "
                        f"{palette.title(str(file))} "
                        f"{palette.source('because of exclude pattern.')}"
                    )
                continue
            # Path.walk reports symlinks to directories among the filenames.
            if not file.is_file():
                continue
            yield file


def _discover_filters(
    conn: sqlite3.Connection,
    cursor: sqlite3.Cursor,
    directory: Path,
    args: Args,
    output: Output | None = None,
) -> dict[Path, M3UGFile]:
    """Parse every M3UG file before any audio file is filtered."""
    all_filters: dict[Path, M3UGFile] = {}
    for file in _walk_files(directory, args, report_skips=False, only_m3ug=True):
        _, parsed, _ = process_file(conn, cursor, file, args, output=output)
        if parsed is not None:
            all_filters[file] = parsed
    return all_filters


def _record_matches(
    matches: dict[Path, list[Match]],
    all_filters: Mapping[Path, M3UGFile],
    order: int,
    file: Path,
    tags: Tags,
    *,
    extended: bool,
    default_sort: SortSpec,
    predicate_cache: PredicateCache | None = None,
) -> None:
    """Add a file to every filter it matches, with its effective sort keys."""
    evaluation_tags = EvaluationTags(tags, predicate_cache)
    entry: Path | PlaylistEntry | None = None
    spec_cache: dict[SortSpec, SortValues] = {}
    dedupe_cache: dict[tuple[str, ...], SortValues] = {}
    limit_key_cache: dict[str, SortValue | None] = {}
    for filter_file, parsed in all_filters.items():
        if parsed.no_playlist:
            continue
        if matches_rules(evaluation_tags, parsed.expression):
            if entry is None:
                entry = playlist_entry(file, tags) if extended else file
            spec = parsed.sort if parsed.sort is not None else default_sort
            if spec not in spec_cache:
                spec_cache[spec] = _sort_values(file, evaluation_tags, spec)
            duration = None
            if parsed.max_duration is not None and parsed.max_duration > 0:
                duration = duration_seconds(tags.get("duration"))
            dedupe_values: SortValues = ()
            if parsed.dedupe:
                if parsed.dedupe not in dedupe_cache:
                    dedupe_cache[parsed.dedupe] = _tag_values(
                        file,
                        evaluation_tags,
                        parsed.dedupe,
                    )
                dedupe_values = dedupe_cache[parsed.dedupe]
            limit_key: SortValue | None = None
            if parsed.limit_per is not None and parsed.limit_per.count > 0:
                tag = parsed.limit_per.tag
                if tag not in limit_key_cache:
                    limit_key_cache[tag] = _tag_values(file, evaluation_tags, (tag,))[0]
                limit_key = limit_key_cache[tag]
            matches[filter_file].append(
                Match(
                    order,
                    entry,
                    spec_cache[spec],
                    duration,
                    dedupe_values,
                    limit_key,
                )
            )


def process_directory(
    conn: sqlite3.Connection,
    cursor: sqlite3.Cursor,
    directory: Path,
    args: Args,
    *,
    retain_tags: bool = False,
    filters: Mapping[Path, M3UGFile] | None = None,
    stats: TagStatsCollector | None = None,
    dry_run: bool = False,
    selection_trace: SelectionTrace | None = None,
    output: Output | None = None,
) -> tuple[dict[Path, Tags], dict[Path, M3UGFile]]:
    """Traverse the directory and process all files.

    See process_file for how each file is handled.

    Returns a tuple in the form (all_tags, all_filters), both keyed by file
    path: all_tags maps music files to their tags, all_filters maps M3UG
    files to their parsed rules and ordering. A playlist is generated for each
    M3UG file that matches at least one song. Unless include_source is
    disabled, the original M3UG text is embedded as comments at the top of the
    playlist. Folders that match an exclude pattern are skipped entirely.

    When ``filters`` is given, those already-parsed filters are used instead
    of discovering every ``.m3ug`` file under ``directory``. This is how a
    single filter passed on the command line is processed without touching
    the playlists of its neighbours.

    With ``retain_tags`` False (the default), tags are released as soon as
    each file has been matched against the filters and ``all_tags`` is empty.
    Set it to True only when the caller needs the complete mapping, such as
    tests or debugging; retaining it defeats the memory optimization for
    large collections.

    When ``stats`` is given, each supported file's tags are also recorded in
    the collector. The collector keeps only aggregate counters, so tags are
    still released after every file.

    With ``selection_trace``, the pipeline records where that trace's target
    file ends up while sorting, deduplicating and applying the caps. Only the
    target is recorded; the normal match lists are still released. With
    ``dry_run``, playlists are not written, but tags, cache rows and the
    selection pipeline behave exactly as in a normal run.

    """
    if not directory.is_dir():
        raise GenplisError(
            f"Attempted to process {directory} as a directory but it's not a directory"
        )

    out = Output.plain() if output is None else output
    start_time = timer()

    if filters is None:
        all_filters = _discover_filters(conn, cursor, directory, args, out)
        if args.verbosity.is_verbose:
            for filter_file, parsed in all_filters.items():
                out.line(
                    format_filter_tree(
                        parsed,
                        title=str(filter_file),
                        default_sort=args.config.output.sort,
                        palette=out.palette,
                    )
                )
    else:
        all_filters = dict(filters)
    predicate_cache = PredicateCache(
        parsed.expression for parsed in all_filters.values() if not parsed.no_playlist
    )
    matches: dict[Path, list[Match]] = {filter_file: [] for filter_file in all_filters}
    retained: dict[int, tuple[Path, Tags]] | None = {} if retain_tags else None
    processed = 0
    pending: list[ParseItem] = []
    order = 0
    batch = db.WriteBatch(conn, every=COMMIT_EVERY, output=out)

    def handle_tags(current_order: int, file: Path, tags: Tags) -> None:
        """Record one successfully parsed file in every consumer."""
        nonlocal processed
        processed += 1
        if retained is not None:
            retained[current_order] = (file, tags)
        if stats is not None:
            stats.record_file(tags, get_calculated_tags(tags))
        _record_matches(
            matches,
            all_filters,
            current_order,
            file,
            tags,
            extended=args.extended_m3u,
            default_sort=args.config.output.sort,
            predicate_cache=predicate_cache,
        )

    progress = Progress(out, enabled=args.verbosity is Verbosity.NORMAL)
    progress.scanning()
    try:
        # Resolve cache hits while walking and queue misses and stale entries,
        # so the parsing phase knows how many files it will attempt.
        for file in _walk_files(directory, args, output=out):
            progress.tick()
            if file.suffix.lower() == ".m3ug":
                continue
            if not is_supported_file(file):
                if args.verbosity.is_verbose:
                    get_tags(
                        file,
                        args.verbosity,
                        max_size=args.config.tags.max_size,
                        ignore=args.config.tags.ignore,
                        output=out,
                    )
                continue

            current_order = order
            order += 1

            last_modified = db.get_last_modified(file)
            cache_status = db.get_cache_status(cursor, file, last_modified)
            if cache_status is db.CacheStatus.HIT:
                tags = db.get_cached_tags(cursor, file)
                handle_tags(current_order, file, tags)
            else:
                pending.append(
                    ParseItem(
                        path=file,
                        last_modified=last_modified,
                        order=current_order,
                    )
                )

        progress.start(len(pending))
        if args.jobs <= 1:
            for item in pending:
                tags, _, _ = process_file(
                    conn,
                    cursor,
                    item.path,
                    args,
                    batch=batch,
                    last_modified=item.last_modified,
                    output=out,
                )
                progress.advance()
                if tags is None:
                    continue
                handle_tags(item.order, item.path, tags)
        else:
            executor = make_executor(args.jobs, len(pending), args.config.tags)
            if isinstance(executor, ProcessExecutor) and args.verbosity.is_verbose:
                out.line(
                    f"{out.palette.directive('Parsing with')} "
                    f"{out.palette.value(str(executor.workers))} worker processes"
                )
            try:
                for result in executor.parse(pending):
                    progress.advance()
                    if args.verbosity.is_verbose:
                        for diagnostic in result.diagnostics:
                            out.line(format_tag_diagnostic(diagnostic, out.palette))
                    if result.tags is None:
                        continue
                    batch.store(
                        cursor,
                        result.item.path,
                        result.tags,
                        last_modified=result.item.last_modified,
                        verbosity=args.verbosity,
                    )
                    handle_tags(
                        result.item.order,
                        result.item.path,
                        result.tags,
                    )
            except BaseException:
                executor.close(cancel=True)
                raise
            else:
                executor.close()
        pending.clear()
    finally:
        try:
            batch.flush()
        finally:
            progress.close()

    all_tags = (
        {file: tags for _, (file, tags) in sorted(retained.items())}
        if retained is not None
        else {}
    )

    # Every filter has already been applied to every file. Sort each match
    # list with its effective spec (worker results can arrive out of order)
    # and write each playlist.
    for filter_file, parsed in all_filters.items():
        spec = parsed.sort if parsed.sort is not None else args.config.output.sort
        trace_entry: FilterSelectionTrace | None = None
        target: Path | None = None
        if selection_trace is not None:
            target = selection_trace.target
            trace_entry = selection_trace.filters.setdefault(
                filter_file,
                FilterSelectionTrace(filter_file=filter_file),
            )
            trace_entry.sort = spec
            trace_entry.sort_is_default = parsed.sort is None
            trace_entry.dedupe = parsed.dedupe
            trace_entry.limit = parsed.limit
            trace_entry.limit_per = parsed.limit_per
            trace_entry.max_duration = parsed.max_duration
            trace_entry.no_playlist = parsed.no_playlist

        if parsed.no_playlist:
            if trace_entry is not None:
                trace_entry.considered = False
                trace_entry.reason = "@NO-PLAYLIST"
            continue
        matched = matches[filter_file]
        if trace_entry is not None:
            trace_entry.total_matches = len(matched)
        _sort_matches(matched, spec)

        target_match: Match | None = None
        if trace_entry is not None and target is not None:
            for index, match in enumerate(matched):
                if _match_path(match) == target:
                    target_match = match
                    trace_entry.sorted_position = index + 1
                    trace_entry.sort_values = match.sort_values
                    trace_entry.dedupe_values = match.dedupe_values
                    trace_entry.limit_key = match.limit_key
                    break
            if target_match is None:
                trace_entry.considered = False
                trace_entry.reason = "no match"

        if parsed.dedupe:
            matched = _dedupe_matches(
                matched,
                trace=trace_entry if target_match is not None else None,
                target=target,
            )
        target_available = (
            trace_entry is not None
            and target is not None
            and any(_match_path(match) == target for match in matched)
        )
        if (
            trace_entry is not None
            and target_match is not None
            and not target_available
        ):
            trace_entry.considered = False
            trace_entry.reason = trace_entry.dedupe_result or "removed before selection"
        matched = _select_matches(
            matched,
            parsed.limit,
            parsed.limit_per,
            parsed.max_duration,
            trace=trace_entry if target_available else None,
            target=target,
        )
        if trace_entry is not None and target_available:
            trace_entry.considered = True
            if trace_entry.selected:
                trace_entry.reason = "selected"
            elif trace_entry.reason is None:
                reasons = [
                    result
                    for result in (
                        trace_entry.limit_result,
                        trace_entry.per_tag_result,
                        trace_entry.duration_result,
                    )
                    if result.startswith("excluded:")
                ]
                trace_entry.reason = "; ".join(reasons) or "not selected"

        if args.verbosity.is_verbose:
            out.line(
                f"\nFiltering songs and generating playlist for "
                f"{out.palette.title(str(filter_file))}"
            )
            out.line(
                f"{out.palette.directive('Sort order:')} "
                f"{out.palette.value(format_sort_spec(spec))}"
            )
            out.line(
                f"Files that match the filter {out.palette.title(str(filter_file))}:"
            )
            for match in matched:
                out.line(f"  {out.palette.value(str(_match_path(match)))}")
        if args.verbosity.shows_progress:
            out.line(
                f"Filter file {out.palette.title(str(filter_file))} matched "
                f"{out.palette.value(str(len(matched)))} songs"
            )
        if matched and not dry_run:
            playlist_file = filter_file.with_suffix(".m3u")
            if args.verbosity.shows_progress:
                out.line(f"Creating playlist {out.palette.title(str(playlist_file))}")
            comments: list[str] = []
            if args.include_source:
                source = filter_file.read_text(encoding="utf-8-sig")
                comments = [
                    f'Generated by genplis from "{filter_file.name}"',
                    "",
                    *source.splitlines(),
                ]
            create_m3u(
                playlist_file,
                (match.entry for match in matched),
                comments=comments,
                overwrite=args.overwrite,
                verbosity=args.verbosity,
                extended=args.extended_m3u,
                output=out,
            )
        matches[filter_file].clear()
        matched.clear()

    end_time = timer()
    process_time = end_time - start_time
    used_memory = psutil.Process().memory_info().rss / (1024 * 1024)
    if args.verbosity.shows_normal_output:
        out.line(
            f"Processed {out.palette.value(str(processed))} files in "
            f"{out.palette.value(f'{process_time:.3f}')} seconds"
        )
        out.line(f"Total RAM usage: {out.palette.value(str(used_memory))} MiB")

    return all_tags, all_filters


def process_file(
    conn: sqlite3.Connection,
    cursor: sqlite3.Cursor,
    file: Path,
    args: Args,
    *,
    batch: db.WriteBatch | None = None,
    last_modified: int | None = None,
    output: Output | None = None,
) -> tuple[Tags | None, M3UGFile | None, db.CacheStatus]:
    """Process a single file.

    Returns a tuple in the form (tags, parsed_m3ug, cache_status), where tags
    is a dictionary, parsed_m3ug is ``None`` for non-M3UG files and
    cache_status is the state of the tag cache when the file was found.

    When ``batch`` is given, cache writes go through it instead of committing
    immediately. ``None`` preserves the single-file behaviour of committing
    each write before returning.

    Pass ``last_modified`` when the caller already read the file's timestamp,
    so it is not read again.

    ``tags`` is ``None`` when the file is not a supported music file. An empty
    dictionary means the file is supported music but has no usable tags (for
    example because every tag is ignored).

    If it's an M3UG file, parse it as such and return its rules and optional
    ordering. See m3ug module.

    Music files are parsed with tinytag, detected tags are returned as a
    dictionary. Up-to-date cached tags are reused instead of parsing again;
    M3UG files are never cached, so they always report CacheStatus.MISS.

    """
    if not file.is_file():
        raise GenplisError(f"Attempted to process {file} as a file but it's not a file")

    if file.suffix.lower() == ".m3ug":
        content = file.read_text(encoding="utf-8-sig")
        parsed = parse_m3ug(
            content,
            str(file),
            args.verbosity,
            output=output,
        )
        return None, parsed, db.CacheStatus.MISS

    if last_modified is None:
        last_modified = db.get_last_modified(file)
    cache_status = db.get_cache_status(cursor, file, last_modified)
    if cache_status is db.CacheStatus.HIT:
        # reuse cached tags from DB instead of parsing them again
        cached_tags = db.get_cached_tags(cursor, file)
        return cached_tags, None, cache_status

    tags = get_tags(
        file,
        args.verbosity,
        max_size=args.config.tags.max_size,
        ignore=args.config.tags.ignore,
        output=output,
    )
    if tags is None:
        return None, None, cache_status
    # Cache supported files even when every tag was filtered out, so an empty
    # tag dictionary is not confused with "not a music file" next time.
    if batch is not None:
        batch.store(
            cursor,
            file,
            tags,
            last_modified=last_modified,
            verbosity=args.verbosity,
        )
    else:
        db.cache_tags_for_file(
            cursor,
            file,
            tags,
            last_modified=last_modified,
            verbosity=args.verbosity,
            output=output,
        )
        conn.commit()
    return tags, None, cache_status


def clean_database(
    conn: sqlite3.Connection,
    cursor: sqlite3.Cursor,
    root: Path | None,
    db_path: Path,
    verbosity: Verbosity = Verbosity.NORMAL,
    output: Output | None = None,
) -> CleanStats:
    """Remove cache entries for missing files and reclaim their space.

    When root is given, only entries under root are considered. VACUUM runs
    only when something was removed, so the reported size reduction is the
    actual change on disk.

    """
    out = Output.plain() if output is None else output
    palette = out.palette
    conn.commit()
    size_before = db_path.stat().st_size

    removed = db.remove_missing_files(cursor, root)
    conn.commit()
    if removed:
        db.vacuum_database(conn)
    size_after = db_path.stat().st_size

    if verbosity.is_verbose:
        for path in removed:
            out.line(
                f"{palette.source('Removed stale cache entry for')} "
                f"{palette.title(str(path))}"
            )

    stats = CleanStats(
        removed=tuple(removed),
        size_before=size_before,
        size_after=size_after,
    )
    entry_word = "entry" if len(removed) == 1 else "entries"
    if verbosity.shows_normal_output:
        out.line(
            f"Removed {palette.value(str(len(removed)))} stale {entry_word} "
            "from the cache database."
        )
        out.line(
            f"{palette.source('Database size:')} "
            f"{palette.value(format_size(size_before))} -> "
            f"{palette.value(format_size(size_after))} "
            f"{palette.paint(ColorRole.PASS, f'({format_size(stats.bytes_saved)} saved)')}."
        )
    return stats


def _run(args: Args) -> None:
    """Run genplis with resolved arguments."""
    out = Output.create(sys.stdout, color=args.color, theme=args.theme)
    if args.verbosity.is_verbose:
        if args.config_disabled:
            out.line(
                f"{out.palette.directive('Configuration disabled with')} "
                f"{out.palette.value('--no-config')}"
            )
        elif args.config.source is not None:
            out.line(f"Using config file {out.palette.title(str(args.config.source))}")
        else:
            out.line(out.palette.source("No config file found; using defaults"))
        if args.mode is not Mode.SHOW_RULES:
            out.line(f"Using {out.palette.title(str(args.db_path))} for genplis DB")

    if args.mode is Mode.SHOW_RULES:
        show_rules(args, out)
        return

    if args.path is None and not args.db_path.exists():
        if args.verbosity.shows_normal_output:
            out.line(out.palette.source("Database does not exist; nothing to clean."))
        return

    try:
        args.db_path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise GenplisError(
            f"Cannot create database directory {args.db_path.parent}: {exc}"
        ) from exc

    conn, cursor = db.setup_database_connection(args.db_path)
    try:
        with conn:
            # Create a DB for caching results if it doesn't exist
            db.create_files_table(cursor, db.get_cache_version(args.config.tags))
            conn.commit()

            if args.mode is Mode.TRACE:
                trace_path(conn, cursor, args, out)
            elif args.mode is Mode.TRACE_FULL:
                trace_full_path(conn, cursor, args, out)
            elif args.mode is Mode.TAG_STATS:
                if args.path is not None:
                    display_tag_stats(conn, cursor, args, out)
            elif args.path is not None:
                process_path(conn, cursor, args, out)
            if args.clean:
                clean_database(
                    conn,
                    cursor,
                    args.path,
                    args.db_path,
                    verbosity=args.verbosity,
                    output=out,
                )
    finally:
        conn.close()


def main() -> None:
    # Set up argparse
    parser = setup_argparse()
    raw_args = parser.parse_args()

    if raw_args.quiet and raw_args.verbose:
        parser.error("--quiet cannot be combined with --verbose")
    if raw_args.clean and raw_args.tags:
        parser.error("--tag cannot be combined with --clean")

    try:
        config = Config() if raw_args.no_config else load_config(raw_args.config)
        args = resolve_args(raw_args, config)
    except GenplisConfigError as exc:
        error_out = Output.create(
            sys.stderr,
            color=raw_args.color,
            theme=Theme(raw_args.theme) if raw_args.theme is not None else Theme.AUTO,
        )
        parser.exit(
            1,
            f"{error_out.palette.error('genplis: error:')} {exc}\n",
        )

    try:
        _run(args)
    except GenplisError as exc:
        error_out = Output.create(sys.stderr, color=args.color, theme=args.theme)
        error_out.line(f"{error_out.palette.error('genplis: error:')} {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()
