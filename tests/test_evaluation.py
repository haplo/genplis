"""Cached evaluation must preserve the ordinary M3UG evaluator's semantics."""

import sqlite3
from collections.abc import Callable, ItemsView, Iterator, Mapping
from pathlib import Path

import pytest

from genplis.core import Args, _sort_values, process_directory
from genplis.m3ug import EvaluationTags, NameNode, parse_m3ug
from genplis.sorting import parse_sort_spec
from genplis.types import Tags, TagValue


class CountingValues(list[str]):
    def __init__(self, values: list[str]) -> None:
        super().__init__(values)
        self.normalizations = 0

    def __len__(self) -> int:
        self.normalizations += 1
        return super().__len__()


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


def test_cached_rules_still_short_circuit_before_invalid_rating(
    caplog: pytest.LogCaptureFixture,
) -> None:
    expression = parse_m3ug("genre = Metal\nrating >= 4").expression
    assert expression is not None

    assert not expression.apply(
        EvaluationTags({"genre": "Rock", "fmps_rating": ["invalid"]})
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
