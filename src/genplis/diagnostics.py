"""Human-readable diagnostics for parsed M3UG filters."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

from .m3ug import (
    AndNode,
    FilterNode,
    IncludeInfo,
    LimitPerTag,
    M3UGFile,
    NotNode,
    OrNode,
    RuleExplanation,
    RuleNode,
    SourceLocation,
    TagLookup,
    ValueNode,
    is_number,
)
from .output import ColorRole, Palette
from .sorting import SortSpec, SortValue, SortValues, format_sort_spec
from .types import TagValue


@dataclass(frozen=True, slots=True)
class RuleTrace:
    """One evaluated rule and the tag lookup that decided it."""

    rule: RuleNode
    passed: bool
    lookup: TagLookup


@dataclass(frozen=True, slots=True)
class ExpressionTrace:
    """The traced evaluation of one filter expression node."""

    node: FilterNode
    passed: bool
    children: tuple[ExpressionTrace, ...] = ()
    rule: RuleTrace | None = None
    skipped: bool = False
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class IncludeTrace:
    """The traced evaluation of one ``@INCLUDE`` directive."""

    include: IncludeInfo
    passed: bool | None
    file: FileTrace | None = None
    skipped: bool = False
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class FileTrace:
    """The traced evaluation of a whole ``M3UGFile``."""

    file: M3UGFile
    passed: bool
    includes: tuple[IncludeTrace, ...]
    own_expression: ExpressionTrace | None
    consulted: tuple[TagLookup, ...]
    skipped: bool = False
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class PlaylistInput:
    """The playlist settings and per-file values used for one filter."""

    filter_file: Path
    sort: SortSpec
    sort_values: SortValues
    sort_is_default: bool
    dedupe: tuple[str, ...] | None
    dedupe_values: SortValues
    limit: int | None
    limit_per: LimitPerTag | None
    limit_key: SortValue | None
    max_duration: float | None
    duration: float | None
    no_playlist: bool
    exclusion: str | None = None


@dataclass(frozen=True, slots=True)
class PlaylistInputsTrace:
    """Playlist inputs for every filter considered by a trace."""

    inputs: tuple[PlaylistInput, ...]


@dataclass(slots=True)
class FilterSelectionTrace:
    """Where the traced file ended up while selecting one playlist."""

    filter_file: Path
    sort: SortSpec = ()
    sort_is_default: bool = False
    total_matches: int = 0
    sorted_position: int | None = None
    sort_values: SortValues = ()
    dedupe: tuple[str, ...] | None = None
    dedupe_values: SortValues = ()
    dedupe_result: str = ""
    dedupe_winner: Path | None = None
    limit: int | None = None
    limit_result: str = ""
    limit_per: LimitPerTag | None = None
    limit_key: SortValue | None = None
    per_tag_result: str = ""
    max_duration: float | None = None
    duration_result: str = ""
    selected: bool = False
    position: int | None = None
    no_playlist: bool = False
    considered: bool = True
    skipped: bool = False
    reason: str | None = None


@dataclass(slots=True)
class SelectionTrace:
    """Selection results for the target file across several filters."""

    target: Path
    filters: dict[Path, FilterSelectionTrace] = field(default_factory=dict)


def _filename_label(filename: str | None) -> str:
    if filename is None:
        return "N/A"
    if filename == "N/A":
        return filename
    return Path(filename).name


def _source_label(source: SourceLocation | None, current_filename: str | None) -> str:
    if source is None:
        return ""
    if current_filename is None or source.filename == current_filename:
        return f" (line {source.line})"
    return f" ({_filename_label(source.filename)}:{source.line})"


def _format_seconds(value: float) -> str:
    if value.is_integer():
        return str(int(value))
    return f"{value:g}"


def _format_value(value: ValueNode) -> str:
    if value.literal is not None:
        return value.literal
    return repr(value.value)


def format_rule_value(rule: RuleNode) -> str:
    """Format a rule's expected value using its original source token."""
    text = _format_value(rule.value_node)
    value = rule.value_node.value
    if (
        rule.name_node.name.lower() in {"duration", "*duration"}
        and is_number(value)
        and rule.value_node.literal is not None
    ):
        text += f" ({_format_seconds(float(value))}s)"
    return text


