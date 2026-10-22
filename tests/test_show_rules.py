import re
import sys
from collections.abc import Callable
from pathlib import Path

import pytest

from genplis.config import CollectionConfig, Config
from genplis.core import Args, Mode, main, resolve_args, setup_argparse, show_rules
from genplis.exceptions import GenplisConfigError, GenplisError
from genplis.types import Verbosity


def _args(
    make_args: Callable[..., Args],
    path: Path,
    *,
    filters: tuple[Path, ...] = (),
    verbosity: Verbosity = Verbosity.NORMAL,
    exclude: list[re.Pattern[str]] | None = None,
    config: Config | None = None,
) -> Args:
    return make_args(
        str(path),
        mode=Mode.SHOW_RULES,
        verbosity=verbosity,
        exclude=exclude,
        config=config,
        filters=filters,
    )


def test_show_rules_prints_one_tree(
    make_args: Callable[..., Args],
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    filter_file = tmp_path / "favorites.m3ug"
    filter_file.write_text("artist = X\nrating >= 4\n", encoding="utf-8")

    show_rules(_args(make_args, tmp_path, filters=(filter_file,)))

    output = capsys.readouterr().out
    assert output.splitlines()[0] == str(filter_file)
    assert "  AND" in output
    assert "    artist = X (line 1)" in output
    assert "    rating >= 4 (line 2)" in output
    assert "    sort: filename (default)" in output


def test_show_rules_directory_prints_each_filter(
    make_args: Callable[..., Args],
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    first = tmp_path / "first.m3ug"
    second = tmp_path / "second.m3ug"
    skipped = tmp_path / "skip.m3ug"
    first.write_text("artist = X\n", encoding="utf-8")
    second.write_text("genre = Metal\n", encoding="utf-8")
    skipped.write_text("artist = Skipped\n", encoding="utf-8")

    show_rules(
        _args(
            make_args,
            tmp_path,
            exclude=[re.compile(r"skip\.m3ug$")],
        )
    )

    output = capsys.readouterr().out
    assert str(first) in output
    assert str(second) in output
    assert str(skipped) not in output


def test_show_rules_renders_includes(
    make_args: Callable[..., Args],
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    base = tmp_path / "Base.m3ug"
    main_filter = tmp_path / "Main.m3ug"
    base.write_text("genre = Metal\n", encoding="utf-8")
    main_filter.write_text("@INCLUDE Base.m3ug\nartist = X\n", encoding="utf-8")

    show_rules(_args(make_args, tmp_path, filters=(main_filter,)))

    output = capsys.readouterr().out
    assert f"  @INCLUDE Base.m3ug (Main.m3ug:1) -> {base.resolve()}" in output
    assert "    genre = Metal (line 1)" in output
    assert "  artist = X (line 2)" in output


def test_show_rules_uses_config_path(
    make_args: Callable[..., Args],
    tmp_path: Path,
) -> None:
    config = Config(collection=CollectionConfig(path=tmp_path))
    args = resolve_args(
        setup_argparse().parse_args(["--show-rules"]),
        config,
    )

    assert args.mode is Mode.SHOW_RULES
    assert args.path == tmp_path


def test_main_show_rules_opens_no_database_or_playlist(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    filter_file = tmp_path / "favorites.m3ug"
    filter_file.write_text("artist = X\n", encoding="utf-8")
    db_path = tmp_path / "genplis.db"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "genplis",
            "--show-rules",
            "--no-config",
            "--db",
            str(db_path),
            "--filter",
            str(filter_file),
        ],
    )

    main()

    output = capsys.readouterr().out
    assert "artist = X (line 1)" in output
    assert "Using" not in output
    assert not db_path.exists()
    assert not filter_file.with_suffix(".m3u").exists()


def test_show_rules_rejects_audio_path(
    make_args: Callable[..., Args],
    file_mp3: Path,
) -> None:
    with pytest.raises(GenplisError, match="must be a directory"):
        show_rules(_args(make_args, file_mp3))


def test_show_rules_rejects_m3ug_path(
    make_args: Callable[..., Args],
    file_m3ug: Path,
) -> None:
    with pytest.raises(GenplisError, match="must be a directory"):
        show_rules(_args(make_args, file_m3ug))


def test_show_rules_reports_empty_directory(
    make_args: Callable[..., Args],
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    show_rules(_args(make_args, tmp_path))

    assert f"No filters found in {tmp_path}" in capsys.readouterr().out


def test_show_rules_quiet_modes(
    make_args: Callable[..., Args],
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    filter_file = tmp_path / "favorites.m3ug"
    filter_file.write_text("artist = X\n", encoding="utf-8")

    show_rules(
        _args(make_args, tmp_path, filters=(filter_file,), verbosity=Verbosity.QUIET)
    )
    assert "artist = X" in capsys.readouterr().out

    show_rules(
        _args(
            make_args,
            tmp_path,
            filters=(filter_file,),
            verbosity=Verbosity.REALLY_QUIET,
        )
    )
    assert capsys.readouterr().out == ""


def test_main_show_rules_color_flags_and_auto_theme(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    filter_file = tmp_path / "favorites.m3ug"
    filter_file.write_text("artist = X\n", encoding="utf-8")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "genplis",
            "--show-rules",
            "--color",
            "--no-config",
            "--filter",
            str(filter_file),
        ],
    )

    monkeypatch.setenv("COLORFGBG", "15;0")
    main()
    assert "\x1b[38;5;51martist\x1b[0m" in capsys.readouterr().out

    monkeypatch.setenv("COLORFGBG", "0;15")
    main()
    assert "\x1b[38;5;30martist\x1b[0m" in capsys.readouterr().out

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "genplis",
            "--show-rules",
            "--no-color",
            "--no-config",
            "--filter",
            str(filter_file),
        ],
    )
    main()
    assert "\x1b[" not in capsys.readouterr().out


def test_show_rules_mode_conflicts(
    tmp_path: Path,
) -> None:
    parser = setup_argparse()
    for conflicting in ("--tag-stats", "--clean"):
        with pytest.raises(SystemExit) as exc_info:
            parser.parse_args(["--show-rules", conflicting, str(tmp_path)])
        assert exc_info.value.code == 2

    with pytest.raises(GenplisConfigError, match="cannot be combined"):
        resolve_args(
            parser.parse_args(["--show-rules", "-t", "genre", str(tmp_path)]),
            Config(),
        )
