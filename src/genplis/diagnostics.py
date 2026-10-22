"""Human-readable diagnostics for parsed M3UG filters."""

from __future__ import annotations

from pathlib import Path

from .m3ug import (
    AndNode,
    FilterNode,
    IncludeInfo,
    M3UGFile,
    NotNode,
    OrNode,
    RuleNode,
    SourceLocation,
    ValueNode,
    is_number,
)
from .sorting import SortSpec, format_sort_spec


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
        rule.name_node.name.lower() == "duration"
        and is_number(value)
        and rule.value_node.literal is not None
    ):
        text += f" ({_format_seconds(float(value))}s)"
    return text


def format_rule(rule: RuleNode, current_filename: str | None) -> str:
    """Format one rule with its source label and case handling."""
    text = (
        f"{rule.name_node.name} {rule.OPERATOR} {format_rule_value(rule)}"
        f"{_source_label(rule.source, current_filename)}"
    )
    if rule.case_sensitive:
        text += " [case-sensitive]"
    return text


def _directive_lines(
    parsed: M3UGFile,
    default_sort: SortSpec | None,
    indent: str,
) -> list[str]:
    rows: list[str] = []
    row = f"{indent}  "
    if parsed.sort is not None:
        rows.append(f"{row}sort: {format_sort_spec(parsed.sort)}")
    elif default_sort is not None:
        rows.append(f"{row}sort: {format_sort_spec(default_sort)} (default)")
    if parsed.limit is not None:
        suffix = " (disabled)" if parsed.limit == 0 else ""
        rows.append(f"{row}limit: {parsed.limit}{suffix}")
    if parsed.limit_per is not None:
        suffix = " (disabled)" if parsed.limit_per.count == 0 else ""
        rows.append(
            f"{row}per-tag limit: {parsed.limit_per.count} per "
            f"{parsed.limit_per.tag}{suffix}"
        )
    if parsed.dedupe is not None:
        keys = ", ".join(parsed.dedupe)
        rows.append(f"{row}dedupe: {keys if keys else '(disabled)'}")
    if parsed.max_duration is not None:
        suffix = " (disabled)" if parsed.max_duration == 0 else ""
        rows.append(
            f"{row}max duration: {_format_seconds(parsed.max_duration)}s{suffix}"
        )
    if parsed.no_playlist:
        rows.append(f"{row}no playlist: yes (@NO-PLAYLIST)")
    if not rows:
        return []
    return [f"{indent}directives:", *rows]


def _render_include(
    include: IncludeInfo,
    current_filename: str | None,
    indent: str,
) -> list[str]:
    header = (
        f"{indent}@INCLUDE {include.raw_path} "
        f"({_filename_label(current_filename)}:{include.line}) -> {include.path}"
    )
    lines = [header]
    if include.file.expression is None:
        lines.append(f"{indent}  (no rules; directives only)")
        lines.extend(_directive_lines(include.file, None, f"{indent}  "))
        return lines
    lines.extend(_render_file_contents(include.file, f"{indent}  "))
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
) -> list[str]:
    if isinstance(node, RuleNode):
        return [f"{indent}{format_rule(node, current_filename)}"]
    if isinstance(node, NotNode):
        return [
            f"{indent}NOT",
            *_render_expression(node.node, current_filename, f"{indent}  "),
        ]
    if isinstance(node, AndNode | OrNode):
        operator = "AND" if isinstance(node, AndNode) else "OR"
        lines = [f"{indent}{operator}"]
        for child in node.nodes:
            lines.extend(_render_expression(child, current_filename, f"{indent}  "))
        return lines
    return [f"{indent}{node!r}"]


def _render_file_contents(parsed: M3UGFile, indent: str) -> list[str]:
    children: list[tuple[str, IncludeInfo | FilterNode]] = [
        ("include", include)
        for include in parsed.includes
        if include.file.expression is not None
    ]
    children.extend(("node", node) for node in _own_nodes(parsed))

    lines: list[str] = []
    if len(children) > 1:
        lines.append(f"{indent}AND")
        child_indent = f"{indent}  "
    else:
        child_indent = indent

    rendered: dict[int, list[str]] = {}
    for index, (_kind, value) in enumerate(children):
        if isinstance(value, IncludeInfo):
            rendered[index] = _render_include(value, parsed.filename, child_indent)
        else:
            rendered[index] = _render_expression(value, parsed.filename, child_indent)

    # Keep directive-only includes in source order without making them
    # logical AND children.
    include_positions: dict[int, list[str]] = {}
    rule_child_index = 0
    for include in parsed.includes:
        if include.file.expression is None:
            include_positions.setdefault(rule_child_index, []).extend(
                _render_include(include, parsed.filename, child_indent)
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
) -> str:
    """Render a parsed filter, including its nested ``@INCLUDE`` files."""
    lines: list[str] = []
    if title is not None:
        lines.append(title)
        indent = "  "
    else:
        indent = ""

    if parsed.expression is None:
        lines.append(f"{indent}(always)")
    else:
        lines.extend(_render_file_contents(parsed, indent))

    lines.extend(_directive_lines(parsed, default_sort, indent))
    return "\n".join(lines)
