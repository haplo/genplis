import argparse
import re
import sqlite3
from collections.abc import Callable
from pathlib import Path

import pytest

from genplis.db import (
    create_files_table,
    setup_database_connection,
)


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
def genplis_db(tmp_path: Path) -> sqlite3.Connection:
    db_path = tmp_path / "genplis.db"
    conn, cursor = setup_database_connection(db_path)
    create_files_table(cursor)
    return conn


@pytest.fixture()
def make_args() -> Callable[..., argparse.Namespace]:
    def _make_args(
        path_str: str,
        exclude: list[re.Pattern[str]] | None = None,
        verbose: bool = False,
    ) -> argparse.Namespace:
        return argparse.Namespace(
            path=Path(path_str),
            exclude=exclude if exclude is not None else [],
            verbose=verbose,
        )

    return _make_args
