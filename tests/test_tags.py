from collections.abc import Callable
from io import StringIO
from pathlib import Path

import pytest
from pytest import approx
from tinytag import TinyTagException

from genplis.output import Output, Palette, Theme
from genplis.tags import (
    AUDIO_PROPERTY_TAGS,
    TagDiagnostic,
    TagDiagnosticKind,
    exceeds_tag_size,
    format_tag_diagnostic,
    get_audio_property_tags,
    get_tag_size,
    get_tags,
    parse_tags,
)
from genplis.types import Tags, Verbosity


class _FakeTinyTag:
    def __init__(self, raw_tags: Tags) -> None:
        self._raw_tags = raw_tags

    def as_dict(self) -> Tags:
        return self._raw_tags


def _patch_tinytag(monkeypatch: pytest.MonkeyPatch, raw_tags: Tags) -> None:
    monkeypatch.setattr("genplis.tags.TinyTag.is_supported", lambda _path: True)
    monkeypatch.setattr(
        "genplis.tags.TinyTag.get",
        lambda _path: _FakeTinyTag(raw_tags),
    )


def test_get_tags_mp3(file_mp3: Path) -> None:
    tags = get_tags(file_mp3)
    assert tags == {
        "artist": ["Test Artist"],
        "bitrate": approx(127.99768145161289),
        "channels": 2,
        "duration": approx(3.239183673469388),
        "encoder_settings": ["Lavf57.83.100"],
        "filename": str(file_mp3),
        "filesize": 53235,
        "genre": ["Synthwave; Retrowave; Electronic"],
        "is_lossless": False,
        "mime_type": "audio/mpeg",
        "samplerate": 44100,
        "title": ["Test"],
    }


def test_get_tags_ogg(file_ogg: Path) -> None:
    tags = get_tags(file_ogg)
    assert tags == {
        "artist": ["Test Artist"],
        "bitrate": 112.0,
        "channels": 2,
        "duration": 1.0,
        "encoder": [
            "Lavc58.35.100 libvorbis",
        ],
        "filename": str(file_ogg),
        "filesize": 5241,
        "genre": ["Synthwave", "Retrowave", "Electronic"],
        "is_lossless": False,
        "mime_type": 'audio/ogg; codecs="vorbis"',
        "samplerate": 44100,
        "title": ["Test"],
    }


