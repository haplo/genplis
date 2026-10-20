import json
import os
import re
import shutil
import sqlite3
import sys
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

import pytest
from pytest import approx

from genplis.config import (
    CollectionConfig,
    Config,
    DatabaseConfig,
    GeneralConfig,
    OutputConfig,
    TagsConfig,
)
from genplis.core import (
    Args,
    clean_database,
    format_size,
    get_calculated_tags,
    main,
    process_directory,
    process_file,
    process_path,
    resolve_args,
    setup_argparse,
)
from genplis.db import (
    CacheStatus,
    cache_tags_for_file,
    create_files_table,
    get_cached_tags,
    setup_database_connection,
)
from genplis.exceptions import GenplisConfigError, GenplisError
from genplis.m3ug import (
    ContainsRuleNode,
    EqualRuleNode,
    GreaterOrEqualRuleNode,
    NameNode,
    ValueNode,
)
from genplis.types import Tags, Verbosity


def test_process_audio_file(
    genplis_db: sqlite3.Connection,
    make_args: Callable[..., Args],
    file_mp3: Path,
) -> None:
    args = make_args(str(file_mp3))
    tags, filters, cache_status = process_file(
        genplis_db, genplis_db.cursor(), file_mp3, args
    )
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
    assert filters == []
    assert cache_status is CacheStatus.MISS


def test_process_m3ug_file(
    genplis_db: sqlite3.Connection,
    make_args: Callable[..., Args],
    file_m3ug: Path,
) -> None:
    args = make_args(str(file_m3ug))
    tags, filters, cache_status = process_file(
        genplis_db, genplis_db.cursor(), file_m3ug, args
    )
    assert tags is None
    assert filters == [
        GreaterOrEqualRuleNode(NameNode("rating"), ValueNode(3)),
        ContainsRuleNode(NameNode("genre"), ValueNode("Metal")),
    ]
    assert cache_status is CacheStatus.MISS


