"""Shared types and type aliases."""

from enum import Enum, auto


class Verbosity(Enum):
    """How much normal output genplis produces."""

    VERBOSE = auto()
    NORMAL = auto()
    QUIET = auto()
    REALLY_QUIET = auto()

    @property
    def is_verbose(self) -> bool:
        """Return whether verbose diagnostics should be printed."""
        return self is Verbosity.VERBOSE

    @property
    def shows_normal_output(self) -> bool:
        """Return whether normal, non-progress output should be printed."""
        return self in (Verbosity.VERBOSE, Verbosity.NORMAL)

    @property
    def shows_progress(self) -> bool:
        """Return whether filter and playlist progress should be printed."""
        return self is not Verbosity.REALLY_QUIET


type TagValue = str | float | int | bool | list[str] | None
type Tags = dict[str, TagValue]
