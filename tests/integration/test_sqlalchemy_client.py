"""Integration smoke test for DBLiftClient.from_sqlalchemy (SQLite file, no Docker)."""

import tempfile
from pathlib import Path

import pytest
from sqlalchemy import create_engine

from api import DBLiftClient


@pytest.mark.integration
def test_from_sqlalchemy_end_to_end_sqlite_file():
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        migrations = td / "migrations"
        migrations.mkdir()
        (migrations / "V1__init.sql").write_text(
            "CREATE TABLE app_users (id INTEGER PRIMARY KEY, name TEXT NOT NULL);"
        )

        db_file = td / "app.db"
        engine = create_engine(f"sqlite:///{db_file}")

        client = DBLiftClient.from_sqlalchemy(engine, migrations_dir=migrations)
        result = client.migrate()
        assert result.success
        assert len(getattr(result, "migrations_applied", [])) >= 1

        info = client.info()
        assert getattr(info, "pending_count", 0) == 0 or len(getattr(info, "pending", [])) == 0

        client.close()

        # App can still use the engine after client close (ownership retained by caller)
        with engine.connect() as conn:
            conn.exec_driver_sql("SELECT 1")
            # Data from migration is visible
            rows = conn.exec_driver_sql("SELECT COUNT(*) FROM app_users").scalar()
            assert rows == 0  # table exists, empty
