import argparse
import shutil
import sqlite3
from collections.abc import Callable
from pathlib import Path

import pytest

from genplis.core import process_directory, process_file
from genplis.exceptions import GenplisError
from genplis.m3ug import (
    ContainsRuleNode,
    GreaterOrEqualRuleNode,
    NameNode,
    ValueNode,
)


def test_process_audio_file(
    genplis_db: sqlite3.Connection,
    make_args: Callable[..., argparse.Namespace],
    file_mp3: Path,
) -> None:
    args = make_args(str(file_mp3))
    tags, filters = process_file(genplis_db, genplis_db.cursor(), file_mp3, args)
    assert tags == {
        "artist": ["Test Artist"],
        "bitrate": 127.488,
        "channels": 2,
        "duration": 3.2653061224489797,
        "encoder_settings": ["Lavf57.83.100"],
        "filename": "/home/fidel/Code/genplis/tests/files/test.mp3",
        "filesize": 53235,
        "genre": ["Synthwave; Retrowave; Electronic"],
        "samplerate": 44100,
        "title": ["Test"],
    }
    assert filters == []


def test_process_m3ug_file(
    genplis_db: sqlite3.Connection,
    make_args: Callable[..., argparse.Namespace],
    file_m3ug: Path,
) -> None:
    args = make_args(str(file_m3ug))
    tags, filters = process_file(genplis_db, genplis_db.cursor(), file_m3ug, args)
    assert tags == {}
    assert filters == [
        GreaterOrEqualRuleNode(NameNode("rating"), ValueNode(3)),
        ContainsRuleNode(NameNode("genre"), ValueNode("Metal")),
    ]


def test_process_file_error_if_dir(
    genplis_db: sqlite3.Connection,
    make_args: Callable[..., argparse.Namespace],
) -> None:
    path = (Path(__file__).parent / "files").absolute()
    args = make_args(str(path))
    with pytest.raises(GenplisError):
        process_file(genplis_db, genplis_db.cursor(), path, args)


def test_process_dir(
    genplis_db: sqlite3.Connection,
    make_args: Callable[..., argparse.Namespace],
    file_mp3: Path,
    file_ogg: Path,
    file_m3ug: Path,
    tmp_path: Path,
) -> None:
    # Work on copies so that generated playlists don't end up in tests/files
    for source in (file_mp3, file_ogg, file_m3ug):
        shutil.copy2(source, tmp_path / source.name)

    args = make_args(str(tmp_path))
    all_tags, all_filters = process_directory(
        genplis_db, genplis_db.cursor(), tmp_path, args
    )

    assert set(all_tags) == {tmp_path / file_mp3.name, tmp_path / file_ogg.name}
    assert set(all_filters) == {tmp_path / file_m3ug.name}
    assert all(isinstance(tags, dict) for tags in all_tags.values())
    assert len(all_filters[tmp_path / file_m3ug.name]) == 2
