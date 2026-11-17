"""A real (not dry-run) undo with ``show_sql`` reports the SQL of each undo script it runs."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import create_engine

from dblift.api import DBLiftClient

pytestmark = [pytest.mark.unit, pytest.mark.sqlite]


def test_undo_with_show_sql_records_each_undo_script_it_runs(tmp_path: Path):
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    (migrations / "V1__create_a.sql").write_text("CREATE TABLE a (id INTEGER PRIMARY KEY);")
    (migrations / "U1__drop_a.sql").write_text("DROP TABLE a;")
    client = DBLiftClient.from_sqlalchemy(
        create_engine(f"sqlite:///{tmp_path / 'app.db'}"), migrations_dir=str(migrations)
    )
    try:
        assert client.migrate().success

        result = client.undo(show_sql=True)
    finally:
        client.close()

    assert result.success, result.error_message
    assert [(info.script, info.statements) for info in result.sql] == [
        ("U1__drop_a.sql", ["DROP TABLE a"])
    ]
    assert [m.script for m in result.undone_migrations] == ["U1__drop_a.sql"]
