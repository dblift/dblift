"""``SQLiteProvider.repair_migration_history`` must exist and update the row.

``MigrationHistoryManager.repair_checksum`` calls
``provider.repair_migration_history(...)``. Every other plugin implements it;
SQLite did not, so ``repair`` failed with ``'SQLiteProvider' object has no
attribute 'repair_migration_history'`` and the drifted checksum was left
untouched.

The expectations mirror the PostgreSQL/MySQL/DuckDB implementations: a matched
row returns ``True``, a missing row or missing history table returns ``False``,
and ``success_value=None`` leaves the stored ``success`` flag alone.
"""

from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path
from typing import Any, Dict, Iterator

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.sqlite]


@pytest.fixture()
def provider() -> Iterator[Any]:
    from dblift.config import DbliftConfig
    from dblift.db.plugins.sqlite.config import SQLiteConfig
    from dblift.db.plugins.sqlite.provider import SQLiteProvider

    tmp = Path(tempfile.mkdtemp())
    p = SQLiteProvider(
        DbliftConfig(
            database=SQLiteConfig(type="sqlite", path=str(tmp / "repair.sqlite"), schema="main")
        )
    )
    p.create_connection()
    yield p
    p.close()


def _record(provider: Any, script: str, checksum: str, success: bool = True) -> None:
    provider.record_migration(
        "main",
        {
            "version": "1",
            "description": "d",
            "type": "SQL",
            "script": script,
            "checksum": checksum,
            "execution_time": 1,
            "success": success,
        },
    )


def _row(provider: Any, script: str) -> Dict[str, Any]:
    rows = provider.execute_query(
        'SELECT checksum, success FROM "dblift_schema_history" WHERE script = ?', [script]
    )
    return rows[0]


class TestSqliteRepairMigrationHistory:
    def test_updates_checksum_and_marks_success(self, provider: Any) -> None:
        _record(provider, "V1__a.sql", "111", success=False)

        assert provider.repair_migration_history("main", "V1__a.sql", "222", success_value=True)

        row = _row(provider, "V1__a.sql")
        assert str(row["checksum"]) == "222"
        assert row["success"] in (1, True)

    def test_returns_false_when_script_not_in_history(self, provider: Any) -> None:
        _record(provider, "V1__a.sql", "111")

        assert (
            provider.repair_migration_history("main", "V2__missing.sql", "222", success_value=True)
            is False
        )

    def test_returns_false_when_history_table_missing(self, provider: Any) -> None:
        _record(provider, "V1__a.sql", "111")

        assert (
            provider.repair_migration_history(
                "main", "V1__a.sql", "222", table_name="no_such_table"
            )
            is False
        )

    def test_none_success_value_preserves_stored_success(self, provider: Any) -> None:
        """Matches PostgreSQL/MySQL/DuckDB: ``COALESCE(?, success)``."""
        _record(provider, "V1__a.sql", "111", success=False)

        assert provider.repair_migration_history("main", "V1__a.sql", "222") is True

        row = _row(provider, "V1__a.sql")
        assert str(row["checksum"]) == "222"
        assert row["success"] in (0, False)

    def test_change_is_persisted_to_disk(self, provider: Any) -> None:
        """The repaired checksum must survive the connection, not just the cursor."""
        _record(provider, "V1__a.sql", "111")

        assert provider.repair_migration_history("main", "V1__a.sql", "222", success_value=True)
        db_path = provider.connection_manager.db_path
        provider.close()

        with sqlite3.connect(db_path) as raw:
            stored = raw.execute(
                'SELECT checksum FROM "dblift_schema_history" WHERE script = ?', ["V1__a.sql"]
            ).fetchone()
        assert str(stored[0]) == "222"
