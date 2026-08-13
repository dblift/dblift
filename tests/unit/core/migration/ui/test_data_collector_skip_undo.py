"""Info table skips UNDO_SQL rows (Flyway removeUndos); Undoable stays."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from core.logger import NullLog
from core.migration.migration import MigrationType
from core.migration.state.migration_state import MigrationEntry, MigrationState
from core.migration.ui.data_collector import MigrationDataCollector

pytestmark = pytest.mark.unit


def _make_migration(version, *, mtype=MigrationType.SQL, script_name=None, rank=1):
    m = MagicMock()
    m.version = version
    m.type = mtype
    m.success = True
    m.installed_rank = rank
    m.script_name = script_name or f"V{version}__test.sql"
    m.checksum = "csum"
    m.description = "test"
    m.installed_by = "ci"
    m.installed_on = None
    m.execution_time = 100
    m.filepath = ""
    return m


def test_skips_pending_undo_sql_rows_and_keeps_undoable_from_companion():
    versioned = _make_migration("2", script_name="V2__test.sql")
    undo = _make_migration("2", mtype=MigrationType.UNDO_SQL, script_name="U2__undo.sql")
    state = MigrationState(
        pending_objects=[versioned, undo],
        pending=[
            MigrationEntry.from_migration(versioned, status="Pending"),
            MigrationEntry.from_migration(undo, status="Available"),
        ],
    )
    collector = MigrationDataCollector(NullLog())
    collector._find_undo_versions = lambda scripts_dir: {"2"}  # type: ignore[method-assign]

    rows = collector._get_migration_data_from_state(
        migration_state=state,
        all_applied_migrations=[],
    )

    scripts = [row["script"] for row in rows]
    assert "U2__undo.sql" not in scripts
    assert "V2__test.sql" in scripts
    versioned_row = next(row for row in rows if row["script"] == "V2__test.sql")
    assert versioned_row["state"] == "Pending"
    assert versioned_row["undoable"] is True


def test_skips_applied_undo_sql_rows():
    sql = _make_migration("1", script_name="V1__test.sql", rank=1)
    undo = _make_migration("1", mtype=MigrationType.UNDO_SQL, script_name="U1__undo.sql", rank=2)
    state = MigrationState(
        all_applied_objects=[sql, undo],
        applied=[
            MigrationEntry.from_migration(sql, status="Undone"),
            MigrationEntry.from_migration(undo, status="Success"),
        ],
    )
    collector = MigrationDataCollector(NullLog())

    rows = collector._get_migration_data_from_state(
        migration_state=state,
        all_applied_migrations=[sql, undo],
    )

    scripts = [row["script"] for row in rows]
    assert "U1__undo.sql" not in scripts
    assert "V1__test.sql" in scripts
    sql_row = next(row for row in rows if row["script"] == "V1__test.sql")
    assert sql_row["state"] == "Undone"
