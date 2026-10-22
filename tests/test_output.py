import io

import pytest

from genplis.output import (
    ColorRole,
    Output,
    Palette,
    Progress,
    Theme,
    color_enabled,
    colorfgbg_background,
    detect_theme,
    resolve_theme,
)


class FakeStream(io.StringIO):
    def __init__(self, *, tty: bool) -> None:
        super().__init__()
        self.tty = tty

    def isatty(self) -> bool:
        return self.tty


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, None),
        ("", None),
        ("15;0", 0),
        ("0;15", 15),
        ("0;default;15", 15),
        ("0;255", 255),
        ("0;256", None),
        ("15;default", None),
        ("not a color", None),
    ],
)
def test_colorfgbg_background(value: str | None, expected: int | None) -> None:
    assert colorfgbg_background(value) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("15;0", Theme.DARK),
        ("0;15", Theme.LIGHT),
        ("0;7", Theme.LIGHT),
        ("0;8", Theme.DARK),
        ("0;231", Theme.LIGHT),
        ("0;16", Theme.DARK),
        ("nonsense", Theme.DARK),
    ],
)
def test_detect_theme_from_colorfgbg(value: str, expected: Theme) -> None:
    assert detect_theme({"COLORFGBG": value}) is expected


def test_detect_theme_defaults_to_dark() -> None:
    assert detect_theme({}) is Theme.DARK


def test_resolve_theme_respects_explicit_values() -> None:
    assert resolve_theme(Theme.LIGHT, {"COLORFGBG": "15;0"}) is Theme.LIGHT
    assert resolve_theme(Theme.DARK, {"COLORFGBG": "0;15"}) is Theme.DARK
    assert resolve_theme(Theme.AUTO, {"COLORFGBG": "0;15"}) is Theme.LIGHT


def test_palette_disabled_returns_plain_text() -> None:
    palette = Palette(theme=Theme.DARK, enabled=False)

    assert palette.paint(ColorRole.PASS, "PASS") == "PASS"
    assert palette.tag("artist") == "artist"
    assert palette.paint(ColorRole.VALUE, "") == ""


@pytest.mark.parametrize(
    ("theme", "role", "code", "text"),
    [
        (Theme.DARK, ColorRole.PASS, 40, "PASS"),
        (Theme.DARK, ColorRole.FAIL, 196, "FAIL"),
        (Theme.DARK, ColorRole.SKIP, 117, "SKIP"),
        (Theme.DARK, ColorRole.DIRECTIVE, 208, "sort:"),
        (Theme.DARK, ColorRole.TAG, 51, "artist"),
        (Theme.DARK, ColorRole.VALUE, 220, '"X"'),
        (Theme.LIGHT, ColorRole.PASS, 28, "PASS"),
        (Theme.LIGHT, ColorRole.FAIL, 160, "FAIL"),
        (Theme.LIGHT, ColorRole.SKIP, 32, "SKIP"),
        (Theme.LIGHT, ColorRole.DIRECTIVE, 166, "sort:"),
        (Theme.LIGHT, ColorRole.TAG, 30, "artist"),
        (Theme.LIGHT, ColorRole.VALUE, 90, '"X"'),
    ],
)
def test_palette_theme_codes(
    theme: Theme, role: ColorRole, code: int, text: str
) -> None:
    palette = Palette(theme=theme, enabled=True)

    assert palette.paint(role, text) == f"\x1b[38;5;{code}m{text}\x1b[0m"


def test_palette_bold_roles() -> None:
    palette = Palette(theme=Theme.DARK, enabled=True)

    assert palette.title("Title") == "\x1b[1;38;5;255mTitle\x1b[0m"
    assert palette.operator("AND") == "\x1b[1mAND\x1b[0m"


def test_color_enabled_precedence() -> None:
    tty = FakeStream(tty=True)
    pipe = FakeStream(tty=False)

    assert color_enabled(True, pipe, {"NO_COLOR": "1"}) is True
    assert color_enabled(False, tty, {"FORCE_COLOR": "1"}) is False
    assert color_enabled(None, tty, {"NO_COLOR": "1"}) is False
    assert color_enabled(None, pipe, {"FORCE_COLOR": "1"}) is True
    assert color_enabled(None, tty, {"TERM": "dumb"}) is False
    assert color_enabled(None, tty, {}) is True
    assert color_enabled(None, pipe, {}) is False


def test_output_create_and_write() -> None:
    stream = FakeStream(tty=True)
    output = Output.create(
        stream,
        color=None,
        theme=Theme.AUTO,
        environ={"COLORFGBG": "0;15"},
    )

    output.line(output.palette.tag("artist"))

    assert output.palette.theme is Theme.LIGHT
    assert output.palette.enabled is True
    assert stream.getvalue() == "\x1b[38;5;30martist\x1b[0m\n"


def test_output_plain_has_no_color() -> None:
    stream = FakeStream(tty=True)
    output = Output.plain(stream)

    output.line(output.palette.paint(ColorRole.PASS, "PASS"))

    assert stream.getvalue() == "PASS\n"


def test_progress_draws_scan_and_parse_bar_on_a_terminal() -> None:
    stream = FakeStream(tty=True)
    progress = Progress(Output.plain(stream))

    progress.scanning()
    progress.start(2)
    progress.advance(2)
    progress.close()

    output = stream.getvalue()
    assert "Scanning collection..." in output
    assert "Parsing audio [" in output
    assert "2/2 (100%)" in output
    assert output.endswith("\n")


def test_progress_prints_one_summary_line_when_redirected() -> None:
    stream = FakeStream(tty=False)
    progress = Progress(Output.plain(stream))

    progress.scanning()
    progress.start(1)
    progress.advance()
    progress.close()

    assert stream.getvalue() == "Parsing 1 file...\n"


def test_progress_is_silent_when_disabled() -> None:
    stream = FakeStream(tty=True)
    progress = Progress(Output.plain(stream), enabled=False)

    progress.scanning()
    progress.tick()
    progress.start(3)
    progress.advance()
    progress.close()

    assert stream.getvalue() == ""


def test_progress_skips_empty_parse_queues() -> None:
    stream = FakeStream(tty=True)
    progress = Progress(Output.plain(stream))

    progress.scanning()
    progress.start(0)
    progress.close()

    assert "Parsing audio" not in stream.getvalue()
