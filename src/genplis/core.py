import argparse
import os
import random
import re
import sqlite3
import sys
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from functools import cmp_to_key
from pathlib import Path
from timeit import default_timer as timer

import psutil

from . import db
from .config import Config, load_config
from .diagnostics import format_filter_tree
from .exceptions import GenplisConfigError, GenplisError
from .executors import (
    ParseItem,
    ProcessExecutor,
    auto_workers,
    make_executor,
)
from .m3u import PlaylistEntry, create_m3u, duration_seconds, playlist_entry
from .m3ug import (
    FilterNode,
    LimitPerTag,
    M3UGFile,
    NameNode,
    get_rating,
    parse_m3ug,
)
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
from .tags import AUDIO_PROPERTY_TAGS, get_audio_property_tags, get_tags
from .types import Tags, TagValue, Verbosity

# User-facing description of each cache state.
CACHE_STATUS_MESSAGES = {
    db.CacheStatus.MISS: "not present",
    db.CacheStatus.STALE: "stale",
    db.CacheStatus.HIT: "valid",
}

# Commit cache writes every N rows during a directory scan. Benchmarked on a
# 50k-file cold scan: 128 was within 0.7% of the best median and far ahead of
# committing after every write.
COMMIT_EVERY = 128


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
    display_tags: bool = False
    tags: tuple[str, ...] = ()


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
        "--db",
        help="Use this database file instead of the XDG cache default",
        type=Path,
        metavar="PATH",
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
            "Remove cache entries for files that no longer exist. With PATH, "
            "process it normally first and clean only entries under it; "
            "without PATH, clean the whole database."
        ),
        action="store_true",
    )
    mode_group.add_argument(
        "--tag-stats",
        dest="display_tags",
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


def resolve_args(args: argparse.Namespace, config: Config) -> Args:
    """Combine command-line arguments with configuration file values.

    Command-line values take precedence. Excludes are special: when any
    --exclude option is present, it replaces the config file's exclude list.
    """
    if args.clean and args.tags:
        raise GenplisConfigError("--tag cannot be combined with --clean")

    requested_tags: list[str] = []
    for raw_tag in args.tags or ():
        name = raw_tag.strip().lower()
        if not name:
            raise GenplisConfigError("tag name must not be empty")
        requested_tags.append(name)
    tags = tuple(dict.fromkeys(requested_tags))
    display_tags = args.display_tags or bool(tags)

    if args.path is not None:
        path = args.path
    elif args.clean:
        # Cleaning without a CLI path removes entries from the whole database,
        # even when a collection path is configured.
        path = None
    elif config.collection.path is not None:
        path = config.collection.path
    else:
        raise GenplisConfigError(
            "PATH is required unless [collection] path is set in the config file"
        )

    exclude = (
        tuple(args.exclude) if args.exclude is not None else config.collection.exclude
    )
    verbosity = _resolve_verbosity(args, config)
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
        display_tags=display_tags,
        tags=tags,
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


def _select_display_tags(
    display_tags: Mapping[str, TagValue],
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
        key: value for key, value in display_tags.items() if key.lower() in wanted
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
) -> None:
    """Print the tags of a single music file, optionally filtered by name."""
    print(f"{path} detected as music file")
    print(f"Cache status: {CACHE_STATUS_MESSAGES[cache_status]}")
    print("Parsed tags:")
    display_tags: Tags = {
        key: value for key, value in tags.items() if key not in AUDIO_PROPERTY_TAGS
    }
    display_tags.update(get_calculated_tags(tags))
    missing: tuple[str, ...] = ()
    if requested:
        display_tags, missing = _select_display_tags(display_tags, requested)
    for key, value in sorted(display_tags.items(), key=lambda tag: tag[0]):
        print(f"    {key} = {value}")
    for name in missing:
        print(f"Tag '{name}' was not found. It may be hidden by [tags] ignore.")


def process_path(conn: sqlite3.Connection, cursor: sqlite3.Cursor, args: Args) -> None:
    """Process an arbitrary path through genplis.

    It will use process_file or process_directory depending on the type of the path.

    """
    path = args.path
    if path is None:
        raise GenplisError("Attempted to process a path but none was given")

    if path.is_dir():
        process_directory(conn, cursor, path, args)
    elif path.is_file():
        tags, parsed, cache_status = process_file(conn, cursor, path, args)
        if tags is not None and args.verbosity.shows_normal_output:
            display_file_tags(path, tags, cache_status)
        if parsed is not None and args.verbosity.shows_normal_output:
            print(
                format_filter_tree(
                    parsed,
                    title=f"{path} detected as M3UG file",
                    default_sort=args.config.output.sort,
                )
            )
        if is_excluded(path, args) and args.verbosity.shows_normal_output:
            print("WARNING: This file is excluded by current configuration.")
        if parsed is not None:
            # An explicit M3UG path processes only that filter. Its directory
            # is scanned for songs, and @INCLUDE still pulls in shared rules.
            process_directory(
                conn,
                cursor,
                path.parent,
                args,
                filters={path: parsed},
            )
    else:
        print(
            f"{path} must be either a directory or a file. Exiting...",
            file=sys.stderr,
        )
        sys.exit(1)


def display_tag_stats(
    conn: sqlite3.Connection,
    cursor: sqlite3.Cursor,
    args: Args,
) -> None:
    """Print tag statistics for a collection or a single audio file."""
    path = args.path
    if path is None:
        raise GenplisError("Attempted to display tag statistics but no path was given")

    if path.is_dir():
        collector = TagStatsCollector(full_tags=full_tag_names(args.tags))
        if args.verbosity is not Verbosity.REALLY_QUIET:
            print(f"Tag statistics for {path}")
        process_directory(
            conn,
            cursor,
            path,
            args,
            filters={},
            stats=collector,
        )
        if args.verbosity is not Verbosity.REALLY_QUIET:
            report = collector.report()
            print(
                render_tag_details(report, args.tags)
                if args.tags
                else render_tag_stats(report)
            )
        return

    if not path.is_file():
        raise GenplisError(f"{path} must be either a directory or a file")

    if path.suffix.lower() == ".m3ug":
        raise GenplisError(
            "Tag statistics require a directory or an audio file, not a .m3ug filter"
        )

    tags, _, cache_status = process_file(conn, cursor, path, args)
    if tags is None:
        if args.verbosity is not Verbosity.REALLY_QUIET:
            print(f"{path} is not a supported music file")
        return
    if args.verbosity is not Verbosity.REALLY_QUIET:
        display_file_tags(path, tags, cache_status, args.tags)
    if is_excluded(path, args) and args.verbosity.shows_normal_output:
        print("WARNING: This file is excluded by current configuration.")


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


def _dedupe_matches(matched: list[Match]) -> list[Match]:
    """Keep the first entry for each normalized key after ordering."""
    seen: set[tuple[SortValue, ...]] = set()
    kept: list[Match] = []
    for match in matched:
        values = match.dedupe_values
        if not values or any(value is None for value in values):
            kept.append(match)
            continue
        key = tuple(value for value in values if value is not None)
        if key in seen:
            continue
        seen.add(key)
        kept.append(match)
    return kept


def _select_matches(
    matched: list[Match],
    limit: int | None,
    limit_per: LimitPerTag | None,
    max_duration: float | None,
) -> list[Match]:
    """Apply the count, per-tag, and duration caps in order."""
    count_cap = limit if limit is not None and limit > 0 else None
    per_tag_cap = limit_per if limit_per is not None and limit_per.count > 0 else None
    duration_cap = (
        max_duration if max_duration is not None and max_duration > 0 else None
    )
    if count_cap is None and per_tag_cap is None and duration_cap is None:
        return matched

    selected: list[Match] = []
    per_tag_counts: dict[SortValue, int] = {}
    total_duration = 0.0
    for match in matched:
        if count_cap is not None and len(selected) >= count_cap:
            break
        limit_key: SortValue | None = None
        if per_tag_cap is not None:
            limit_key = match.limit_key
            if limit_key is None:
                continue
            if per_tag_counts.get(limit_key, 0) >= per_tag_cap.count:
                continue
        duration = match.duration if match.duration is not None else 0.0
        if (
            duration_cap is not None
            and selected
            and total_duration + duration > duration_cap
        ):
            break
        selected.append(match)
        total_duration += duration
        if per_tag_cap is not None and limit_key is not None:
            per_tag_counts[limit_key] = per_tag_counts.get(limit_key, 0) + 1
    return selected


def _walk_files(
    directory: Path,
    args: Args,
    *,
    report_skips: bool = True,
    only_m3ug: bool = False,
) -> Iterator[Path]:
    """Yield included files in directory walk order.

    ``only_m3ug`` restricts the first scan to filter files without stat'ing
    every audio file. ``report_skips`` is disabled for that scan so verbose
    exclusion messages are printed once, by the audio scan.
    """
    for current_dir, dirnames, filenames in directory.walk():
        current = Path(current_dir)

        kept_dirs: list[str] = []
        for name in dirnames:
            folder = current / name
            if is_excluded(folder, args, is_dir=True):
                if report_skips and args.verbosity.is_verbose:
                    print(f"Skipping {folder} because of exclude pattern.")
                continue
            kept_dirs.append(name)
        dirnames[:] = kept_dirs

        for name in filenames:
            file = current / name
            if only_m3ug and file.suffix.lower() != ".m3ug":
                continue
            if is_excluded(file, args):
                if report_skips and args.verbosity.is_verbose:
                    print(f"Skipping {file} because of exclude pattern.")
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
) -> dict[Path, M3UGFile]:
    """Parse every M3UG file before any audio file is filtered."""
    all_filters: dict[Path, M3UGFile] = {}
    for file in _walk_files(directory, args, report_skips=False, only_m3ug=True):
        _, parsed, _ = process_file(conn, cursor, file, args)
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
) -> None:
    """Add a file to every filter it matches, with its effective sort keys."""
    entry: Path | PlaylistEntry | None = None
    spec_cache: dict[SortSpec, SortValues] = {}
    dedupe_cache: dict[tuple[str, ...], SortValues] = {}
    limit_key_cache: dict[str, SortValue | None] = {}
    for filter_file, parsed in all_filters.items():
        if parsed.no_playlist:
            continue
        if matches_rules(tags, parsed.expression):
            if entry is None:
                entry = playlist_entry(file, tags) if extended else file
            spec = parsed.sort if parsed.sort is not None else default_sort
            if spec not in spec_cache:
                spec_cache[spec] = _sort_values(file, tags, spec)
            duration = None
            if parsed.max_duration is not None and parsed.max_duration > 0:
                duration = duration_seconds(tags.get("duration"))
            dedupe_values: SortValues = ()
            if parsed.dedupe:
                if parsed.dedupe not in dedupe_cache:
                    dedupe_cache[parsed.dedupe] = _tag_values(
                        file,
                        tags,
                        parsed.dedupe,
                    )
                dedupe_values = dedupe_cache[parsed.dedupe]
            limit_key: SortValue | None = None
            if parsed.limit_per is not None and parsed.limit_per.count > 0:
                tag = parsed.limit_per.tag
                if tag not in limit_key_cache:
                    limit_key_cache[tag] = _tag_values(file, tags, (tag,))[0]
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

    """
    if not directory.is_dir():
        raise GenplisError(
            f"Attempted to process {directory} as a directory but it's not a directory"
        )

    start_time = timer()

    if filters is None:
        all_filters = _discover_filters(conn, cursor, directory, args)
        if args.verbosity.is_verbose:
            for filter_file, parsed in all_filters.items():
                print(
                    format_filter_tree(
                        parsed,
                        title=str(filter_file),
                        default_sort=args.config.output.sort,
                    )
                )
    else:
        all_filters = dict(filters)
    matches: dict[Path, list[Match]] = {filter_file: [] for filter_file in all_filters}
    retained: dict[int, tuple[Path, Tags]] | None = {} if retain_tags else None
    processed = 0
    pending: list[ParseItem] = []
    order = 0
    batch = db.WriteBatch(conn, every=COMMIT_EVERY)

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
        )

    try:
        for file in _walk_files(directory, args):
            if file.suffix.lower() == ".m3ug":
                continue

            current_order = order
            order += 1

            if args.jobs <= 1:
                tags, _, _ = process_file(conn, cursor, file, args, batch=batch)
                if tags is None:
                    continue
                handle_tags(current_order, file, tags)
                continue

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

        if args.jobs > 1:
            executor = make_executor(args.jobs, len(pending), args.config.tags)
            if isinstance(executor, ProcessExecutor) and args.verbosity.is_verbose:
                print(f"Parsing with {executor.workers} worker processes")
            try:
                for result in executor.parse(pending):
                    if args.verbosity.is_verbose:
                        for message in result.messages:
                            print(message)
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
        batch.flush()

    all_tags = (
        {file: tags for _, (file, tags) in sorted(retained.items())}
        if retained is not None
        else {}
    )

    # Every filter has already been applied to every file. Sort each match
    # list with its effective spec (worker results can arrive out of order)
    # and write each playlist.
    for filter_file, parsed in all_filters.items():
        if parsed.no_playlist:
            continue
        matched = matches[filter_file]
        spec = parsed.sort if parsed.sort is not None else args.config.output.sort
        _sort_matches(matched, spec)
        if parsed.dedupe:
            matched = _dedupe_matches(matched)
        matched = _select_matches(
            matched, parsed.limit, parsed.limit_per, parsed.max_duration
        )
        if args.verbosity.is_verbose:
            print(f"\nFiltering songs and generating playlist for {filter_file}")
            print(f"Sort order: {format_sort_spec(spec)}")
            print(f"Files that match the filter {filter_file}:")
            for match in matched:
                path = (
                    match.entry.path
                    if isinstance(match.entry, PlaylistEntry)
                    else match.entry
                )
                print(f"  {path}")
        if args.verbosity.shows_progress:
            print(f"Filter file {filter_file} matched {len(matched)} songs")
        if matched:
            playlist_file = filter_file.with_suffix(".m3u")
            if args.verbosity.shows_progress:
                print(f"Creating playlist {playlist_file}")
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
            )
        matches[filter_file].clear()
        matched.clear()

    end_time = timer()
    process_time = end_time - start_time
    used_memory = psutil.Process().memory_info().rss / (1024 * 1024)
    if args.verbosity.shows_normal_output:
        print(f"Processed {processed} files in {process_time:.3f} seconds")
        print(f"Total RAM usage: {used_memory} MiB")

    return all_tags, all_filters


def process_file(
    conn: sqlite3.Connection,
    cursor: sqlite3.Cursor,
    file: Path,
    args: Args,
    *,
    batch: db.WriteBatch | None = None,
) -> tuple[Tags | None, M3UGFile | None, db.CacheStatus]:
    """Process a single file.

    Returns a tuple in the form (tags, parsed_m3ug, cache_status), where tags
    is a dictionary, parsed_m3ug is ``None`` for non-M3UG files and
    cache_status is the state of the tag cache when the file was found.

    When ``batch`` is given, cache writes go through it instead of committing
    immediately. ``None`` preserves the single-file behaviour of committing
    each write before returning.

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
        parsed = parse_m3ug(content, str(file), args.verbosity)
        return None, parsed, db.CacheStatus.MISS

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
        )
        conn.commit()
    return tags, None, cache_status


