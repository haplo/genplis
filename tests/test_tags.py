from pathlib import Path

import pytest
from pytest import approx
from tinytag import TinyTagException

from genplis.tags import get_audio_property_tags, get_tag_size, get_tags


def test_get_tags_mp3(file_mp3: Path) -> None:
    tags = get_tags(file_mp3)
    assert tags == {
        "artist": ["Test Artist"],
        "bitrate": approx(127.99768145161289),
        "channels": 2,
        "duration": approx(3.239183673469388),
        "encoder_settings": ["Lavf57.83.100"],
        "filename": "/home/fidel/Code/genplis/tests/files/test.mp3",
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
    assert get_tag_size(None) == 16
    assert get_tag_size(2) == 28
    assert get_tag_size(128.0) == 24
    assert get_tag_size("") == 41
    assert get_tag_size("DANCE WITH THE DEAD") == 60
    assert get_tag_size(["Synthwave", "Retrowave", "Electronic"]) == 151


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


def test_get_tags_respects_max_size(file_mp3: Path) -> None:
    tags = get_tags(file_mp3, max_size=0)

    assert tags == {}


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
        verbose=True,
        max_size=0,
        ignore=frozenset({"artist"}),
    )

    output = capsys.readouterr().out
    assert tags == {}
    assert "Removing tag artist because it is configured to be ignored" in output
    assert "because it's larger than 0 bytes" in output


def test_get_tags_verbose_explains_unsupported_and_unparseable_files(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    unsupported = tmp_path / "notes.txt"
    unsupported.write_text("not music\n", encoding="utf-8")

    assert get_tags(unsupported, verbose=True) is None
    assert (
        f"Skipping {unsupported}: not supported by tinytag" in capsys.readouterr().out
    )

    broken = tmp_path / "broken.mp3"
    broken.write_bytes(b"")

    def fail_get(*_args: object, **_kwargs: object) -> None:
        raise TinyTagException("boom")

    monkeypatch.setattr("genplis.tags.TinyTag.get", fail_get)

    assert get_tags(broken, verbose=True) is None
    assert f"Skipping {broken}: boom" in capsys.readouterr().out
