"""Cached evaluation must preserve the ordinary M3UG evaluator's semantics."""

import sqlite3
from collections.abc import Callable, ItemsView, Iterator, Mapping
from pathlib import Path

import pytest

from genplis import db
from genplis.core import Args, _sort_values, process_directory
from genplis.diagnostics import trace_file
from genplis.m3ug import (
    EqualRuleNode,
    EvaluationTags,
    NameNode,
    PredicateCache,
    ValueNode,
    parse_m3ug,
)
from genplis.sorting import parse_sort_spec
from genplis.types import Tags, TagValue


class CountingValues(list[str]):
    def __init__(self, values: list[str]) -> None:
        super().__init__(values)
        self.normalizations = 0

    def __len__(self) -> int:
        self.normalizations += 1
        return super().__len__()


class CountingText(str):
    folds = 0

    def casefold(self) -> str:
        self.folds += 1
        return super().casefold()


class CountingTags(Mapping[str, TagValue]):
    def __init__(self, tags: dict[str, TagValue]) -> None:
        self.tags = tags
        self.scans = 0

    def __getitem__(self, key: str) -> TagValue:
        return self.tags[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self.tags)

    def __len__(self) -> int:
        return len(self.tags)

    def items(self) -> ItemsView[str, TagValue]:
        self.scans += 1
        return self.tags.items()


def test_rules_reuse_a_songs_tag_lookup_and_normalization() -> None:
    genre = CountingValues(["Heavy Metal"])
    raw = CountingTags({"Genre": genre})
    tags = EvaluationTags(raw)

    for source in ("genre ~ Metal", "GENRE ^ Heavy", "genre != Rock"):
        expression = parse_m3ug(source).expression
        assert expression is not None
        assert expression.apply(tags)

    assert raw.scans == 1
    assert genre.normalizations == 1
    assert tags["Genre"] is genre


@pytest.mark.parametrize(
    "raw",
    [
        {},
        {"genre": None},
        {"genre": []},
        {"genre": ["Heavy Metal"]},
        {"Genre": ["Rock", "Metal"]},
        {"GENRE": "Rock", "Genre": "Metal"},
        {"Genre": "Rock", "genre": "Metal"},
        {"artist": "Straße", "genre": "ßx"},
        {"genre": False, "rating": True},
        {"rating": 0, "fmps_rating": ["1.0"]},
        {"RATING": None, "fmps_rating": ["1.0"]},
        {"FMPS_RATING": ["0.8"]},
        {"fmps_rating": ["0.8", "0.9"]},
        {"fmps_rating": ["invalid"]},
        {"track": ["007"], "duration": 300.0},
    ],
)
def test_cached_song_evaluation_matches_plain_tags(raw: Tags) -> None:
    tags = EvaluationTags(raw)
    for source in (
        'genre = [Metal | Rock | ""]',
        "genre != Metal",
        "genre ~ metal",
        "genre ^ ß",
        "genre $ x",
        "genre % ^(Metal|Rock)$",
        "@CASE genre ~ Metal",
        "genre = true",
        "artist = STRASSE",
        "rating >= 4",
        "rating <= 4",
        "rating = 0",
        "track = 7",
        "duration > 3m",
        "@NOT genre = Metal\n@OR rating >= 4",
        "[genre | style] = [Metal | Rock]\nrating >= 3",
    ):
        expression = parse_m3ug(source).expression
        assert expression is not None
        assert expression.apply(tags) == expression.apply(raw), source
    assert dict(tags) == raw


def test_missing_tags_only_build_one_case_insensitive_index() -> None:
    raw = CountingTags({"Artist": "Example"})
    tags = EvaluationTags(raw)

    for name in ("style", "STYLE", "comment", "rating", "RATING"):
        assert NameNode(name).find(tags) == (name.lower(), None)

    assert raw.scans == 1


def test_calculated_rating_is_reused_by_rules_and_ordering() -> None:
    alias = CountingValues(["0.8"])
    tags = EvaluationTags({"FMPS_RATING": alias})
    expression = parse_m3ug("rating >= 4\nrating <= 4").expression
    assert expression is not None

    assert expression.apply(tags)
    assert _sort_values(Path("song.flac"), tags, parse_sort_spec("rating desc")) == (
        4.0,
    )
    assert NameNode("RATING").find(tags) == ("rating", 4.0)
    assert alias.normalizations == 1


def test_song_contexts_do_not_leak_values_between_songs() -> None:
    expression = parse_m3ug("rating >= 4").expression
    assert expression is not None

    assert expression.apply(EvaluationTags({"fmps_rating": ["0.8"]}))
    assert not expression.apply(EvaluationTags({"rating": 0}))
    assert not expression.apply(EvaluationTags({}))