def format_rule(
    rule: RuleNode,
    current_filename: str | None,
    palette: Palette | None = None,
) -> str:
    """Format one rule with its source label and case handling."""
    colors = Palette() if palette is None else palette
    text = (
        f"{colors.tag(rule.name_node.name)} "
        f"{colors.operator(rule.OPERATOR)} "
        f"{colors.value(format_rule_value(rule))}"
        f"{colors.source(_source_label(rule.source, current_filename))}"
    )
    if rule.case_sensitive:
        text += f" {colors.directive('[case-sensitive]')}"
    return text


def _directive_lines(
    parsed: M3UGFile,
    default_sort: SortSpec | None,
    indent: str,
    palette: Palette,
) -> list[str]:
    rows: list[str] = []
    row = f"{indent}  "
    if parsed.sort is not None:
        text = f"sort: {format_sort_spec(parsed.sort)}"
        rows.append(f"{row}{palette.directive(text)}")
    elif default_sort is not None:
        text = f"sort: {format_sort_spec(default_sort)} (default)"
        rows.append(f"{row}{palette.directive(text)}")
    if parsed.limit is not None:
        suffix = " (disabled)" if parsed.limit == 0 else ""
        rows.append(f"{row}{palette.directive(f'limit: {parsed.limit}{suffix}')}")
    if parsed.limit_per is not None:
        suffix = " (disabled)" if parsed.limit_per.count == 0 else ""
        text = (
            f"per-tag limit: {parsed.limit_per.count} per "
            f"{parsed.limit_per.tag}{suffix}"
        )
        rows.append(f"{row}{palette.directive(text)}")
    if parsed.dedupe is not None:
        keys = ", ".join(parsed.dedupe)
        text = f"dedupe: {keys if keys else '(disabled)'}"
        rows.append(f"{row}{palette.directive(text)}")
    if parsed.max_duration is not None:
        suffix = " (disabled)" if parsed.max_duration == 0 else ""
        text = f"max duration: {_format_seconds(parsed.max_duration)}s{suffix}"
        rows.append(f"{row}{palette.directive(text)}")
    if parsed.no_playlist:
        text = "no playlist: yes (@NO-PLAYLIST)"
        rows.append(f"{row}{palette.directive(text)}")
    if not rows:
        return []
    return [f"{indent}{palette.directive('directives:')}", *rows]


def _include_header(
    include: IncludeInfo,
    parent_filename: str | None,
    palette: Palette,
) -> str:
    directive = palette.directive(f"@INCLUDE {include.raw_path}")
    source = palette.source(f"({_filename_label(parent_filename)}:{include.line})")
    return f"{directive} {source} -> {include.path}"


def _render_include(
    include: IncludeInfo,
    current_filename: str | None,
    indent: str,
    palette: Palette,
) -> list[str]:
    header = f"{indent}{_include_header(include, current_filename, palette)}"
    lines = [header]
    if include.file.expression is None:
        lines.append(f"{indent}  {palette.source('(no rules; directives only)')}")
        lines.extend(_directive_lines(include.file, None, f"{indent}  ", palette))
        return lines
    lines.extend(_render_file_contents(include.file, f"{indent}  ", palette))
    return lines


def _own_nodes(parsed: M3UGFile) -> tuple[FilterNode, ...]:
    expression = parsed.own_expression
    if expression is None:
        return ()
    if isinstance(expression, AndNode):
        return expression.nodes
    return (expression,)


def _render_expression(
    node: FilterNode,
    current_filename: str | None,
    indent: str,
    palette: Palette,
) -> list[str]:
    if isinstance(node, RuleNode):
        return [f"{indent}{format_rule(node, current_filename, palette)}"]
    if isinstance(node, NotNode):
        return [
            f"{indent}{palette.operator('NOT')}",
            *_render_expression(
                node.node,
                current_filename,
                f"{indent}  ",
                palette,
            ),
        ]
    if isinstance(node, AndNode | OrNode):
        operator = palette.operator("AND" if isinstance(node, AndNode) else "OR")
        lines = [f"{indent}{operator}"]
        for child in node.nodes:
            lines.extend(
                _render_expression(
                    child,
                    current_filename,
                    f"{indent}  ",
                    palette,
                )
            )
        return lines
    return [f"{indent}{node!r}"]


