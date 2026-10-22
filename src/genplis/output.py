"""Console output helpers and terminal color themes."""

from __future__ import annotations

import os
import re
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum, auto
from typing import TextIO

RESET = "\x1b[0m"


class Theme(Enum):
    """A terminal color theme, or automatic detection."""

    AUTO = "auto"
    DARK = "dark"
    LIGHT = "light"


class ColorRole(Enum):
    """Semantic roles that can be colored independently."""

    PASS = auto()
    FAIL = auto()
    SKIP = auto()
    DIRECTIVE = auto()
    TAG = auto()
    VALUE = auto()
    SOURCE = auto()
    TITLE = auto()
    OPERATOR = auto()
    WARNING = auto()
    ERROR = auto()


_DARK_COLORS = {
    ColorRole.PASS: 40,
    ColorRole.FAIL: 196,
    ColorRole.SKIP: 117,
    ColorRole.DIRECTIVE: 208,
    ColorRole.TAG: 51,
    ColorRole.VALUE: 220,
    ColorRole.SOURCE: 244,
    ColorRole.TITLE: 255,
    ColorRole.WARNING: 214,
    ColorRole.ERROR: 196,
}

_LIGHT_COLORS = {
    ColorRole.PASS: 28,
    ColorRole.FAIL: 160,
    ColorRole.SKIP: 32,
    ColorRole.DIRECTIVE: 166,
    ColorRole.TAG: 30,
    ColorRole.VALUE: 90,
    ColorRole.SOURCE: 242,
    ColorRole.TITLE: 235,
    ColorRole.WARNING: 130,
    ColorRole.ERROR: 160,
}

_BOLD_ROLES = frozenset({ColorRole.TITLE, ColorRole.OPERATOR})


@dataclass(frozen=True, slots=True)
class Palette:
    """Maps semantic roles to ANSI colors for one terminal theme."""

    theme: Theme = Theme.DARK
    enabled: bool = False

    def paint(self, role: ColorRole, text: str) -> str:
        """Color text for a role, or return it unchanged when disabled."""
        if not self.enabled or not text:
            return text
        colors = _LIGHT_COLORS if self.theme is Theme.LIGHT else _DARK_COLORS
        codes: list[str] = []
        if role in _BOLD_ROLES:
            codes.append("1")
        color = colors.get(role)
        if color is not None:
            codes.append(f"38;5;{color}")
        if not codes:
            return text
        return f"\x1b[{';'.join(codes)}m{text}{RESET}"

    def tag(self, text: str) -> str:
        return self.paint(ColorRole.TAG, text)

    def value(self, text: str) -> str:
        return self.paint(ColorRole.VALUE, text)

    def directive(self, text: str) -> str:
        return self.paint(ColorRole.DIRECTIVE, text)

    def source(self, text: str) -> str:
        return self.paint(ColorRole.SOURCE, text)

    def title(self, text: str) -> str:
        return self.paint(ColorRole.TITLE, text)

    def operator(self, text: str) -> str:
        return self.paint(ColorRole.OPERATOR, text)

    def warning(self, text: str) -> str:
        return self.paint(ColorRole.WARNING, text)

    def error(self, text: str) -> str:
        return self.paint(ColorRole.ERROR, text)


def _xterm_rgb(index: int) -> tuple[int, int, int]:
    """Return the approximate RGB value for an xterm color index."""
    base = (
        (0, 0, 0),
        (128, 0, 0),
        (0, 128, 0),
        (128, 128, 0),
        (0, 0, 128),
        (128, 0, 128),
        (0, 128, 128),
        (192, 192, 192),
        (128, 128, 128),
        (255, 0, 0),
        (0, 255, 0),
        (255, 255, 0),
        (0, 0, 255),
        (255, 0, 255),
        (0, 255, 255),
        (255, 255, 255),
    )
    if index < 16:
        return base[index]
    if index < 232:
        value = index - 16
        levels = (0, 95, 135, 175, 215, 255)
        return (
            levels[value // 36],
            levels[(value % 36) // 6],
            levels[value % 6],
        )
    gray = 8 + 10 * (index - 232)
    return gray, gray, gray


def _relative_luminance(color: tuple[int, int, int]) -> float:
    """Return WCAG relative luminance for an RGB color."""

    def linearize(component: int) -> float:
        value = component / 255
        if value <= 0.04045:
            return value / 12.92
        return ((value + 0.055) / 1.055) ** 2.4

    red, green, blue = (linearize(component) for component in color)
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def colorfgbg_background(value: str | None) -> int | None:
    """Return the background color index from a ``COLORFGBG`` value."""
    if not value:
        return None
    last = value.rsplit(";", 1)[-1].strip()
    if not re.fullmatch(r"\d+", last):
        return None
    index = int(last)
    if 0 <= index <= 255:
        return index
    return None


def detect_theme(environ: Mapping[str, str] | None = None) -> Theme:
    """Guess the terminal theme from the environment, preferring dark."""
    environment = os.environ if environ is None else environ
    background = colorfgbg_background(environment.get("COLORFGBG"))
    if background is None:
        return Theme.DARK
    luminance = _relative_luminance(_xterm_rgb(background))
    return Theme.LIGHT if luminance >= 0.5 else Theme.DARK


def resolve_theme(configured: Theme, environ: Mapping[str, str] | None = None) -> Theme:
    """Resolve ``auto`` to a concrete light or dark theme."""
    if configured is Theme.AUTO:
        return detect_theme(environ)
    return configured


def _force_color(environ: Mapping[str, str]) -> bool:
    value = environ.get("FORCE_COLOR")
    return value is not None and value.lower() not in {"", "0", "false", "no"}


def color_enabled(
    setting: bool | None,
    stream: TextIO,
    environ: Mapping[str, str] | None = None,
) -> bool:
    """Resolve the color setting against ``NO_COLOR`` and terminal support.

    ``True`` forces color, ``False`` disables it, and ``None`` means automatic.
    """
    environment = os.environ if environ is None else environ
    if setting is not None:
        return setting
    if environment.get("NO_COLOR"):
        return False
    if _force_color(environment):
        return True
    if environment.get("TERM") == "dumb":
        return False
    return stream.isatty()


@dataclass(slots=True)
class Output:
    """A text stream with an attached color palette."""

    stream: TextIO
    palette: Palette

    @classmethod
    def create(
        cls,
        stream: TextIO,
        *,
        color: bool | None = None,
        theme: Theme = Theme.AUTO,
        environ: Mapping[str, str] | None = None,
    ) -> Output:
        environment = os.environ if environ is None else environ
        return cls(
            stream=stream,
            palette=Palette(
                theme=resolve_theme(theme, environment),
                enabled=color_enabled(color, stream, environment),
            ),
        )

    @classmethod
    def plain(cls, stream: TextIO | None = None) -> Output:
        return cls(
            stream=sys.stdout if stream is None else stream,
            palette=Palette(),
        )

    def line(self, text: str = "") -> None:
        print(text, file=self.stream)

    def write(self, text: str) -> None:
        self.stream.write(text)
