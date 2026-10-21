"""Parse tag files sequentially or in a pool of worker processes."""

import multiprocessing
import os
from collections.abc import Iterator, Sequence
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from itertools import batched
from pathlib import Path
from typing import Protocol

from .config import TagsConfig
from .tags import parse_tags
from .types import Tags

MIN_PARALLEL_FILES = 64
BATCH_SIZE = 32
MAX_AUTO_WORKERS = 8


@dataclass(frozen=True, slots=True)
class ParseItem:
    """One cache-miss or stale file queued for parsing."""

    path: Path
    last_modified: int


@dataclass(frozen=True, slots=True)
class ParseResult:
    """Parsed tags and diagnostics for one ParseItem."""

    item: ParseItem
    tags: Tags | None
    messages: tuple[str, ...]


class ParseExecutor(Protocol):
    """Parse pending files in walk order."""

    def parse(self, items: Sequence[ParseItem]) -> Iterator[ParseResult]: ...

    def close(self, *, cancel: bool = False) -> None: ...


_WORKER_SETTINGS: TagsConfig | None = None


def _init_worker(settings: TagsConfig) -> None:
    global _WORKER_SETTINGS
    _WORKER_SETTINGS = settings


def _parse_item(item: ParseItem, settings: TagsConfig) -> ParseResult:
    tags, messages = parse_tags(
        item.path,
        max_size=settings.max_size,
        ignore=settings.ignore,
    )
    return ParseResult(item, tags, messages)


def _parse_one(item: ParseItem) -> ParseResult:
    settings = _WORKER_SETTINGS
    if settings is None:
        raise RuntimeError("worker settings were not initialized")
    return _parse_item(item, settings)


def _parse_batch(items: Sequence[ParseItem]) -> list[ParseResult]:
    return [_parse_one(item) for item in items]


def auto_workers() -> int:
    """Return the default worker count: CPU affinity capped at eight."""
    try:
        count = len(os.sched_getaffinity(0))
    except (AttributeError, OSError):
        count = os.cpu_count() or 1
    return max(1, min(count, MAX_AUTO_WORKERS))


class SequentialExecutor:
    """Parse in the main process, preserving walk order."""

    def __init__(self, settings: TagsConfig) -> None:
        self._settings = settings

    def parse(self, items: Sequence[ParseItem]) -> Iterator[ParseResult]:
        for item in items:
            yield _parse_item(item, self._settings)

    def close(self, *, cancel: bool = False) -> None:
        """No resources to release."""


class ProcessExecutor:
    """Parse files in worker processes without touching the parent's DB."""

    def __init__(self, workers: int, settings: TagsConfig) -> None:
        self.workers = workers
        context = multiprocessing.get_context(
            "forkserver" if os.name == "posix" else "spawn"
        )
        self._pool = ProcessPoolExecutor(
            max_workers=workers,
            mp_context=context,
            initializer=_init_worker,
            initargs=(settings,),
        )

    def parse(self, items: Sequence[ParseItem]) -> Iterator[ParseResult]:
        for batch in self._pool.map(_parse_batch, batched(items, BATCH_SIZE)):
            yield from batch

    def close(self, *, cancel: bool = False) -> None:
        self._pool.shutdown(wait=not cancel, cancel_futures=cancel)


def make_executor(
    workers: int,
    pending: int,
    settings: TagsConfig,
) -> ParseExecutor:
    """Return a process pool for enough work, otherwise parse inline."""
    workers = max(1, min(workers, pending))
    if workers <= 1 or pending < MIN_PARALLEL_FILES:
        return SequentialExecutor(settings)
    return ProcessExecutor(workers, settings)