def _render_file_contents(
    parsed: M3UGFile,
    indent: str,
    palette: Palette,
) -> list[str]:
    children: list[tuple[str, IncludeInfo | FilterNode]] = [
        ("include", include)
        for include in parsed.includes
        if include.file.expression is not None
    ]
    children.extend(("node", node) for node in _own_nodes(parsed))

    lines: list[str] = []
    if len(children) > 1:
        lines.append(f"{indent}{palette.operator('AND')}")
        child_indent = f"{indent}  "
    else:
        child_indent = indent

    rendered: dict[int, list[str]] = {}
    for index, (_kind, value) in enumerate(children):
        if isinstance(value, IncludeInfo):
            rendered[index] = _render_include(
                value,
                parsed.filename,
                child_indent,
                palette,
            )
        else:
            rendered[index] = _render_expression(
                value,
                parsed.filename,
                child_indent,
                palette,
            )

    # Keep directive-only includes in source order without making them
    # logical AND children.
    include_positions: dict[int, list[str]] = {}
    rule_child_index = 0
    for include in parsed.includes:
        if include.file.expression is None:
            include_positions.setdefault(rule_child_index, []).extend(
                _render_include(
                    include,
                    parsed.filename,
                    child_indent,
                    palette,
                )
            )
        else:
            rule_child_index += 1

    for index in range(len(children) + 1):
        lines.extend(include_positions.get(index, []))
        if index in rendered:
            lines.extend(rendered[index])
    return lines


def format_filter_tree(
    parsed: M3UGFile,
    *,
    title: str | None = None,
    default_sort: SortSpec | None = None,
    palette: Palette | None = None,
) -> str:
    """Render a parsed filter, including its nested ``@INCLUDE`` files."""
    colors = Palette() if palette is None else palette
    lines: list[str] = []
    if title is not None:
        lines.append(colors.title(title))
        indent = "  "
    else:
        indent = ""

    if parsed.expression is None:
        lines.append(f"{indent}{colors.source('(always)')}")
    else:
        lines.extend(_render_file_contents(parsed, indent, colors))

    lines.extend(_directive_lines(parsed, default_sort, indent, colors))
    return "\n".join(lines)


def _rule_expression_trace(
    rule: RuleNode, tags: Mapping[str, TagValue]
) -> ExpressionTrace:
    explanation: RuleExplanation = rule.explain(tags)
    return ExpressionTrace(
        node=rule,
        passed=explanation.passed,
        rule=RuleTrace(
            rule=rule,
            passed=explanation.passed,
            lookup=explanation.lookup,
        ),
    )


def trace_expression(
    node: FilterNode,
    tags: Mapping[str, TagValue],
    *,
    skipped: bool = False,
    reason: str | None = None,
) -> ExpressionTrace:
    """Evaluate an expression and record every visited node."""
    if skipped:
        return ExpressionTrace(
            node=node,
            passed=False,
            skipped=True,
            reason=reason,
        )
    if isinstance(node, RuleNode):
        return _rule_expression_trace(node, tags)
    if isinstance(node, NotNode):
        child = trace_expression(node.node, tags)
        return ExpressionTrace(
            node=node,
            passed=not child.passed,
            children=(child,),
        )
    if isinstance(node, AndNode):
        children: list[ExpressionTrace] = []
        failed = False
        for child_node in node.nodes:
            if failed:
                children.append(
                    trace_expression(
                        child_node,
                        tags,
                        skipped=True,
                        reason="short-circuited: an earlier AND child failed",
                    )
                )
                continue
            child = trace_expression(child_node, tags)
            children.append(child)
            if not child.passed:
                failed = True
        return ExpressionTrace(
            node=node,
            passed=not failed,
            children=tuple(children),
        )
    if isinstance(node, OrNode):
        children = []
        passed = False
        for child_node in node.nodes:
            if passed:
                children.append(
                    trace_expression(
                        child_node,
                        tags,
                        skipped=True,
                        reason="short-circuited: an earlier OR child passed",
                    )
                )
                continue
            child = trace_expression(child_node, tags)
            children.append(child)
            if child.passed:
                passed = True
        return ExpressionTrace(
            node=node,
            passed=passed,
            children=tuple(children),
        )
    return ExpressionTrace(node=node, passed=node.apply(tags))


