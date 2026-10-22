"""Collect and render tag statistics for a music collection."""

from collections import Counter
from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass, field

from .tags import AUDIO_PROPERTY_TAGS
from .types import TagValue

# A capped counter keeps memory bounded for high-cardinality tags such as
# title or comment. Selected --tag values are collected without a cap.
MAX_DISTINCT_VALUES = 10_000
MAX_EXAMPLES = 3
MAX_EXAMPLE_WIDTH = 40
MAX_EXAMPLES_WIDTH = 72
MAX_DETAIL_VALUE_WIDTH = 80


def _normalize_name(name: str) -> str:
    """Normalize a tag name for case-insensitive matching."""
    return name.strip().lower()


def full_tag_names(requested: Sequence[str]) -> frozenset[str]:
    """Return the accumulator names that need uncapped value counting.

    An unprefixed request also enables the calculated form so that, for
    example, ``--tag duration`` finds ``*duration`` and ``--tag rating`` can
    report both the embedded and calculated rating.
    """
    names: set[str] = set()
    for raw in requested:
        name = _normalize_name(raw)
        if not name:
            continue
        names.add(name)
        if not name.startswith("*"):
            names.add(f"*{name}")
    return frozenset(names)


def _format_raw(raw: TagValue) -> str | None:
    """Format one raw tag value for counting and display."""
    if raw is None:
        return None
    if isinstance(raw, bool):
        return "true" if raw else "false"
    if isinstance(raw, int):
        return str(raw)
    if isinstance(raw, float):
        return str(int(raw)) if raw.is_integer() else str(raw)
    return str(raw)


def iter_tag_values(raw: TagValue) -> Iterable[str]:
    """Yield the individual values of a tag, flattening lists."""
    if isinstance(raw, list):
        for item in raw:
            value = _format_raw(item)
            if value is not None:
                yield value
        return
    value = _format_raw(raw)
    if value is not None:
        yield value


def _collect_values(
    tags: Mapping[str, TagValue],
    *,
    exclude: Collection[str] = (),
) -> dict[str, list[str]]:
    """Return normalized tag names mapped to their values for one file."""
    excluded = {_normalize_name(name) for name in exclude}
    collected: dict[str, list[str]] = {}
    for key, raw in tags.items():
        name = _normalize_name(key)
        if not name or name in excluded:
            continue
        values = list(iter_tag_values(raw))
        if values:
            collected.setdefault(name, []).extend(values)
    return collected


def _value_sort_key(item: tuple[str, int]) -> tuple[int, str, str]:
    """Sort values by descending file count, then case-insensitively."""
    value, files = item
    return -files, value.casefold(), value


def _display_value(value: str, *, max_width: int = MAX_EXAMPLE_WIDTH) -> str:
    """Make a value safe for a one-line table cell."""
    if not value:
        return "<empty>"
    text = value.replace("\r", "\\r").replace("\n", "\\n").replace("\t", "\\t")
    return _shorten(text, max_width)


def _shorten(text: str, max_width: int) -> str:
    if max_width <= 0 or len(text) <= max_width:
        return text
    return text[: max_width - 3] + "..."


@dataclass(slots=True)
class _ValueCounter:
    """Count files per value, optionally capping the distinct values kept."""

    max_distinct: int | None
    counts: Counter[str] = field(default_factory=Counter)
    capped: bool = False

    def add(self, values: Iterable[str]) -> None:
        for value in set(values):
            if value in self.counts:
                self.counts[value] += 1
            elif self.max_distinct is None or len(self.counts) < self.max_distinct:
                self.counts[value] += 1
            else:
                self.capped = True


@dataclass(slots=True)
class _TagAccumulator:
    counter: _ValueCounter
    files: int = 0

    def add_file(self, values: list[str]) -> None:
        if not values:
            return
        self.files += 1
        self.counter.add(values)


@dataclass(frozen=True, slots=True)
class TagValueStat:
    """One distinct value and the number of files that contain it."""

    value: str
    files: int


