import argparse
from pathlib import Path

import pytest

from genplis.db import (
    create_files_table,
    setup_database_connection,
)


@pytest.fixture(scope="session")
def file_mp3():
    return (Path(__file__).parent / "files" / "test.mp3").absolute()


@pytest.fixture(scope="session")
def file_ogg():
    return (Path(__file__).parent / "files" / "test.ogg").absolute()


@pytest.fixture(scope="session")
def file_m3ug():
    return (Path(__file__).parent / "files" / "test.m3ug").absolute()


@pytest.fixture()
def genplis_db(tmp_path):
    db_path = tmp_path / "genplis.db"
    conn, cursor = setup_database_connection(db_path)
    create_files_table(cursor)
    return conn


@pytest.fixture()
def make_args():
    def _make_args(path_str, exclude=None, verbose=False):
        return argparse.Namespace(
            path=Path(path_str),
            exclude=exclude if exclude is not None else [],
            verbose=verbose,
        )

    return _make_args