def _collect_expression_lookups(
    trace: ExpressionTrace,
    seen: set[str],
    collected: list[TagLookup],
) -> None:
    if trace.skipped:
        return
    if trace.rule is not None:
        lookup = trace.rule.lookup
        if lookup.requested not in seen:
            seen.add(lookup.requested)
            collected.append(lookup)
    for child in trace.children:
        _collect_expression_lookups(child, seen, collected)


def _collect_consulted(
    includes: tuple[IncludeTrace, ...],
    own_expression: ExpressionTrace | None,
) -> tuple[TagLookup, ...]:
    collected: list[TagLookup] = []
    seen: set[str] = set()
    for include in includes:
        if include.file is None:
            continue
        for lookup in include.file.consulted:
            if lookup.requested not in seen:
                seen.add(lookup.requested)
                collected.append(lookup)
    if own_expression is not None:
        _collect_expression_lookups(own_expression, seen, collected)
    return tuple(collected)


def trace_file(parsed: M3UGFile, tags: Mapping[str, TagValue]) -> FileTrace:
    """Evaluate a parsed file, following includes and short-circuiting."""
    includes: list[IncludeTrace] = []
    short_reason: str | None = None
    for include in parsed.includes:
        if include.file.expression is None:
            includes.append(IncludeTrace(include=include, passed=None, file=None))
            continue
        if short_reason is not None:
            includes.append(
                IncludeTrace(
                    include=include,
                    passed=None,
                    skipped=True,
                    reason=short_reason,
                )
            )
            continue
        child = trace_file(include.file, tags)
        includes.append(
            IncludeTrace(
                include=include,
                passed=child.passed,
                file=child,
            )
        )
        if not child.passed:
            short_reason = f"short-circuited: include {include.path.name} failed"

    include_traces = tuple(includes)
    if parsed.own_expression is None:
        own_trace = None
        passed = short_reason is None
    elif short_reason is not None:
        own_trace = trace_expression(
            parsed.own_expression,
            tags,
            skipped=True,
            reason=short_reason,
        )
        passed = False
    else:
        own_trace = trace_expression(parsed.own_expression, tags)
        passed = own_trace.passed

    return FileTrace(
        file=parsed,
        passed=passed,
        includes=include_traces,
        own_expression=own_trace,
        consulted=_collect_consulted(include_traces, own_trace),
    )


def _status(trace: ExpressionTrace | IncludeTrace | FileTrace) -> str:
    if trace.skipped:
        return "SKIP"
    if trace.passed is None:
        return ""
    return "PASS" if trace.passed else "FAIL"


def _paint_status(status: str, palette: Palette) -> str:
    role = {
        "PASS": ColorRole.PASS,
        "FAIL": ColorRole.FAIL,
        "SKIP": ColorRole.SKIP,
    }.get(status)
    return status if role is None else palette.paint(role, status)


def _format_value_or_missing(value: object) -> str:
    if value is None:
        return "<missing>"
    return repr(value)


def _format_lookup(lookup: TagLookup, palette: Palette) -> str:
    if lookup.source == "missing":
        text = f"missing tag {palette.tag(lookup.requested)}"
        if lookup.note is not None:
            text += f" {palette.source(f'({lookup.note})')}"
        return text
    if lookup.source == "calculated":
        if lookup.requested not in {"rating", "*rating"}:
            return (
                f"calculated {palette.tag(lookup.requested[1:])} = "
                f"{palette.value(_format_value_or_missing(lookup.normalized))}"
            )
        source = lookup.key or "fmps_rating"
        return (
            f"calculated rating = "
            f"{palette.value(_format_value_or_missing(lookup.normalized))} "
            f"(from {palette.tag(source)})"
        )
    text = (
        f"tag {palette.tag(lookup.key or lookup.requested)} = "
        f"{palette.value(_format_value_or_missing(lookup.raw))}"
    )
    if lookup.normalized != lookup.raw:
        text += f" -> {palette.value(_format_value_or_missing(lookup.normalized))}"
    if lookup.note is not None:
        text += f" {palette.source(f'({lookup.note})')}"
    return text