@dataclass(frozen=True, slots=True)
class TagStat:
    """Statistics for one tag name."""

    name: str
    files: int
    distinct: int
    capped: bool
    examples: tuple[str, ...]
    values: tuple[TagValueStat, ...] = ()


@dataclass(frozen=True, slots=True)
class TagStats:
    """The collected statistics for a scan."""

    files: int
    files_with_embedded: int
    embedded: tuple[TagStat, ...]
    calculated: tuple[TagStat, ...]


class TagStatsCollector:
    """Accumulate tag statistics without retaining every file's tags."""

    def __init__(
        self,
        *,
        full_tags: Collection[str] = (),
        max_distinct: int = MAX_DISTINCT_VALUES,
    ) -> None:
        self._full_tags = frozenset(_normalize_name(name) for name in full_tags)
        self._max_distinct = max_distinct
        self._embedded: dict[str, _TagAccumulator] = {}
        self._calculated: dict[str, _TagAccumulator] = {}
        self.files = 0
        self.files_with_embedded = 0

    def record_file(
        self,
        tags: Mapping[str, TagValue],
        calculated: Mapping[str, TagValue],
    ) -> None:
        """Record the embedded and calculated tags of one supported file."""
        self.files += 1
        embedded = _collect_values(tags, exclude=AUDIO_PROPERTY_TAGS)
        if embedded:
            self.files_with_embedded += 1
        self._record_values(self._embedded, embedded)
        self._record_values(self._calculated, _collect_values(calculated))

    def _record_values(
        self,
        store: dict[str, _TagAccumulator],
        values: Mapping[str, list[str]],
    ) -> None:
        for name, tag_values in values.items():
            accumulator = store.get(name)
            if accumulator is None:
                max_distinct = None if name in self._full_tags else self._max_distinct
                accumulator = _TagAccumulator(_ValueCounter(max_distinct))
                store[name] = accumulator
            accumulator.add_file(tag_values)

    def report(self) -> TagStats:
        """Return an immutable snapshot of the collected statistics."""
        return TagStats(
            files=self.files,
            files_with_embedded=self.files_with_embedded,
            embedded=self._report_store(self._embedded),
            calculated=self._report_store(self._calculated),
        )

    @staticmethod
    def _report_store(store: Mapping[str, _TagAccumulator]) -> tuple[TagStat, ...]:
        stats: list[TagStat] = []
        for name in sorted(store):
            accumulator = store[name]
            counter = accumulator.counter
            values: tuple[TagValueStat, ...] = ()
            if counter.max_distinct is None:
                values = tuple(
                    TagValueStat(value, files)
                    for value, files in sorted(
                        counter.counts.items(), key=_value_sort_key
                    )
                )
            examples = tuple(
                value
                for value, _ in sorted(counter.counts.items(), key=_value_sort_key)[
                    :MAX_EXAMPLES
                ]
            )
            stats.append(
                TagStat(
                    name=name,
                    files=accumulator.files,
                    distinct=len(counter.counts),
                    capped=counter.capped,
                    examples=examples,
                    values=values,
                )
            )
        return tuple(stats)


def _coverage(files: int, total: int) -> str:
    if total <= 0:
        return "n/a"
    return f"{files / total:.1%}"


def _summary_line(report: TagStats) -> str:
    if report.files == 0:
        return "No supported audio files found."
    return (
        f"{report.files_with_embedded:,} of {report.files:,} supported files "
        "have embedded tags"
    )


def _format_table(
    headers: Sequence[str],
    rows: Sequence[Sequence[str]],
    *,
    right: Collection[int] = (),
) -> list[str]:
    """Format a simple two-space-separated table."""
    widths = [
        max(len(row[index]) for row in (headers, *rows))
        for index in range(len(headers))
    ]

    def format_row(row: Sequence[str]) -> str:
        return "  ".join(
            (cell.rjust(width) if index in right else cell.ljust(width))
            for index, (cell, width) in enumerate(zip(row, widths, strict=True))
        ).rstrip()

    lines = [
        format_row(headers),
        format_row(tuple("-" * width for width in widths)),
    ]
    lines.extend(format_row(row) for row in rows)
    return lines