def filter_songs(
    files_and_tags: Mapping[Path, Tags],
    filter_file: Path,
    expression: FilterNode | None,
    verbosity: Verbosity = Verbosity.NORMAL,
) -> list[Path]:
    if verbosity.is_verbose:
        print(f"\nFiltering songs and generating playlist for {filter_file}")

    filtered_songs: list[Path] = []
    for file, tags in files_and_tags.items():
        if matches_rules(tags, expression):
            filtered_songs.append(file)

    if verbosity.is_verbose:
        print(f"Files that match the filter {filter_file}:")
        for song in filtered_songs:
            print(f"  {song}")

    return filtered_songs


def clean_database(
    conn: sqlite3.Connection,
    cursor: sqlite3.Cursor,
    root: Path | None,
    db_path: Path,
    verbosity: Verbosity = Verbosity.NORMAL,
) -> CleanStats:
    """Remove cache entries for missing files and reclaim their space.

    When root is given, only entries under root are considered. VACUUM runs
    only when something was removed, so the reported size reduction is the
    actual change on disk.

    """
    conn.commit()
    size_before = db_path.stat().st_size

    removed = db.remove_missing_files(cursor, root)
    conn.commit()
    if removed:
        db.vacuum_database(conn)
    size_after = db_path.stat().st_size

    if verbosity.is_verbose:
        for path in removed:
            print(f"Removed stale cache entry for {path}")

    stats = CleanStats(
        removed=tuple(removed),
        size_before=size_before,
        size_after=size_after,
    )
    entry_word = "entry" if len(removed) == 1 else "entries"
    if verbosity.shows_normal_output:
        print(f"Removed {len(removed)} stale {entry_word} from the cache database.")
        print(
            "Database size: "
            f"{format_size(size_before)} -> {format_size(size_after)} "
            f"({format_size(stats.bytes_saved)} saved)."
        )
    return stats


def _run(args: Args) -> None:
    """Run genplis with resolved arguments."""
    if args.verbosity.is_verbose:
        if args.config_disabled:
            print("Configuration disabled with --no-config")
        elif args.config.source is not None:
            print(f"Using config file {args.config.source}")
        else:
            print("No config file found; using defaults")
        print(f"Using {args.db_path} for genplis DB")

    if args.path is None and not args.db_path.exists():
        if args.verbosity.shows_normal_output:
            print("Database does not exist; nothing to clean.")
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

            if args.path is not None:
                if args.display_tags:
                    display_tag_stats(conn, cursor, args)
                else:
                    process_path(conn, cursor, args)
            if args.clean:
                clean_database(
                    conn,
                    cursor,
                    args.path,
                    args.db_path,
                    verbosity=args.verbosity,
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
        parser.exit(1, f"genplis: error: {exc}\n")

    try:
        _run(args)
    except GenplisError as exc:
        print(f"genplis: error: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