@pytest.mark.parametrize("memoize", [False, True])
def test_cached_rules_still_short_circuit_before_invalid_rating(
    caplog: pytest.LogCaptureFixture,
    memoize: bool,
) -> None:
    expression = parse_m3ug("genre = Metal\nrating >= 4").expression
    assert expression is not None

    cache = PredicateCache([expression]) if memoize else None
    for _ in range(3):
        assert not expression.apply(
            EvaluationTags({"genre": "Rock", "fmps_rating": ["invalid"]}, cache)
        )
    assert not caplog.messages


def test_directory_reuses_song_values_between_playlists(
    tmp_path: Path,
    genplis_db: sqlite3.Connection,
    make_args: Callable[..., Args],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tmp_path = tmp_path / "music"
    tmp_path.mkdir()
    (tmp_path / "song.mp3").touch()
    genre = CountingValues(["Heavy Metal"])
    monkeypatch.setattr(
        "genplis.core.get_tags", lambda *args, **kwargs: {"Genre": genre}
    )
    filters = {
        tmp_path / "first.m3ug": parse_m3ug("genre ~ Metal"),
        tmp_path / "second.m3ug": parse_m3ug("GENRE ^ Heavy"),
    }

    process_directory(
        genplis_db,
        genplis_db.cursor(),
        tmp_path,
        make_args(str(tmp_path), include_source=False, extended_m3u=False),
        filters=filters,
    )

    assert (tmp_path / "first.m3u").read_text() == "song.mp3\n"
    assert (tmp_path / "second.m3u").read_text() == "song.mp3\n"
    assert genre.normalizations == 1


def test_predicates_share_results_between_songs_and_equivalent_rules() -> None:
    expressions = [parse_m3ug("genre = metal").expression for _ in range(2)]
    cache = PredicateCache(expressions)
    genre = CountingText("Metal")

    for expression in expressions:
        assert expression is not None
        for _ in range(3):
            assert expression.apply(EvaluationTags({"genre": genre}, cache))

    assert genre.folds == 1


@pytest.mark.parametrize("max_entries,max_per_predicate", [(1, 10), (10, 1)])
def test_predicate_cache_stops_admitting_values_at_its_limits(
    max_entries: int, max_per_predicate: int
) -> None:
    expression = parse_m3ug("genre = metal").expression
    assert expression is not None
    cache = PredicateCache(
        [expression], max_entries=max_entries, max_per_predicate=max_per_predicate
    )
    metal = CountingText("Metal")
    rock = CountingText("Rock")

    for genre in (metal, rock, metal, rock):
        assert expression.apply(EvaluationTags({"genre": genre}, cache)) == (
            genre == "Metal"
        )

    assert metal.folds == 1
    assert rock.folds == 2


def test_predicate_cache_does_not_retain_oversized_values() -> None:
    expression = parse_m3ug("genre ~ metal").expression
    assert expression is not None
    cache = PredicateCache([expression])
    genre = CountingText("x" * 1024)

    for _ in range(3):
        assert not expression.apply(EvaluationTags({"genre": genre}, cache))

    assert genre.folds == 3


@pytest.mark.parametrize("many_items", [False, True])
def test_predicate_cache_limits_multivalued_key_sizes(many_items: bool) -> None:
    expression = parse_m3ug("genre ~ metal").expression
    assert expression is not None
    cache = PredicateCache([expression])
    first = CountingText("Metal" if many_items else "Metal" + "x" * 256)
    values = [first, *([""] * 256 if many_items else ["Rock"])]

    for _ in range(3):
        assert expression.apply(EvaluationTags({"genre": values}, cache))

    assert first.folds == 3


@pytest.mark.parametrize("jobs", [1, 2])
def test_directory_shares_comparisons_on_each_warm_cache_run(
    tmp_path: Path,
    genplis_db: sqlite3.Connection,
    make_args: Callable[..., Args],
    monkeypatch: pytest.MonkeyPatch,
    jobs: int,
) -> None:
    music = tmp_path / "music"
    music.mkdir()
    cursor = genplis_db.cursor()
    for name in ("first.mp3", "second.mp3"):
        song = music / name
        song.touch()
        db.cache_tags_for_file(cursor, song, {"genre": "Metal"})
    genplis_db.commit()

    values: list[CountingText] = []
    get_cached_tags = db.get_cached_tags

    def read_cached_tags(cursor: sqlite3.Cursor, path: Path) -> Tags:
        tags = get_cached_tags(cursor, path)
        genre = CountingText(str(tags["genre"]))
        values.append(genre)
        tags["genre"] = genre
        return tags

    def unexpected_parse(*args: object, **kwargs: object) -> Tags | None:
        raise AssertionError("cache miss")

    monkeypatch.setattr(db, "get_cached_tags", read_cached_tags)
    monkeypatch.setattr("genplis.core.get_tags", unexpected_parse)
    filters = {
        music / f"filter-{i}.m3ug": parse_m3ug("genre = metal") for i in range(2)
    }

    for _ in range(2):
        values.clear()
        process_directory(
            genplis_db,
            cursor,
            music,
            make_args(str(music), jobs=jobs),
            filters=filters,
            dry_run=True,
        )
        assert len(values) == 2
        assert sum(value.folds for value in values) == 1


def test_memoized_predicates_preserve_types_lists_operators_and_traces() -> None:
    filters = [
        parse_m3ug(source)
        for source in (
            "genre = true",
            "genre = 1",
            'genre = "1"',
            "genre = metal",
            "@CASE genre = metal",
            "genre != metal",
            "genre ~ metal",
            "@CASE genre ~ Metal",
            "genre ^ ß",
            "genre $ x",
            "genre % ^(Metal|Rock)$",
            "@CASE genre % ^Metal$",
            "genre < 2",
            "genre <= 2",
            "genre > 2",
            "genre >= 2",
            "@NOT genre = Metal\n@OR rating >= 4",
            "[genre | style] = [Metal | Rock]\nrating >= 3",
        )
    ]
    cache = PredicateCache(parsed.expression for parsed in filters)
    inputs: list[Tags] = [
        {},
        {"genre": None},
        {"genre": True},
        {"genre": False},
        {"genre": 1},
        {"genre": 1.0},
        {"genre": "1"},
        {"genre": "01"},
        {"genre": "1.0"},
        {"genre": "Metal"},
        {"genre": "metal"},
        {"genre": "ßx"},
        {"genre": []},
        {"genre": ["Metal"]},
        {"genre": ["Metal", "Rock"]},
        {"genre": ["Rock", "Metal"]},
        {"Genre": "Metal", "style": "Rock", "fmps_rating": ["0.8"]},
        {"genre": float("nan")},
        {"genre": float("inf")},
        {"genre": 10**1000},
    ]

    for _ in range(3):
        for raw in inputs:
            tags = EvaluationTags(raw, cache)
            for parsed in filters:
                assert parsed.expression is not None
                expected = parsed.expression.apply(raw)
                assert parsed.expression.apply(tags) == expected
                assert trace_file(parsed, raw).passed == expected


def test_memoization_does_not_suppress_warnings_from_distinct_sources(
    caplog: pytest.LogCaptureFixture,
) -> None:
    expressions = [
        parse_m3ug("[genre | style] ~ [Metal | Rock]", filename).expression
        for filename in ("first.m3ug", "second.m3ug")
    ]
    cache = PredicateCache(expressions)

    for _ in range(3):
        tags = EvaluationTags({"genre": True, "style": False}, cache)
        for expression in expressions:
            assert expression is not None
            assert not expression.apply(tags)

    assert (
        caplog.messages
        == ["text operator '~' applied to boolean tag 'genre'; use = true or = false"]
        * 2
    )


def test_global_cache_budget_is_shared_between_distinct_predicates() -> None:
    expression = parse_m3ug("genre = metal\n@OR genre = rock").expression
    assert expression is not None
    cache = PredicateCache([expression], max_entries=2, max_per_predicate=10)
    jazz = CountingText("Jazz")
    pop = CountingText("Pop")

    for genre in (jazz, pop, jazz, pop):
        assert not expression.apply(EvaluationTags({"genre": genre}, cache))

    assert jazz.folds == 2
    assert pop.folds == 4


@pytest.mark.parametrize("limits", [{"max_entries": 0}, {"max_per_predicate": 0}])
def test_zero_budget_disables_memoization(limits: dict[str, int]) -> None:
    expression = parse_m3ug("genre = metal").expression
    assert expression is not None
    cache = PredicateCache([expression], **limits)
    genre = CountingText("Metal")

    for _ in range(2):
        assert expression.apply(EvaluationTags({"genre": genre}, cache))

    assert genre.folds == 2


def test_custom_rule_checks_are_not_memoized() -> None:
    class AlternatingRule(EqualRuleNode):
        calls = 0

        def check(self, tag_value: TagValue) -> bool:
            self.calls += 1
            return self.calls % 2 == 1

    rule = AlternatingRule(NameNode("genre"), ValueNode("Metal"))
    cache = PredicateCache([rule])

    assert rule.apply(EvaluationTags({"genre": "Metal"}, cache))
    assert not rule.apply(EvaluationTags({"genre": "Metal"}, cache))


def test_custom_value_normalization_is_not_replaced_by_the_song_cache() -> None:
    class MetalValue(ValueNode):
        def normalize(self, raw: TagValue) -> TagValue:
            return "Metal"

    rule = EqualRuleNode(NameNode("genre"), MetalValue("Metal"))
    cache = PredicateCache([rule])

    assert rule.apply({"genre": "Rock"})
    assert rule.apply(EvaluationTags({"genre": "Rock"}, cache))


@pytest.mark.parametrize("limits", [{"max_entries": -1}, {"max_per_predicate": -1}])
def test_negative_cache_limits_are_rejected(limits: dict[str, int]) -> None:
    with pytest.raises(ValueError, match="non-negative"):
        PredicateCache([], **limits)
