import re
import sqlite3
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from genplis.config import Config
from genplis.core import Args
from genplis.db import (
    create_files_table,
    setup_database_connection,
)
from genplis.types import Verbosity


@pytest.fixture(scope="session")
def file_mp3() -> Path:
    return (Path(__file__).parent / "files" / "test.mp3").absolute()


@pytest.fixture(scope="session")
def file_ogg() -> Path:
    return (Path(__file__).parent / "files" / "test.ogg").absolute()


@pytest.fixture(scope="session")
def file_m3ug() -> Path:
    return (Path(__file__).parent / "files" / "test.m3ug").absolute()


@pytest.fixture()
def genplis_db(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    db_path = tmp_path / "genplis.db"
    conn, cursor = setup_database_connection(db_path)
    create_files_table(cursor)
    try:
        yield conn
    finally:
        conn.close()


@pytest.fixture()
def make_args() -> Callable[..., Args]:
    def _make_args(
        path_str: str,
        exclude: list[re.Pattern[str]] | None = None,
        verbosity: Verbosity = Verbosity.NORMAL,
        overwrite: bool = True,
        config: Config | None = None,
        db_path: Path | None = None,
        include_source: bool = True,
        extended_m3u: bool = True,
        clean: bool = False,
        jobs: int = 1,
    ) -> Args:
        return Args(
            path=Path(path_str),
            exclude=tuple(exclude) if exclude is not None else (),
            verbosity=verbosity,
            overwrite=overwrite,
            db_path=db_path if db_path is not None else Path("genplis.db"),
            config=config if config is not None else Config(),
            include_source=include_source,
            extended_m3u=extended_m3u,
            clean=clean,
            jobs=jobs,
        )

    return _make_args
