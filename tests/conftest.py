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


@pytest.fixture()
def genplis_db(tmp_path):
    db_path = tmp_path / "genplis.db"
    conn, cursor = setup_database_connection(db_path)
    create_files_table(cursor)
    return conn
