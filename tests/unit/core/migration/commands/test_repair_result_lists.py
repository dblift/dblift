"""Repair reports the rows it would touch on a dry run and the rows it touched."""

from __future__ import annotations

import sqlite3

import pytest
from sqlalchemy import create_engine

from dblift.api import DBLiftClient

pytestmark = [pytest.mark.unit, pytest.mark.sqlite]


def _history(database):
    with sqlite3.connect(database) as connection:
        return connection.execute(
            "SELECT script, checksum, success, type FROM dblift_schema_history "
            "ORDER BY installed_rank"
        ).fetchall()


@pytest.fixture
def damaged_history(tmp_path):
    """History with one checksum mismatch (V1), one missing script (V2), one failed row (V3)."""
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    database = tmp_path / "app.db"
    engine = create_engine(f"sqlite:///{database}")
    client = DBLiftClient.from_sqlalchemy(engine, migrations_dir=str(migrations))
    (migrations / "V1__edited.sql").write_text("CREATE TABLE edited (id INTEGER);\n")
    (migrations / "V2__gone.sql").write_text("CREATE TABLE gone (id INTEGER);\n")
    (migrations / "V3__broken.sql").write_text("CREATE TABLE broken (id INTEGER);\n")
    try:
        assert client.migrate().success
        (migrations / "V1__edited.sql").write_text("CREATE TABLE edited (id INTEGER);\n-- edit\n")
        (migrations / "V2__gone.sql").unlink()
        with sqlite3.connect(database) as connection:
            connection.execute(
                "UPDATE dblift_schema_history SET success = 0 WHERE script = 'V3__broken.sql'"
            )
        yield client, database
    finally:
        client.close()
        engine.dispose()


def _assert_lists(result):
    assert result.success, result.error_message
    assert [(m.script, m.version, m.description, m.status) for m in result.aligned_migrations] == [
        ("V1__edited.sql", "1", "edited", "SUCCESS")
    ]
    assert [(m.script, m.version, m.description, m.status) for m in result.repaired_migrations] == [
        ("V2__gone.sql", "2", "gone", "MISSING")
    ]
    assert [(m.script, m.version, m.description, m.status) for m in result.removed_migrations] == [
        ("V3__broken.sql", "3", "broken", "FAILED")
    ]
    assert result.checksums_fixed == 1
    assert result.deleted_migrations_marked == 1
    assert result.failed_migrations_removed == 1


def test_dry_run_reports_the_repairs_it_would_make(damaged_history):
    client, database = damaged_history
    before = _history(database)

    result = client.repair(dry_run=True)

    _assert_lists(result)
    assert _history(database) == before


def test_repair_reports_the_repairs_it_made(damaged_history):
    client, database = damaged_history
    before = _history(database)

    result = client.repair()

    _assert_lists(result)
    after = _history(database)
    assert "V3__broken.sql" not in [row[0] for row in after]
    v1_before = next(row for row in before if row[0] == "V1__edited.sql")
    v1_after = next(row for row in after if row[0] == "V1__edited.sql")
    assert v1_after[1] != v1_before[1]
    assert ("V2__gone.sql", "DELETE") in [(row[0], row[3]) for row in after]
    assert client.validate().success
