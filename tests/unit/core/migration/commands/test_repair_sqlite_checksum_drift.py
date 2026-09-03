"""``repair`` must clear checksum drift on SQLite, end to end.

Editing an applied script changes its filesystem checksum, so ``validate``
reports a modified migration. ``repair`` exists to rewrite the stored checksum
so validation passes again. On SQLite it did not: the provider had no
``repair_migration_history``, ``MigrationHistoryManager.repair_checksum``
swallowed the ``AttributeError`` and returned ``False``, and the command
reported "Repair may require manual intervention" while the row was unchanged.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from sqlalchemy import create_engine

from dblift.api import DBLiftClient

pytestmark = [pytest.mark.unit, pytest.mark.sqlite]


def _client(db: Path, migrations: Path) -> DBLiftClient:
    return DBLiftClient.from_sqlalchemy(
        create_engine(f"sqlite:///{db}"), migrations_dir=str(migrations)
    )


def _stored_checksum(db: Path, script: str) -> str:
    with sqlite3.connect(db) as conn:
        row = conn.execute(
            "SELECT checksum FROM dblift_schema_history WHERE script = ?", (script,)
        ).fetchone()
    return str(row[0])


def test_repair_fixes_checksum_drift_and_validate_passes(tmp_path: Path) -> None:
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    script = migrations / "V1_0_0__a.sql"
    script.write_text("CREATE TABLE a (id INTEGER PRIMARY KEY);")
    db = tmp_path / "db.sqlite"

    _client(db, migrations).migrate()
    applied_checksum = _stored_checksum(db, "V1_0_0__a.sql")

    # Genuine content drift: the file changes, the stored checksum does not.
    script.write_text("CREATE TABLE a (id INTEGER PRIMARY KEY);\n-- edited after apply\n")

    assert _client(db, migrations).validate().success is False

    assert _client(db, migrations).repair().success is True
    assert _stored_checksum(db, "V1_0_0__a.sql") != applied_checksum

    assert _client(db, migrations).validate().success is True