def test_parse_tags_returns_messages_without_printing(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    raw_tags: Tags = {
        "artist": ["Test Artist"],
        "long": ["x" * 10],
        "title": ["Test"],
    }
    _patch_tinytag(monkeypatch, raw_tags)

    tags, diagnostics = parse_tags(
        Path("song.mp3"),
        max_size=5,
        ignore=frozenset({"artist"}),
    )

    assert tags == {"title": ["Test"]}
    assert diagnostics == (
        TagDiagnostic(
            TagDiagnosticKind.REMOVE,
            Path("song.mp3"),
            "it is configured to be ignored",
            tag="artist",
        ),
        TagDiagnostic(
            TagDiagnosticKind.REMOVE,
            Path("song.mp3"),
            "it's larger than 5 UTF-8 bytes",
            tag="long",
        ),
    )
    assert capsys.readouterr().out == ""


def test_parse_tags_reports_unsupported_file(tmp_path: Path) -> None:
    unsupported = tmp_path / "notes.txt"
    unsupported.write_text("not music\n", encoding="utf-8")

    tags, diagnostics = parse_tags(unsupported)

    assert tags is None
    assert diagnostics == (
        TagDiagnostic(
            TagDiagnosticKind.SKIP,
            unsupported,
            "not supported by tinytag",
        ),
    )


def test_format_tag_diagnostic_uses_palette(
    strip_ansi: Callable[[str], str],
) -> None:
    palette = Palette(theme=Theme.DARK, enabled=True)
    skipped = TagDiagnostic(
        TagDiagnosticKind.SKIP,
        Path("song.mp3"),
        "not supported by tinytag",
    )
    removed = TagDiagnostic(
        TagDiagnosticKind.REMOVE,
        Path("song.mp3"),
        "it is configured to be ignored",
        tag="artist",
    )

    skip_output = format_tag_diagnostic(skipped, palette)
    remove_output = format_tag_diagnostic(removed, palette)

    assert "Skipping song.mp3: not supported by tinytag" == strip_ansi(skip_output)
    assert "Removing tag artist because it is configured to be ignored" == strip_ansi(
        remove_output
    )
    assert "\x1b[38;5;117mSkipping\x1b[0m" in skip_output
    assert "\x1b[38;5;214mRemoving tag\x1b[0m" in remove_output
    assert "\x1b[38;5;51martist\x1b[0m" in remove_output


def test_get_tags_colors_verbose_diagnostics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_tinytag(monkeypatch, {"artist": ["Artist"], "title": ["Title"]})
    stream = StringIO()

    get_tags(
        Path("song.mp3"),
        Verbosity.VERBOSE,
        ignore=frozenset({"artist"}),
        output=Output(
            stream=stream,
            palette=Palette(theme=Theme.DARK, enabled=True),
        ),
    )

    output = stream.getvalue()
    assert "\x1b[38;5;214mRemoving tag\x1b[0m" in output
    assert "\x1b[38;5;51martist\x1b[0m" in output


def test_get_audio_property_tags() -> None:
    tags = {
        "filename": "/music/test.mp3",
        "duration": 1.5,
        "is_lossless": False,
        "title": ["Test"],
    }

    assert get_audio_property_tags(tags) == {
        "*filename": "/music/test.mp3",
        "*duration": 1.5,
        "*is_lossless": False,
    }


def test_get_tag_size() -> None:
    assert get_tag_size(None) == 4
    assert get_tag_size(2) == 1
    assert get_tag_size(128.0) == 5
    assert get_tag_size("") == 0
    assert get_tag_size("DANCE WITH THE DEAD") == 19
    assert get_tag_size(["Synthwave", "Retrowave", "Electronic"]) == 28


def test_get_tag_size_counts_utf8_bytes() -> None:
    assert get_tag_size("\u03b1") == 2
    assert get_tag_size("\u4e00") == 3
    assert get_tag_size("\U0001f600") == 4
    assert get_tag_size(["\u03b1", "abc"]) == 5


def test_exceeds_tag_size() -> None:
    assert exceeds_tag_size("", 0) is False
    assert exceeds_tag_size("abc", 3) is False
    assert exceeds_tag_size("abcd", 3) is True
    assert exceeds_tag_size("\u03b1", 1) is True
    assert exceeds_tag_size(["\u03b1", "abc"], 5) is False
    assert exceeds_tag_size(["\u03b1", "abc"], 4) is True
    assert exceeds_tag_size(123, 3) is False


def test_get_tags_invalid_file(tmp_path: Path) -> None:
    invalid_file = tmp_path / "invalid.m4a"
    invalid_file.write_bytes(b"\x1aE\xdf\xa3")

    assert get_tags(invalid_file) is None


def test_get_tags_respects_ignore_list(file_mp3: Path) -> None:
    tags = get_tags(file_mp3, ignore=frozenset({"artist", "genre"}))

    assert tags is not None
    assert "artist" not in tags
    assert "genre" not in tags
    assert "title" in tags


def test_get_tags_respects_max_size(monkeypatch: pytest.MonkeyPatch) -> None:
    raw_tags: Tags = {
        "exact": ["a" * 6],
        "over": ["a" * 7],
        "multi": ["abc", "def"],
    }
    _patch_tinytag(monkeypatch, raw_tags)

    tags = get_tags(Path("song.mp3"), max_size=6)

    assert tags == {
        "exact": ["a" * 6],
        "multi": ["abc", "def"],
    }


def test_get_tags_max_size_counts_utf8_bytes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw_tags: Tags = {
        "fits": ["\u03b1" * 3],
        "too_big": ["\u03b1" * 4],
    }
    _patch_tinytag(monkeypatch, raw_tags)

    tags = get_tags(Path("song.mp3"), max_size=6)

    assert tags == {"fits": ["\u03b1" * 3]}


def test_get_tags_max_size_zero_disables_filtering(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw_tags: Tags = {"title": ["x" * 2000]}
    _patch_tinytag(monkeypatch, raw_tags)

    assert get_tags(Path("song.mp3"), max_size=0) == raw_tags


def test_get_tags_size_limit_ignores_audio_properties(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    long_path = "/music/" + "x" * 2000 + ".mp3"
    raw_tags: Tags = {
        "filename": long_path,
        "lyrics": ["y" * 2000],
    }
    _patch_tinytag(monkeypatch, raw_tags)

    assert get_tags(Path("song.mp3"), max_size=100) == {"filename": long_path}
    assert (
        get_tags(
            Path("song.mp3"),
            max_size=100,
            ignore=frozenset({"filename"}),
        )
        == {}
    )


def test_get_tags_ignore_is_case_insensitive(file_mp3: Path) -> None:
    tags = get_tags(file_mp3, ignore=frozenset({"ARTIST"}))

    assert tags is not None
    assert "artist" not in tags


def test_get_tags_verbose_explains_ignored_and_oversized_tags(
    file_mp3: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    tags = get_tags(
        file_mp3,
        Verbosity.VERBOSE,
        max_size=1,
        ignore=frozenset({"artist"}),
    )

    output = capsys.readouterr().out
    assert tags is not None
    assert set(tags) <= AUDIO_PROPERTY_TAGS
    assert "title" not in tags
    assert "Removing tag artist because it is configured to be ignored" in output
    assert "because it's larger than 1 UTF-8 bytes" in output


def test_get_tags_verbose_explains_unsupported_and_unparseable_files(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    unsupported = tmp_path / "notes.txt"
    unsupported.write_text("not music\n", encoding="utf-8")

    assert get_tags(unsupported, Verbosity.VERBOSE) is None
    assert (
        f"Skipping {unsupported}: not supported by tinytag" in capsys.readouterr().out
    )

    broken = tmp_path / "broken.mp3"
    broken.write_bytes(b"")

    def fail_get(*_args: object, **_kwargs: object) -> None:
        raise TinyTagException("boom")

    monkeypatch.setattr("genplis.tags.TinyTag.get", fail_get)

    assert get_tags(broken, Verbosity.VERBOSE) is None
    assert f"Skipping {broken}: boom" in capsys.readouterr().out


def test_get_tags_skips_unreadable_file(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    unreadable = tmp_path / "unreadable.mp3"
    unreadable.write_bytes(b"")
    monkeypatch.setattr("genplis.tags.TinyTag.is_supported", lambda _path: True)

    def fail_get(*_args: object, **_kwargs: object) -> None:
        raise PermissionError("permission denied")

    monkeypatch.setattr("genplis.tags.TinyTag.get", fail_get)

    assert get_tags(unreadable) is None
    assert get_tags(unreadable, Verbosity.VERBOSE) is None
    assert f"Skipping {unreadable}: permission denied" in capsys.readouterr().out