def _expression_label(node: FilterNode) -> str:
    if isinstance(node, RuleNode):
        return f"{node.name_node.name} {node.OPERATOR}"
    if isinstance(node, AndNode):
        return "AND"
    if isinstance(node, OrNode):
        return "OR"
    if isinstance(node, NotNode):
        return "NOT"
    return type(node).__name__


def _render_expression_trace(
    trace: ExpressionTrace,
    current_filename: str | None,
    indent: str,
    palette: Palette,
) -> list[str]:
    status = _paint_status(_status(trace), palette)
    if trace.rule is not None:
        label = format_rule(trace.rule.rule, current_filename, palette)
        line = f"{indent}{status} {label}"
        if trace.skipped and trace.reason is not None:
            line += f" {palette.source(f'({trace.reason})')}"
        lines = [line]
        if not trace.skipped:
            lines.append(f"{indent}  {_format_lookup(trace.rule.lookup, palette)}")
        return lines

    if isinstance(trace.node, RuleNode):
        label = format_rule(trace.node, current_filename, palette)
    else:
        label = palette.operator(_expression_label(trace.node))
    line = f"{indent}{status} {label}"
    if trace.skipped:
        if trace.reason is not None:
            line += f" {palette.source(f'({trace.reason})')}"
        return [line]
    lines = [line]
    for child in trace.children:
        lines.extend(
            _render_expression_trace(
                child,
                current_filename,
                f"{indent}  ",
                palette,
            )
        )
    return lines


def _render_file_body(
    trace: FileTrace,
    current_filename: str | None,
    indent: str,
    palette: Palette,
) -> list[str]:
    lines: list[str] = []
    for include in trace.includes:
        header = _include_header(include.include, current_filename, palette)
        if include.skipped:
            line = f"{indent}{_paint_status('SKIP', palette)} {header}"
            if include.reason is not None:
                line += f" {palette.source(f'({include.reason})')}"
            lines.append(line)
            continue
        if include.passed is None:
            lines.append(f"{indent}{header}")
            lines.append(f"{indent}  {palette.source('(no rules; directives only)')}")
            lines.extend(
                _directive_lines(
                    include.include.file,
                    None,
                    f"{indent}  ",
                    palette,
                )
            )
            continue
        status = _paint_status(
            "PASS" if include.passed else "FAIL",
            palette,
        )
        lines.append(f"{indent}{status} {header}")
        if include.file is not None:
            lines.extend(
                _render_file_body(
                    include.file,
                    include.file.file.filename,
                    f"{indent}  ",
                    palette,
                )
            )
    if trace.own_expression is not None:
        lines.extend(
            _render_expression_trace(
                trace.own_expression,
                current_filename,
                indent,
                palette,
            )
        )
    elif not trace.includes:
        lines.append(f"{indent}{palette.source('(always)')}")
    return lines


def format_file_trace(
    trace: FileTrace,
    *,
    title: str | None = None,
    palette: Palette | None = None,
) -> str:
    """Render a traced file as an annotated tree."""
    colors = Palette() if palette is None else palette
    label = title if title is not None else _filename_label(trace.file.filename)
    lines = [f"{colors.title(label)}: {_paint_status(_status(trace), colors)}"]
    lines.extend(_render_file_body(trace, trace.file.filename, "  ", colors))
    return "\n".join(lines)


def format_tags_consulted(
    consulted: tuple[TagLookup, ...],
    *,
    indent: str = "",
    palette: Palette | None = None,
) -> str:
    """Render the tags a trace actually consulted, in first-use order."""
    colors = Palette() if palette is None else palette
    heading = colors.title("tags consulted:")
    if not consulted:
        return f"{indent}{heading} {colors.source('(none)')}"
    lines = [f"{indent}{heading}"]
    for lookup in consulted:
        detail = ""
        if lookup.source == "missing":
            detail = " (missing)"
        elif lookup.source == "calculated":
            detail = " (calculated)"
        elif lookup.key is not None and lookup.key != lookup.requested:
            detail = f" (key {lookup.key})"
        lines.append(f"{indent}  {colors.tag(lookup.requested)}{colors.source(detail)}")
    return "\n".join(lines)


