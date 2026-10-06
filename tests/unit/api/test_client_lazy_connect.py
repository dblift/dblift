"""Entering the client context does not open a database connection."""

import pytest

from dblift.api.client import DBLiftClient


def _config(tmp_path, db_path):
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    (migrations / "V1__init.sql").write_text("CREATE TABLE t (id INTEGER PRIMARY KEY);\n")
    config = tmp_path / "dblift.yaml"
    config.write_text(
        f"database:\n  type: sqlite\n  path: {db_path}\nmigrations:\n  directory: {migrations}\n"
    )
    return config


@pytest.mark.unit
def test_enter_does_not_create_the_database_file(tmp_path):
    db_path = tmp_path / "missing" / "app.db"
    config = _config(tmp_path, db_path)

    with DBLiftClient.from_config_file(str(config)) as client:
        assert not db_path.exists()
        assert client.migrate().success

    assert db_path.exists()
