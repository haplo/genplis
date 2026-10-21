from functools import cmp_to_key

import pytest

from genplis.sorting import (
    SortKey,
    SortSpecError,
    compare_sort_values,
    format_sort_spec,
    normalize_sort_value,
    parse_sort_spec,
)


def test_parse_sort_spec_defaults_to_ascending() -> None:
    assert parse_sort_spec("artist, album desc") == (
        SortKey("artist"),
        SortKey("album", descending=True),
    )


def test_parse_sort_spec_is_case_insensitive() -> None:
    assert parse_sort_spec("ARTIST DESC, Album ASC") == (
        SortKey("artist", descending=True),
        SortKey("album"),
    )


def test_parse_sort_spec_accepts_empty_value() -> None:
    assert parse_sort_spec("") == ()
    assert parse_sort_spec("   \n  ") == ()


@pytest.mark.parametrize(
    ("spec", "message"),
    [
        ("artist,", "sort key must not be empty"),
        ("artist,,album", "sort key must not be empty"),
        ("artist sideways", "invalid sort direction"),
        ("artist asc extra", "invalid sort key"),
    ],
)
def test_parse_sort_spec_rejects_invalid_input(spec: str, message: str) -> None:
    with pytest.raises(SortSpecError, match=message):
        parse_sort_spec(spec)


def test_format_sort_spec() -> None:
    assert format_sort_spec(()) == "walk order"
    assert format_sort_spec(parse_sort_spec("artist, album desc")) == (
        "artist, album desc"
    )


def test_parse_sort_spec_accepts_random_last() -> None:
    assert parse_sort_spec("random") == (SortKey("random"),)
    assert parse_sort_spec("artist, random 42") == (
        SortKey("artist"),
        SortKey("random", seed=42),
    )
    assert format_sort_spec(parse_sort_spec("artist, random 42")) == (
        "artist, random 42"
    )


@pytest.mark.parametrize(
    "spec",
    [
        "random desc",
        "random asc",
        "random 1.5",
        "random -1",
        "random, artist",
        "random, random",
        "random, artist, random",
    ],
)
def test_parse_sort_spec_rejects_invalid_random_keys(spec: str) -> None:
    with pytest.raises(SortSpecError):
        parse_sort_spec(spec)


def test_normalize_sort_value() -> None:
    assert normalize_sort_value(None) is None
    assert normalize_sort_value("") is None
    assert normalize_sort_value("  ") is None
    assert normalize_sort_value([]) is None
    assert normalize_sort_value(["", " Value "]) == "value"
    assert normalize_sort_value("007") == 7
    assert normalize_sort_value("3.5") == 3.5
    assert normalize_sort_value(True) == 1
    assert normalize_sort_value("Mixed Case") == "mixed case"


def test_missing_values_are_last_per_key() -> None:
    spec = parse_sort_spec("artist, album, disc, track, title")
    entries = {
        "song-1": ("ART", "ALB", "1", "1", "TIT"),
        "song-2": ("ART", "DLT", None, None, "PLK"),
        "song-3": ("ART", "BUD", None, None, "DSA"),
        "song-4": ("BDC", "YDF", "1", "1", "JAD"),
    }
    values = {
        name: tuple(normalize_sort_value(value) for value in raw)
        for name, raw in entries.items()
    }

    ordered = sorted(
        values,
        key=cmp_to_key(
            lambda first, second: compare_sort_values(
                values[first], values[second], spec
            )
        ),
    )

    assert ordered == ["song-1", "song-3", "song-2", "song-4"]


def test_lower_priority_keys_still_compare_after_missing_value() -> None:
    spec = parse_sort_spec("artist, album, title")
    first = ("ART", None, None)
    second = ("ART", None, "TITLE")

    assert compare_sort_values(first, second, spec) > 0
    assert compare_sort_values(second, first, spec) < 0


def test_descending_keeps_missing_values_last() -> None:
    spec = parse_sort_spec("rating desc")
    values = [3, 5, None, 4]
    ordered = sorted(
        values,
        key=cmp_to_key(
            lambda first, second: compare_sort_values((first,), (second,), spec)
        ),
    )

    assert ordered == [5, 4, 3, None]


def test_mixed_numeric_and_text_values_have_a_stable_order() -> None:
    spec = parse_sort_spec("value")

    assert compare_sort_values((10,), ("alpha",), spec) < 0
    assert compare_sort_values(("alpha",), (10,), spec) > 0


def test_text_sort_is_case_insensitive() -> None:
    spec = parse_sort_spec("title")
    values = [("beta",), ("Alpha",), ("alpha",)]

    ordered = sorted(
        values,
        key=cmp_to_key(
            lambda first, second: compare_sort_values(
                tuple(normalize_sort_value(v) for v in first),
                tuple(normalize_sort_value(v) for v in second),
                spec,
            )
        ),
    )

    assert ordered == [("Alpha",), ("alpha",), ("beta",)]