def format_playlist_input(
    entry: PlaylistInput,
    *,
    selection_simulated: bool = False,
    palette: Palette | None = None,
) -> str:
    """Render the deterministic playlist inputs for one filter."""
    colors = Palette() if palette is None else palette
    lines = [colors.title("playlist inputs:")]
    sort_suffix = " (default)" if entry.sort_is_default else ""
    lines.append(
        f"  {colors.directive('sort:')} "
        f"{colors.value(format_sort_spec(entry.sort))}"
        f"{colors.source(sort_suffix)}"
    )
    names = [key.name for key in entry.sort if not key.is_random]
    for name, value in zip(names, entry.sort_values, strict=True):
        suffix = " (sorts last)" if value is None else ""
        lines.append(
            f"    {colors.tag(name)} = "
            f"{colors.value(_format_value_or_missing(value))}"
            f"{colors.source(suffix)}"
        )
    for key in entry.sort:
        if key.is_random:
            seed = "unseeded" if key.seed is None else f"seed {key.seed}"
            lines.append(f"    {colors.directive('random:')} {colors.value(seed)}")

    if entry.dedupe is not None:
        if not entry.dedupe:
            lines.append(
                f"  {colors.directive('dedupe:')} {colors.source('(disabled)')}"
            )
        else:
            lines.append(
                f"  {colors.directive('dedupe:')} "
                f"{colors.value(', '.join(entry.dedupe))}"
            )
            for name, value in zip(entry.dedupe, entry.dedupe_values, strict=True):
                suffix = " (kept)" if value is None else ""
                lines.append(
                    f"    {colors.tag(name)} = "
                    f"{colors.value(_format_value_or_missing(value))}"
                    f"{colors.source(suffix)}"
                )

    if entry.limit is not None:
        suffix = " (disabled)" if entry.limit == 0 else ""
        lines.append(
            f"  {colors.directive('limit:')} "
            f"{colors.value(str(entry.limit))}{colors.source(suffix)}"
        )

    if entry.limit_per is not None:
        per_tag = entry.limit_per
        suffix = " (disabled)" if per_tag.count == 0 else ""
        lines.append(
            f"  {colors.directive('per-tag limit:')} "
            f"{colors.value(str(per_tag.count))} per "
            f"{colors.tag(per_tag.tag)}{colors.source(suffix)}"
        )
        if per_tag.count > 0:
            if entry.limit_key is None:
                lines.append(
                    f"    {colors.tag(per_tag.tag)} = "
                    f"{colors.source('<missing>')} "
                    f"{colors.warning('(file would be skipped)')}"
                )
            else:
                lines.append(
                    f"    {colors.tag(per_tag.tag)} = "
                    f"{colors.value(_format_value_or_missing(entry.limit_key))}"
                )

    if entry.max_duration is not None:
        suffix = " (disabled)" if entry.max_duration == 0 else ""
        lines.append(
            f"  {colors.directive('max duration:')} "
            f"{colors.value(f'{_format_seconds(entry.max_duration)}s')}"
            f"{colors.source(suffix)}"
        )
        if entry.duration is None:
            lines.append(
                f"    {colors.directive('target duration:')} "
                f"{colors.value('0s')} {colors.source('(missing)')}"
            )
        else:
            lines.append(
                f"    {colors.directive('target duration:')} "
                f"{colors.value(f'{_format_seconds(entry.duration)}s')}"
            )

    if entry.no_playlist:
        lines.append(
            f"  {colors.directive('no playlist:')} "
            f"{colors.value('yes')} {colors.directive('(@NO-PLAYLIST)')}"
        )

    if entry.no_playlist:
        lines.append(
            f"  {colors.directive('selection:')} "
            f"{colors.directive('no playlist (@NO-PLAYLIST)')}"
        )
    elif entry.exclusion is not None:
        lines.append(
            f"  {colors.directive('selection:')} "
            f"{colors.warning(f'excluded: {entry.exclusion}')}"
        )
    elif selection_simulated:
        lines.append(
            f"  {colors.directive('selection:')} {colors.source('simulated below')}"
        )
    else:
        lines.append(
            f"  {colors.directive('selection:')} "
            f"{colors.source('not simulated; use --trace-full')}"
        )
    return "\n".join(lines)