def test_process_path_reports_cache_status(
    genplis_db: sqlite3.Connection,
    make_args: Callable[..., Args],
    file_mp3: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Each run must report the cache state found before parsing the file.

    Regression test: the cache was checked after process_file had already
    refreshed it, so it always reported "valid".
    """
    song = tmp_path / file_mp3.name
    shutil.copy2(file_mp3, song)
    args = make_args(str(song))
    cursor = genplis_db.cursor()

    # First run: nothing cached yet, tags are parsed.
    process_path(genplis_db, cursor, args)
    assert "Cache status: not present" in capsys.readouterr().out

    # Second run: tags come from the cache.
    process_path(genplis_db, cursor, args)
    assert "Cache status: valid" in capsys.readouterr().out

    # Touch the file so the cached entry becomes stale, then run again.
    mtime = song.stat().st_mtime + 10
    os.utime(song, (mtime, mtime))
    process_path(genplis_db, cursor, args)
    assert "Cache status: stale" in capsys.readouterr().out

    # The stale entry was refreshed by the previous run.
    process_path(genplis_db, cursor, args)
    assert "Cache status: valid" in capsys.readouterr().out


def test_process_path_prints_m3ug_filters(
    genplis_db: sqlite3.Connection,
    make_args: Callable[..., Args],
    file_m3ug: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    process_path(genplis_db, genplis_db.cursor(), make_args(str(file_m3ug)))

    output = capsys.readouterr().out
    assert f"{file_m3ug} detected as M3UG file" in output
    assert "Parsed filters:" in output
    assert "    rating greater or equal 3" in output
    assert "    genre contains Metal" in output
    assert "detected as music file" not in output
    assert "Parsed tags:" not in output


def test_process_path_warns_for_excluded_single_file(
    genplis_db: sqlite3.Connection,
    make_args: Callable[..., Args],
    file_mp3: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    args = make_args(str(file_mp3), exclude=[re.compile(r"test\.mp3$")])

    process_path(genplis_db, genplis_db.cursor(), args)

    assert (
        "WARNING: This file is excluded by current configuration."
        in capsys.readouterr().out
    )


def test_process_path_rejects_nonexistent_path(
    genplis_db: sqlite3.Connection,
    make_args: Callable[..., Args],
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    missing = tmp_path / "missing.mp3"

    with pytest.raises(SystemExit) as exc_info:
        process_path(genplis_db, genplis_db.cursor(), make_args(str(missing)))

    assert exc_info.value.code == 1
    assert (
        f"{missing} must be either a directory or a file. Exiting..."
        in capsys.readouterr().err
    )


def test_process_path_errors_without_path(
    genplis_db: sqlite3.Connection,
    make_args: Callable[..., Args],
    file_mp3: Path,
) -> None:
    args = replace(make_args(str(file_mp3)), path=None)

    with pytest.raises(GenplisError, match="none was given"):
        process_path(genplis_db, genplis_db.cursor(), args)


def test_get_calculated_tags_adds_rating_from_fmps_rating() -> None:
    assert get_calculated_tags({"fmps_rating": ["0.8"]}) == {"*rating": approx(4.0)}


def test_get_calculated_tags_omits_missing_rating() -> None:
    assert get_calculated_tags({"title": ["Test"]}) == {}


def test_get_calculated_tags_omits_rating_when_raw_rating_exists() -> None:
    tags = {"rating": 4, "fmps_rating": ["0.8"]}
    assert get_calculated_tags(tags) == {}


def test_get_calculated_tags_adds_audio_properties() -> None:
    tags = {
        "filename": "/music/test.mp3",
        "filesize": 1234,
        "duration": 1.5,
        "is_lossless": False,
        "title": ["Test"],
    }

    assert get_calculated_tags(tags) == {
        "*filename": "/music/test.mp3",
        "*filesize": 1234,
        "*duration": 1.5,
        "*is_lossless": False,
    }


def test_get_calculated_tags_omits_absent_audio_properties() -> None:
    tags = {
        "filename": "/music/test.mp3",
        "title": ["Test"],
    }

    assert get_calculated_tags(tags) == {"*filename": "/music/test.mp3"}


def test_process_path_prints_calculated_rating(
    genplis_db: sqlite3.Connection,
    make_args: Callable[..., Args],
    file_mp3: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_get_tags(*_args: object, **_kwargs: object) -> Tags:
        return {"fmps_rating": ["0.8"], "title": ["Test"]}

    monkeypatch.setattr("genplis.core.get_tags", fake_get_tags)

    process_path(genplis_db, genplis_db.cursor(), make_args(str(file_mp3)))

    assert "    *rating = 4.0" in capsys.readouterr().out


def test_process_path_omits_calculated_rating_when_raw_rating_exists(
    genplis_db: sqlite3.Connection,
    make_args: Callable[..., Args],
    file_mp3: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_get_tags(*_args: object, **_kwargs: object) -> Tags:
        return {"rating": 4, "fmps_rating": ["0.8"], "title": ["Test"]}

    monkeypatch.setattr("genplis.core.get_tags", fake_get_tags)

    process_path(genplis_db, genplis_db.cursor(), make_args(str(file_mp3)))

    output = capsys.readouterr().out
    assert "    rating = 4" in output
    assert "*rating" not in output


def test_process_path_stars_audio_properties(
    genplis_db: sqlite3.Connection,
    make_args: Callable[..., Args],
    file_mp3: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_get_tags(*_args: object, **_kwargs: object) -> Tags:
        return {
            "bitrate": 128.0,
            "duration": 1.5,
            "filename": str(file_mp3),
            "filesize": 1234,
            "is_lossless": False,
            "title": ["Test"],
        }

    monkeypatch.setattr("genplis.core.get_tags", fake_get_tags)

    process_path(genplis_db, genplis_db.cursor(), make_args(str(file_mp3)))

    output = capsys.readouterr().out
    assert "    *bitrate = 128.0" in output
    assert "    *duration = 1.5" in output
    assert f"    *filename = {file_mp3}" in output
    assert "    *filesize = 1234" in output
    assert "    *is_lossless = False" in output
    assert "    filename = " not in output
    assert "    duration = " not in output
    assert "    bitrate = " not in output
    assert "    filesize = " not in output
    assert "    is_lossless = " not in output
    assert "*bitdepth" not in output


def test_process_file_error_if_dir(
    genplis_db: sqlite3.Connection,
    make_args: Callable[..., Args],
) -> None:
    path = (Path(__file__).parent / "files").absolute()
    args = make_args(str(path))
    with pytest.raises(GenplisError):
        process_file(genplis_db, genplis_db.cursor(), path, args)


def test_process_dir(
    genplis_db: sqlite3.Connection,
    make_args: Callable[..., Args],
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


def test_process_dir_walks_nested_directories(
    genplis_db: sqlite3.Connection,
    make_args: Callable[..., Args],
    file_mp3: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    album = tmp_path / "album"
    disc = album / "disc1"
    disc.mkdir(parents=True)
    songs = [tmp_path / "root.mp3", album / "album.mp3", disc / "disc.mp3"]
    for song in songs:
        shutil.copy2(file_mp3, song)

    all_tags, all_filters = process_directory(
        genplis_db, genplis_db.cursor(), tmp_path, make_args(str(tmp_path))
    )

    assert set(all_tags) == set(songs)
    assert all_filters == {}
    assert "Processed 3 files" in capsys.readouterr().out


def test_process_dir_filters_songs_across_subdirectories(
    genplis_db: sqlite3.Connection,
    make_args: Callable[..., Args],
    file_mp3: Path,
    file_ogg: Path,
    tmp_path: Path,
) -> None:
    subdirectory = tmp_path / "sub"
    subdirectory.mkdir()
    shutil.copy2(file_mp3, tmp_path / "root.mp3")
    shutil.copy2(file_ogg, tmp_path / "root.ogg")
    shutil.copy2(file_mp3, subdirectory / "nested.mp3")
    shutil.copy2(file_ogg, subdirectory / "nested.ogg")

    filter_file = tmp_path / "favorites.m3ug"
    filter_file.write_text(
        'artist = "Test Artist"\nmime_type ~= ogg\n', encoding="utf-8"
    )

    process_directory(
        genplis_db, genplis_db.cursor(), tmp_path, make_args(str(tmp_path))
    )

    lines = (tmp_path / "favorites.m3u").read_text(encoding="utf-8").splitlines()
    playlist_entries = sorted(line for line in lines if not line.startswith("#"))
    assert playlist_entries == ["root.ogg", "sub/nested.ogg"]


def test_process_dir_does_not_create_playlist_when_no_song_matches(
    genplis_db: sqlite3.Connection,
    make_args: Callable[..., Args],
    file_mp3: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    shutil.copy2(file_mp3, tmp_path / "song.mp3")
    filter_file = tmp_path / "favorites.m3ug"
    filter_file.write_text('artist = "Nobody"\n', encoding="utf-8")

    process_directory(
        genplis_db, genplis_db.cursor(), tmp_path, make_args(str(tmp_path))
    )

    output = capsys.readouterr().out
    assert f"Filter file {filter_file} matched 0 songs" in output
    assert "Creating playlist" not in output
    assert not (tmp_path / "favorites.m3u").exists()


def test_process_dir_quiet_only_reports_filters_and_playlists(
    genplis_db: sqlite3.Connection,
    make_args: Callable[..., Args],
    file_mp3: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    shutil.copy2(file_mp3, tmp_path / "song.mp3")
    filter_file = tmp_path / "favorites.m3ug"
    filter_file.write_text('artist = "Test Artist"\n', encoding="utf-8")
    playlist_file = tmp_path / "favorites.m3u"

    process_directory(
        genplis_db,
        genplis_db.cursor(),
        tmp_path,
        make_args(str(tmp_path), verbosity=Verbosity.QUIET),
    )

    assert capsys.readouterr().out.splitlines() == [
        f"Filter file {filter_file} matched 1 songs",
        f"Creating playlist {playlist_file}",
    ]


def test_process_dir_double_quiet_prints_nothing(
    genplis_db: sqlite3.Connection,
    make_args: Callable[..., Args],
    file_mp3: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    shutil.copy2(file_mp3, tmp_path / "song.mp3")
    filter_file = tmp_path / "favorites.m3ug"
    filter_file.write_text('artist = "Test Artist"\n', encoding="utf-8")

    process_directory(
        genplis_db,
        genplis_db.cursor(),
        tmp_path,
        make_args(str(tmp_path), verbosity=Verbosity.REALLY_QUIET),
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""
    assert (tmp_path / "favorites.m3u").exists()


def test_process_dir_verbose_lists_matching_songs(
    genplis_db: sqlite3.Connection,
    make_args: Callable[..., Args],
    file_mp3: Path,
    file_ogg: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    mp3 = tmp_path / "song.mp3"
    ogg = tmp_path / "song.ogg"
    shutil.copy2(file_mp3, mp3)
    shutil.copy2(file_ogg, ogg)
    filter_file = tmp_path / "favorites.m3ug"
    filter_file.write_text("mime_type ~= ogg\n", encoding="utf-8")

    process_directory(
        genplis_db,
        genplis_db.cursor(),
        tmp_path,
        make_args(str(tmp_path), verbosity=Verbosity.VERBOSE),
    )

    output = capsys.readouterr().out
    assert f"Filtering songs and generating playlist for {filter_file}" in output
    assert f"Files that match the filter {filter_file}:" in output
    assert f"  {ogg}" in output
    assert f"  {mp3}" not in output


def test_process_dir_generates_playlist_relative_to_nested_filter_file(
    genplis_db: sqlite3.Connection,
    make_args: Callable[..., Args],
    file_mp3: Path,
    tmp_path: Path,
) -> None:
    subdirectory = tmp_path / "sub"
    subdirectory.mkdir()
    shutil.copy2(file_mp3, tmp_path / "a.mp3")
    shutil.copy2(file_mp3, subdirectory / "b.mp3")

    filter_file = subdirectory / "favorites.m3ug"
    filter_file.write_text('artist = "Test Artist"\n', encoding="utf-8")

    process_directory(
        genplis_db, genplis_db.cursor(), tmp_path, make_args(str(tmp_path))
    )

    lines = (subdirectory / "favorites.m3u").read_text(encoding="utf-8").splitlines()
    playlist_entries = sorted(line for line in lines if not line.startswith("#"))
    assert playlist_entries == ["../a.mp3", "b.mp3"]


def test_process_dir_rejects_file(
    genplis_db: sqlite3.Connection,
    make_args: Callable[..., Args],
    file_mp3: Path,
) -> None:
    with pytest.raises(GenplisError, match="not a directory"):
        process_directory(
            genplis_db,
            genplis_db.cursor(),
            file_mp3,
            make_args(str(file_mp3)),
        )


def test_process_file_uses_config_tags(
    genplis_db: sqlite3.Connection,
    make_args: Callable[..., Args],
    file_mp3: Path,
) -> None:
    config = Config(tags=TagsConfig(ignore=frozenset({"artist", "genre"})))
    args = make_args(str(file_mp3), config=config)
    tags, _, _ = process_file(genplis_db, genplis_db.cursor(), file_mp3, args)

    assert tags is not None
    assert "artist" not in tags
    assert "genre" not in tags
    assert "title" in tags


def test_process_file_uses_cached_tags_without_reparsing(
    genplis_db: sqlite3.Connection,
    make_args: Callable[..., Args],
    file_mp3: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cache_tags_for_file(genplis_db.cursor(), file_mp3, {"title": ["Cached"]})

    def fail_get_tags(*_args: object, **_kwargs: object) -> Tags:
        raise AssertionError("get_tags should not be called on a cache hit")

    monkeypatch.setattr("genplis.core.get_tags", fail_get_tags)

    tags, filters, cache_status = process_file(
        genplis_db, genplis_db.cursor(), file_mp3, make_args(str(file_mp3))
    )

    assert tags == {"title": ["Cached"]}
    assert filters == []
    assert cache_status is CacheStatus.HIT


def test_process_file_refreshes_stale_cache_entry(
    genplis_db: sqlite3.Connection,
    make_args: Callable[..., Args],
    file_mp3: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cache_tags_for_file(genplis_db.cursor(), file_mp3, {"title": ["Old"]})
    genplis_db.execute(
        "UPDATE files SET last_modified=last_modified-1 WHERE path=?",
        (str(file_mp3),),
    )

    def fake_get_tags(*_args: object, **_kwargs: object) -> Tags:
        return {"title": ["Fresh"]}

    monkeypatch.setattr("genplis.core.get_tags", fake_get_tags)

    tags, filters, cache_status = process_file(
        genplis_db, genplis_db.cursor(), file_mp3, make_args(str(file_mp3))
    )

    assert tags == {"title": ["Fresh"]}
    assert filters == []
    assert cache_status is CacheStatus.STALE
    assert get_cached_tags(genplis_db.cursor(), file_mp3) == {"title": ["Fresh"]}


def test_process_file_accepts_uppercase_m3ug_extension(
    genplis_db: sqlite3.Connection,
    make_args: Callable[..., Args],
    file_m3ug: Path,
    tmp_path: Path,
) -> None:
    filter_file = tmp_path / "FILTERS.M3UG"
    shutil.copy2(file_m3ug, filter_file)

    tags, filters, cache_status = process_file(
        genplis_db, genplis_db.cursor(), filter_file, make_args(str(filter_file))
    )

    assert tags is None
    assert len(filters) == 2
    assert cache_status is CacheStatus.MISS


def test_process_file_reads_m3ug_with_utf8_bom(
    genplis_db: sqlite3.Connection,
    make_args: Callable[..., Args],
    tmp_path: Path,
) -> None:
    filter_file = tmp_path / "bom.m3ug"
    filter_file.write_text('\ufeffartist = "Test Artist"\n', encoding="utf-8")

    tags, filters, _ = process_file(
        genplis_db, genplis_db.cursor(), filter_file, make_args(str(filter_file))
    )

    assert tags is None
    assert filters == [
        EqualRuleNode(NameNode("artist"), ValueNode("Test Artist")),
    ]


def test_process_file_ignores_unsupported_file_without_caching(
    genplis_db: sqlite3.Connection,
    make_args: Callable[..., Args],
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    unsupported = tmp_path / "notes.txt"
    unsupported.write_text("not music\n", encoding="utf-8")

    tags, filters, cache_status = process_file(
        genplis_db,
        genplis_db.cursor(),
        unsupported,
        make_args(str(unsupported), verbosity=Verbosity.VERBOSE),
    )

    assert tags is None
    assert filters == []
    assert cache_status is CacheStatus.MISS
    assert (
        f"Skipping {unsupported}: not supported by tinytag" in capsys.readouterr().out
    )
    assert genplis_db.execute("SELECT count(*) FROM files").fetchone() == (0,)


def test_process_file_returns_and_caches_empty_tags_for_supported_file(
    genplis_db: sqlite3.Connection,
    make_args: Callable[..., Args],
    file_mp3: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_get_tags(*_args: object, **_kwargs: object) -> Tags:
        return {}

    monkeypatch.setattr("genplis.core.get_tags", fake_get_tags)

    tags, filters, cache_status = process_file(
        genplis_db, genplis_db.cursor(), file_mp3, make_args(str(file_mp3))
    )

    assert tags == {}
    assert filters == []
    assert cache_status is CacheStatus.MISS
    assert get_cached_tags(genplis_db.cursor(), file_mp3) == {}


def test_process_file_uses_cached_empty_tags(
    genplis_db: sqlite3.Connection,
    make_args: Callable[..., Args],
    file_mp3: Path,
) -> None:
    cache_tags_for_file(genplis_db.cursor(), file_mp3, {})

    tags, filters, cache_status = process_file(
        genplis_db, genplis_db.cursor(), file_mp3, make_args(str(file_mp3))
    )

    assert tags == {}
    assert filters == []
    assert cache_status is CacheStatus.HIT


def test_empty_filter_includes_tagless_music_file(
    genplis_db: sqlite3.Connection,
    make_args: Callable[..., Args],
    file_mp3: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    music = tmp_path / "music"
    music.mkdir()
    song = music / "tagless.mp3"
    shutil.copy2(file_mp3, song)
    filter_file = music / "all.m3ug"
    filter_file.write_text("", encoding="utf-8")

    def fake_get_tags(*_args: object, **_kwargs: object) -> Tags:
        return {}

    monkeypatch.setattr("genplis.core.get_tags", fake_get_tags)

    all_tags, all_filters = process_directory(
        genplis_db, genplis_db.cursor(), music, make_args(str(music))
    )

    assert all_tags == {song: {}}
    assert all_filters == {filter_file: []}
    playlist = filter_file.with_suffix(".m3u")
    assert song.name in playlist.read_text(encoding="utf-8").splitlines()


def test_process_path_reports_tagless_music_file(
    genplis_db: sqlite3.Connection,
    make_args: Callable[..., Args],
    file_mp3: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_get_tags(*_args: object, **_kwargs: object) -> Tags:
        return {}

    monkeypatch.setattr("genplis.core.get_tags", fake_get_tags)

    process_path(genplis_db, genplis_db.cursor(), make_args(str(file_mp3)))

    output = capsys.readouterr().out
    assert f"{file_mp3} detected as music file" in output
    assert "Parsed tags:" in output


def test_process_dir_respects_overwrite_setting(
    genplis_db: sqlite3.Connection,
    make_args: Callable[..., Args],
    file_mp3: Path,
    file_ogg: Path,
    tmp_path: Path,
) -> None:
    for source in (file_mp3, file_ogg):
        shutil.copy2(source, tmp_path / source.name)

    filter_file = tmp_path / "favorites.m3ug"
    filter_file.write_text('artist = "Test Artist"\n')
    playlist_file = tmp_path / "favorites.m3u"
    playlist_file.write_text("keep this\n")

    args = make_args(str(tmp_path), overwrite=False)
    process_directory(genplis_db, genplis_db.cursor(), tmp_path, args)

    assert playlist_file.read_text() == "keep this\n"


def test_process_dir_prints_and_prunes_excluded_folder(
    genplis_db: sqlite3.Connection,
    make_args: Callable[..., Args],
    file_mp3: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    excluded = tmp_path / "@eaDir"
    excluded.mkdir()
    shutil.copy2(file_mp3, excluded / file_mp3.name)

    # The pattern targets folder paths, which only match with a trailing
    # separator added before testing.
    args = make_args(
        str(tmp_path), exclude=[re.compile(r"/@eaDir/")], verbosity=Verbosity.VERBOSE
    )
    all_tags, all_filters = process_directory(
        genplis_db, genplis_db.cursor(), tmp_path, args
    )

    output = capsys.readouterr().out
    assert f"Skipping {excluded} because of exclude pattern." in output
    assert str(excluded / file_mp3.name) not in output
    assert all_tags == {}
    assert all_filters == {}


def test_process_dir_prunes_excluded_folder_without_verbose(
    genplis_db: sqlite3.Connection,
    make_args: Callable[..., Args],
    file_mp3: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    excluded = tmp_path / "@eaDir"
    excluded.mkdir()
    shutil.copy2(file_mp3, excluded / file_mp3.name)

    args = make_args(str(tmp_path), exclude=[re.compile(r"/@eaDir/")])
    all_tags, _ = process_directory(genplis_db, genplis_db.cursor(), tmp_path, args)

    assert "Skipping" not in capsys.readouterr().out
    assert all_tags == {}


def test_process_dir_still_skips_excluded_files(
    genplis_db: sqlite3.Connection,
    make_args: Callable[..., Args],
    file_mp3: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    shutil.copy2(file_mp3, tmp_path / "keep.mp3")
    shutil.copy2(file_mp3, tmp_path / "skip-me.mp3")

    args = make_args(
        str(tmp_path),
        exclude=[re.compile(r"skip-me\.mp3$")],
        verbosity=Verbosity.VERBOSE,
    )
    all_tags, _ = process_directory(genplis_db, genplis_db.cursor(), tmp_path, args)

    output = capsys.readouterr().out
    assert f"Skipping {tmp_path / 'skip-me.mp3'} because of exclude pattern." in output
    assert f"Skipping {tmp_path} because of exclude pattern." not in output
    assert set(all_tags) == {tmp_path / "keep.mp3"}


def test_process_dir_includes_m3ug_source_as_comments(
    genplis_db: sqlite3.Connection,
    make_args: Callable[..., Args],
    file_mp3: Path,
    file_ogg: Path,
    tmp_path: Path,
) -> None:
    for source in (file_mp3, file_ogg):
        shutil.copy2(source, tmp_path / source.name)

    filter_file = tmp_path / "favorites.m3ug"
    filter_file.write_text(
        '# 5-star artists\n#EXTINF:ignored,Directive\nartist = "Test Artist"\n',
        encoding="utf-8",
    )

    args = make_args(str(tmp_path))
    process_directory(genplis_db, genplis_db.cursor(), tmp_path, args)

    lines = (tmp_path / "favorites.m3u").read_text(encoding="utf-8").splitlines()
    assert lines[:5] == [
        '# Generated by genplis from "favorites.m3ug"',
        "#",
        "# # 5-star artists",
        "# #EXTINF:ignored,Directive",
        '# artist = "Test Artist"',
    ]
    assert set(lines[5:]) == {"test.mp3", "test.ogg"}


def test_process_dir_can_disable_source_comments(
    genplis_db: sqlite3.Connection,
    make_args: Callable[..., Args],
    file_mp3: Path,
    file_ogg: Path,
    tmp_path: Path,
) -> None:
    for source in (file_mp3, file_ogg):
        shutil.copy2(source, tmp_path / source.name)

    filter_file = tmp_path / "favorites.m3ug"
    filter_file.write_text('artist = "Test Artist"\n', encoding="utf-8")

    args = make_args(str(tmp_path), include_source=False)
    process_directory(genplis_db, genplis_db.cursor(), tmp_path, args)

    lines = (tmp_path / "favorites.m3u").read_text(encoding="utf-8").splitlines()
    assert set(lines) == {"test.mp3", "test.ogg"}


def test_resolve_args_uses_config_path() -> None:
    config = Config(collection=CollectionConfig(path=Path("/music")))
    args = resolve_args(setup_argparse().parse_args([]), config)

    assert args.path == Path("/music")


def test_resolve_args_cli_path_wins_over_config() -> None:
    config = Config(collection=CollectionConfig(path=Path("/config/music")))
    args = resolve_args(
        setup_argparse().parse_args(["/cli/music"]),
        config,
    )

    assert args.path == Path("/cli/music")


def test_resolve_args_requires_path() -> None:
    with pytest.raises(GenplisConfigError, match="PATH is required"):
        resolve_args(setup_argparse().parse_args([]), Config())


def test_resolve_args_cli_exclude_replaces_config() -> None:
    config = Config(
        collection=CollectionConfig(
            path=Path("/music"),
            exclude=(re.compile("from-config"),),
        )
    )
    args = resolve_args(
        setup_argparse().parse_args(["-e", "from-cli"]),
        config,
    )

    assert [pattern.pattern for pattern in args.exclude] == ["from-cli"]


def test_resolve_args_uses_config_exclude_without_cli() -> None:
    config = Config(
        collection=CollectionConfig(
            path=Path("/music"),
            exclude=(re.compile("from-config"),),
        )
    )
    args = resolve_args(setup_argparse().parse_args([]), config)

    assert [pattern.pattern for pattern in args.exclude] == ["from-config"]


def test_resolve_args_boolean_precedence() -> None:
    config = Config(
        general=GeneralConfig(verbose=True),
        output=OutputConfig(overwrite=False, include_source=False),
    )
    args = resolve_args(
        setup_argparse().parse_args(
            ["--no-verbose", "--overwrite", "--include-source", "/music"]
        ),
        config,
    )

    assert args.verbosity is Verbosity.NORMAL
    assert args.overwrite is True
    assert args.include_source is True


def test_resolve_args_verbosity() -> None:
    parser = setup_argparse()

    def resolve(argv: list[str], config: Config | None = None) -> Verbosity:
        return resolve_args(
            parser.parse_args([*argv, "/music"]),
            config if config is not None else Config(),
        ).verbosity

    assert resolve([]) is Verbosity.NORMAL
    assert resolve([], Config(general=GeneralConfig(verbose=True))) is Verbosity.VERBOSE
    assert resolve([], Config(general=GeneralConfig(quiet=True))) is Verbosity.QUIET
    assert (
        resolve(["--no-verbose"], Config(general=GeneralConfig(verbose=True)))
        is Verbosity.NORMAL
    )
    assert (
        resolve(["--no-verbose"], Config(general=GeneralConfig(quiet=True)))
        is Verbosity.QUIET
    )
    assert resolve(["-v"]) is Verbosity.VERBOSE
    assert (
        resolve(["-v"], Config(general=GeneralConfig(quiet=True))) is Verbosity.VERBOSE
    )
    assert (
        resolve(["-q"], Config(general=GeneralConfig(verbose=True))) is Verbosity.QUIET
    )
    assert resolve(["-qq"]) is Verbosity.REALLY_QUIET
    assert resolve(["-qqq"]) is Verbosity.REALLY_QUIET


def test_resolve_args_uses_include_source_from_config() -> None:
    config = Config(
        collection=CollectionConfig(path=Path("/music")),
        output=OutputConfig(include_source=False),
    )
    args = resolve_args(setup_argparse().parse_args([]), config)

    assert args.include_source is False


def test_resolve_args_db_path_precedence(tmp_path: Path) -> None:
    config = Config(
        collection=CollectionConfig(path=Path("/music")),
        database=DatabaseConfig(path=tmp_path / "config.db"),
    )
    parser = setup_argparse()

    from_config = resolve_args(parser.parse_args([]), config)
    assert from_config.db_path == tmp_path / "config.db"

    from_cli = resolve_args(
        parser.parse_args(["--db", str(tmp_path / "cli.db")]),
        config,
    )
    assert from_cli.db_path == tmp_path / "cli.db"


def test_resolve_args_allows_clean_without_path() -> None:
    args = resolve_args(setup_argparse().parse_args(["--clean"]), Config())

    assert args.path is None
    assert args.clean is True


def test_resolve_args_clean_uses_config_path() -> None:
    config = Config(collection=CollectionConfig(path=Path("/music")))
    args = resolve_args(setup_argparse().parse_args(["--clean"]), config)

    assert args.path == Path("/music")
    assert args.clean is True


def test_format_size() -> None:
    assert format_size(0) == "0 B"
    assert format_size(1023) == "1023 B"
    assert format_size(1024) == "1.0 KiB"
    assert format_size(1536) == "1.5 KiB"
    assert format_size(1024 * 1024) == "1.0 MiB"


def test_clean_database_reports_stats(
    genplis_db: sqlite3.Connection,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    missing = tmp_path / "gone.mp3"
    genplis_db.execute(
        "INSERT INTO files(path, last_modified, tags) VALUES (?, 0, '{}')",
        (str(missing),),
    )

    stats = clean_database(
        genplis_db,
        genplis_db.cursor(),
        None,
        tmp_path / "genplis.db",
        verbosity=Verbosity.VERBOSE,
    )

    output = capsys.readouterr().out
    assert stats.removed == (missing,)
    assert f"Removed stale cache entry for {missing}" in output
    assert "Removed 1 stale entry from the cache database." in output
    assert "Database size:" in output
    assert "saved)." in output


def test_main_clean_without_path_removes_stale_entries(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    db_path = tmp_path / "genplis.db"
    conn, cursor = setup_database_connection(db_path)
    try:
        create_files_table(cursor)
        for index in range(50):
            cursor.execute(
                "INSERT INTO files(path, last_modified, tags) VALUES (?, 0, ?)",
                (
                    str(tmp_path / f"gone-{index}.mp3"),
                    json.dumps({"blob": "x" * 4096}),
                ),
            )
        existing = tmp_path / "keep.mp3"
        existing.write_bytes(b"")
        cursor.execute(
            "INSERT INTO files(path, last_modified, tags) VALUES (?, 0, '{}')",
            (str(existing),),
        )
        conn.commit()
        size_before = db_path.stat().st_size
    finally:
        conn.close()

    monkeypatch.setattr(
        sys,
        "argv",
        ["genplis", "--clean", "--no-config", "--db", str(db_path)],
    )
    main()

    output = capsys.readouterr().out
    assert "Removed 50 stale entries from the cache database." in output
    assert "Database size:" in output
    assert "saved)." in output
    assert db_path.stat().st_size < size_before

    conn, cursor = setup_database_connection(db_path)
    try:
        assert cursor.execute("SELECT path FROM files").fetchall() == [(str(existing),)]
    finally:
        conn.close()


def test_main_clean_with_path_processes_and_scopes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    file_mp3: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    music = tmp_path / "music"
    music.mkdir()
    song = music / "song.mp3"
    shutil.copy2(file_mp3, song)

    outside = tmp_path / "outside"
    outside.mkdir()
    outside_missing = outside / "gone.mp3"
    inside_missing = music / "gone.mp3"

    db_path = tmp_path / "genplis.db"
    conn, cursor = setup_database_connection(db_path)
    try:
        create_files_table(cursor)
        for missing in (inside_missing, outside_missing):
            cursor.execute(
                "INSERT INTO files(path, last_modified, tags) VALUES (?, 0, '{}')",
                (str(missing),),
            )
        conn.commit()
    finally:
        conn.close()

    monkeypatch.setattr(
        sys,
        "argv",
        ["genplis", "--clean", "--no-config", "--db", str(db_path), str(music)],
    )
    main()

    output = capsys.readouterr().out
    assert "Removed 1 stale entry from the cache database." in output

    conn, cursor = setup_database_connection(db_path)
    try:
        assert set(cursor.execute("SELECT path FROM files").fetchall()) == {
            (str(song),),
            (str(outside_missing),),
        }
    finally:
        conn.close()


def test_main_clean_without_database(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    db_path = tmp_path / "missing" / "genplis.db"
    monkeypatch.setattr(
        sys,
        "argv",
        ["genplis", "--clean", "--no-config", "--db", str(db_path)],
    )

    main()

    assert "Database does not exist; nothing to clean." in capsys.readouterr().out
    assert not db_path.exists()


def test_main_rejects_quiet_and_verbose_together(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        ["genplis", "-q", "-v", "--no-config", "/music"],
    )

    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "--quiet cannot be combined with --verbose" in captured.err


def test_main_closes_database_connection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "genplis.db"
    db_path.touch()
    real_connect = sqlite3.connect

    class TrackingConnection(sqlite3.Connection):
        was_closed = False

        def close(self) -> None:
            type(self).was_closed = True
            super().close()

    def tracking_connect(*_args: object, **_kwargs: object) -> sqlite3.Connection:
        return real_connect(db_path, factory=TrackingConnection)

    monkeypatch.setattr("genplis.core.sqlite3.connect", tracking_connect)
    monkeypatch.setattr(
        sys,
        "argv",
        ["genplis", "--clean", "--no-config", "--db", str(db_path)],
    )

    main()

    assert TrackingConnection.was_closed


def test_main_reports_m3ug_error_with_location(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    music = tmp_path / "music"
    music.mkdir()
    invalid = music / "favorites.m3ug"
    invalid.write_text("invalid\n", encoding="utf-8")
    db_path = tmp_path / "genplis.db"
    monkeypatch.setattr(
        sys,
        "argv",
        ["genplis", "--no-config", "--db", str(db_path), str(music)],
    )

    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert f"{invalid}:1: Invalid filter syntax" in captured.err
    assert "Traceback" not in captured.err
    assert captured.out == ""


def test_main_double_quiet_reports_errors_on_stderr(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    db_path = tmp_path / "genplis.db"
    missing = tmp_path / "missing.mp3"
    monkeypatch.setattr(
        sys,
        "argv",
        ["genplis", "-qq", "--no-config", "--db", str(db_path), str(missing)],
    )

    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert f"{missing} must be either a directory or a file." in captured.err
