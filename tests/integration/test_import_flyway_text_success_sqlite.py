"""SQLite regression: a text ``success`` column keeps failed Flyway rows failed.

A hand-built Flyway table may declare ``success`` as TEXT holding ``'0'`` or
``'false'``. ``import-flyway`` used to truth-test those strings and record the
failed rows as successful in ``dblift_schema_history``. No Docker needed.
"""

import sqlite3

import pytest
from sqlalchemy import create_engine

from dblift.api import DBLiftClient

pytestmark = [pytest.mark.integration]


def test_import_flyway_text_success_column_keeps_failed_rows_failed(tmp_path):
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    db_file = tmp_path / "app.db"

    with sqlite3.connect(db_file) as conn:
        conn.execute("""CREATE TABLE flyway_schema_history (
            installed_rank INTEGER NOT NULL PRIMARY KEY, version TEXT,
            description TEXT NOT NULL, type TEXT NOT NULL, script TEXT NOT NULL,
            checksum INTEGER, installed_by TEXT NOT NULL,
            installed_on TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            execution_time INTEGER NOT NULL, success TEXT NOT NULL
        )""")
        conn.executemany(
            "INSERT INTO flyway_schema_history (installed_rank, version, description, type,"
            " script, checksum, installed_by, execution_time, success)"
            " VALUES (?, ?, ?, 'SQL', ?, 0, 'flyway', 1, ?)",
            [
                (1, "1", "ok", "V1__ok.sql", "1"),
                (2, "2", "failed zero", "V2__failed_zero.sql", "0"),
                (3, "3", "failed false", "V3__failed_false.sql", "false"),
            ],
        )

    engine = create_engine(f"sqlite:///{db_file}")
    client = DBLiftClient.from_sqlalchemy(engine, migrations_dir=migrations)
    try:
        result = client.import_flyway(flyway_table="flyway_schema_history")
        assert result.success, result.error_message
    finally:
        client.close()
        engine.dispose()

    with sqlite3.connect(db_file) as conn:
        imported = dict(
            conn.execute("SELECT version, success FROM dblift_schema_history").fetchall()
        )
    assert imported == {"1": 1, "2": 0, "3": 0}