def format_playlist_inputs(
    trace: PlaylistInputsTrace, *, palette: Palette | None = None
) -> str:
    """Render playlist inputs for several filters."""
    colors = Palette() if palette is None else palette
    return "\n\n".join(
        format_playlist_input(entry, palette=colors) for entry in trace.inputs
    )


def format_selection_trace(
    trace: SelectionTrace, *, palette: Palette | None = None
) -> str:
    """Render where the traced file ended up in each playlist."""
    colors = Palette() if palette is None else palette
    lines = [colors.title("selection:")]
    if not trace.filters:
        lines.append(colors.source("  (no filters)"))
        return "\n".join(lines)

    result_key = colors.directive("result:")
    for filter_file, entry in trace.filters.items():
        lines.append(f"  {colors.title(str(filter_file))}")
        if entry.no_playlist:
            lines.append(f"    {result_key} {colors.directive('@NO-PLAYLIST')}")
            continue
        if entry.skipped:
            reason = entry.reason or "scan skipped"
            lines.append(
                f"    {result_key} "
                f"{colors.paint(ColorRole.SKIP, 'SKIPPED')} "
                f"{colors.source(f'({reason})')}"
            )
            continue
        if entry.reason == "no match" or (
            entry.sorted_position is None and entry.total_matches == 0
        ):
            lines.append(f"    {result_key} {colors.paint(ColorRole.FAIL, 'NO MATCH')}")
            continue

        lines.append(
            f"    {colors.directive('matches:')} "
            f"{colors.value(str(entry.total_matches))}"
        )
        if entry.sorted_position is not None:
            lines.append(
                f"    {colors.directive('sorted position:')} "
                f"{colors.value(str(entry.sorted_position))} of "
                f"{colors.value(str(entry.total_matches))}"
            )
        sort_suffix = " (default)" if entry.sort_is_default else ""
        lines.append(
            f"    {colors.directive('sort:')} "
            f"{colors.value(format_sort_spec(entry.sort))}"
            f"{colors.source(sort_suffix)}"
        )
        names = [key.name for key in entry.sort if not key.is_random]
        for name, value in zip(names, entry.sort_values, strict=True):
            suffix = " (sorts last)" if value is None else ""
            lines.append(
                f"      {colors.tag(name)} = "
                f"{colors.value(_format_value_or_missing(value))}"
                f"{colors.source(suffix)}"
            )

        if entry.dedupe is not None:
            if entry.dedupe:
                result = entry.dedupe_result or "not reached"
                result_color = (
                    colors.warning(result)
                    if result.startswith("excluded:")
                    else colors.value(result)
                )
                lines.append(f"    {colors.directive('dedupe:')} {result_color}")
                if entry.dedupe_winner is not None:
                    lines.append(
                        f"      {colors.directive('winner:')} "
                        f"{colors.value(str(entry.dedupe_winner))}"
                    )
            else:
                lines.append(
                    f"    {colors.directive('dedupe:')} {colors.source('(disabled)')}"
                )
        for label, result in (
            ("count:", entry.limit_result or "not reached"),
            ("per-tag:", entry.per_tag_result or "not reached"),
            ("duration:", entry.duration_result or "not reached"),
        ):
            result_color = (
                colors.warning(result)
                if result.startswith("excluded:")
                else colors.value(result)
            )
            lines.append(f"    {colors.directive(label)} {result_color}")
        if not entry.selected and entry.reason is not None:
            lines.append(
                f"    {colors.directive('reason:')} {colors.warning(entry.reason)}"
            )
        if entry.selected:
            lines.append(
                f"    {result_key} "
                f"{colors.paint(ColorRole.PASS, 'IN PLAYLIST')} at position "
                f"{colors.value(str(entry.position))}"
            )
        else:
            lines.append(
                f"    {result_key} {colors.paint(ColorRole.FAIL, 'NOT IN PLAYLIST')}"
            )
    return "\n".join(lines)