def _summary_rows(report: TagStats, stats: Sequence[TagStat]) -> list[list[str]]:
    rows: list[list[str]] = []
    for stat in stats:
        examples = ", ".join(_display_value(value) for value in stat.examples)
        examples = _shorten(examples, MAX_EXAMPLES_WIDTH)
        rows.append(
            [
                stat.name,
                f"{stat.files:,}",
                _coverage(stat.files, report.files),
                f"{stat.distinct:,}{'+' if stat.capped else ''}",
                examples,
            ]
        )
    return rows


def render_tag_stats(report: TagStats) -> str:
    """Render the summary table for a collection scan."""
    if report.files == 0:
        return _summary_line(report)

    lines = [_summary_line(report), ""]
    headers = ["Tag", "Files", "Coverage", "Distinct", "Examples"]
    if report.embedded:
        lines.append("Embedded tags")
        lines.extend(
            _format_table(
                headers,
                _summary_rows(report, report.embedded),
                right={1, 2, 3},
            )
        )
    else:
        lines.append("No embedded tags found.")

    if report.calculated:
        lines.append("")
        lines.append("Calculated tags")
        lines.extend(
            _format_table(
                headers,
                _summary_rows(report, report.calculated),
                right={1, 2, 3},
            )
        )
    return "\n".join(lines)


def _find_requested_tags(report: TagStats, name: str) -> list[tuple[TagStat, bool]]:
    """Resolve a requested name to embedded and/or calculated tag stats."""
    matches: list[tuple[TagStat, bool]] = []
    if name.startswith("*"):
        matches.extend((stat, True) for stat in report.calculated if stat.name == name)
        return matches

    matches.extend((stat, False) for stat in report.embedded if stat.name == name)
    calculated_name = f"*{name}"
    matches.extend(
        (stat, True) for stat in report.calculated if stat.name == calculated_name
    )
    return matches


def _render_tag_detail(
    report: TagStats,
    stat: TagStat,
    *,
    calculated: bool,
) -> list[str]:
    kind = "calculated" if calculated else "embedded"
    lines = [
        f"Tag: {stat.name} ({kind})",
        (
            f"Files: {stat.files:,} of {report.files:,} "
            f"({_coverage(stat.files, report.files)})"
        ),
        f"Distinct values: {stat.distinct:,}{'+' if stat.capped else ''}",
    ]
    if not stat.values:
        lines.append("No values recorded.")
        return lines

    lines.append("")
    rows = [
        [
            _display_value(value.value, max_width=MAX_DETAIL_VALUE_WIDTH),
            f"{value.files:,}",
            _coverage(value.files, report.files),
        ]
        for value in stat.values
    ]
    lines.extend(_format_table(["Value", "Files", "Coverage"], rows, right={1, 2}))

    if sum(value.files for value in stat.values) > stat.files:
        lines.append("")
        lines.append(
            "A file can contain more than one value, so coverage values "
            "can add up to more than 100%."
        )

    missing = report.files - stat.files
    lines.append("")
    lines.append(
        f"Files without this tag: {missing:,} ({_coverage(missing, report.files)})"
    )
    return lines


def render_tag_details(report: TagStats, requested: Sequence[str]) -> str:
    """Render full value details for the requested tags."""
    if report.files == 0:
        return _summary_line(report)

    lines = [_summary_line(report)]
    seen: set[str] = set()
    for raw in requested:
        name = _normalize_name(raw)
        if not name or name in seen:
            continue
        seen.add(name)

        matches = _find_requested_tags(report, name)
        if not matches:
            lines.append("")
            lines.append(
                f"Tag '{name}' was not found. It may be hidden by [tags] ignore."
            )
            continue
        for stat, calculated in matches:
            lines.append("")
            lines.extend(_render_tag_detail(report, stat, calculated=calculated))
    return "\n".join(lines)
