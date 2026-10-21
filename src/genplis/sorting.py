"""Playlist ordering: sort specs, value normalization, and comparison."""

from __future__ import annotations

import re
from dataclasses import dataclass

from .types import TagValue

INT_RE = re.compile(r"^\d+$")
FLOAT_RE = re.compile(r"^\d+\.\d+$")

type SortValue = int | float | str
type SortValues = tuple[SortValue | None, ...]


class SortSpecError(ValueError):
    """Raised when a sort specification cannot be parsed."""


@dataclass(frozen=True, slots=True)
class SortKey:
    """One key in a playlist sort specification."""

    name: str
    descending: bool = False
    seed: int | None = None

    @property
    def is_random(self) -> bool:
        """Return whether this key shuffles entries instead of comparing them."""
        return self.name == "random"

    def __str__(self) -> str:
        if self.is_random:
            return "random" if self.seed is None else f"random {self.seed}"
        if self.descending:
            return f"{self.name} desc"
        return self.name


type SortSpec = tuple[SortKey, ...]

DEFAULT_SORT_SPEC: SortSpec = (SortKey("filename"),)


def parse_sort_spec(text: str) -> SortSpec:
    """Parse a comma-separated sort specification.

    Each key is a tag name followed by an optional ``asc`` or ``desc``
    direction. The special key ``random`` must be last and accepts an optional
    integer seed. An empty or whitespace-only specification means no ordering,
    which lets configuration disable the default sort.
    """
    if not text.strip():
        return ()

    keys: list[SortKey] = []
    random_seen = False
    for part in text.split(","):
        item = part.strip()
        if not item:
            raise SortSpecError("sort key must not be empty")
        components = item.split()
        name = components[0].lower()

        if random_seen:
            raise SortSpecError("random must be the last sort key")

        if name == "random":
            if len(components) > 2:
                raise SortSpecError(f"invalid random sort key: {item!r}")
            seed = None
            if len(components) == 2:
                seed_text = components[1]
                if seed_text.lower() in {"asc", "desc"}:
                    raise SortSpecError("random cannot take a direction")
                if not INT_RE.match(seed_text):
                    raise SortSpecError(
                        "random accepts only an optional non-negative integer seed"
                    )
                seed = int(seed_text)
            keys.append(SortKey("random", seed=seed))
            random_seen = True
            continue

        if len(components) > 2:
            raise SortSpecError(f"invalid sort key: {item!r}")
        if len(components) == 2:
            direction = components[1].lower()
            if direction not in {"asc", "desc"}:
                raise SortSpecError(
                    f"invalid sort direction {components[1]!r} (use asc or desc)"
                )
            descending = direction == "desc"
        else:
            descending = False
        keys.append(SortKey(name, descending))
    return tuple(keys)


def format_sort_spec(spec: SortSpec) -> str:
    """Format a sort specification for diagnostics."""
    if not spec:
        return "walk order"
    return ", ".join(str(key) for key in spec)


def normalize_sort_value(raw: TagValue) -> SortValue | None:
    """Normalize a tag value into a comparable sort value.

    Multi-valued tags use their first non-empty value. Numeric-looking strings
    become numbers, other text is case-folded, and missing or empty values are
    represented by ``None``.
    """
    if isinstance(raw, list):
        for item in raw:
            value = normalize_sort_value(item)
            if value is not None:
                return value
        return None
    if raw is None:
        return None
    if isinstance(raw, bool):
        return int(raw)
    if isinstance(raw, int | float):
        return raw
    text = str(raw).strip()
    if not text:
        return None
    if INT_RE.match(text):
        return int(text)
    if FLOAT_RE.match(text):
        return float(text)
    return text.casefold()


def compare_sort_values(first: SortValues, second: SortValues, spec: SortSpec) -> int:
    """Compare two entries according to ``spec``.

    Missing values sort after present values for that key, but lower-priority
    keys are still compared. The caller is responsible for the final stable
    tie-breaker.
    """
    for key, left, right in zip(spec, first, second, strict=True):
        if left is None and right is None:
            continue
        if left is None:
            return 1
        if right is None:
            return -1
        result = _compare_present(left, right)
        if result:
            return -result if key.descending else result
    return 0


def _compare_present(left: SortValue, right: SortValue) -> int:
    if isinstance(left, str):
        if not isinstance(right, str):
            return 1
        return (left > right) - (left < right)
    if isinstance(right, str):
        return -1
    return (left > right) - (left < right)
