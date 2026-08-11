"""Applied migrations whose script file no longer exists on disk show as
Missing (or Failed missing) in the state-based data collector path, the way
Flyway reports missing migrations, without info calling validate."""

import pytest

from core.logger import NullLog
from core.migration.migration import Migration, MigrationType
from core.migration.state.migration_state import MigrationEntry, MigrationState
from core.migration.state.migration_state_service import MigrationStateService
from core.migration.ui.data_collector import MigrationDataCollector

pytestmark = pytest.mark.unit


def _mk_versioned(version, rank, script_name=None, success=True, resolved=True):
    m = Migration(
        script_name=script_name or f"V{version}__test.sql",
        content="SELECT 1;",
        version=version,
        description="Test",
        type=MigrationType.SQL,
    )
    m.success = success
    m.installed_rank = rank
    m.resolved = resolved
    return m


def _build_state(applied_migrations, current_version=None, undone_versions=None):
    """Build a MigrationState the way MigrationStateManager.build_state() does:
    .applied entries carry the status MigrationStateService.determine_state()
    computes, so the collector can look status up instead of re-deriving it.
    """
    context = {
        "undone_versions": set(undone_versions or []),
        "out_of_order_migrations": set(),
        "repeatable_checksums": {},
        "reapplied_versions": set(),
        "current_version": current_version,
    }
    service = MigrationStateService(NullLog())
    entries = [
        MigrationEntry.from_migration(m, status=service.determine_state(m, context).value)
        for m in applied_migrations
    ]
    return MigrationState(
        current_version=current_version,
        undone_versions=sorted(context["undone_versions"]),
        pending_objects=[],
        all_applied_objects=applied_migrations,
        applied=entries,
    )


def _build_pending_state(pending_migrations, scripts_dir=None, baseline_version=None, target_version=None):
    """Same idea as _build_state, but for pending entries via
    MigrationStateService.determine_pending_state()."""
    context = {
        "baseline_version": baseline_version,
        "target_version": target_version,
        "scripts_dir": scripts_dir,
    }
    service = MigrationStateService(NullLog())
    entries = [
        MigrationEntry.from_migration(m, status=service.determine_pending_state(m, context).value)
        for m in pending_migrations
    ]
    return MigrationState(pending_objects=pending_migrations, pending=entries)


def test_applied_migration_with_deleted_script_shows_missing():
    """V3's script was applied but its file is gone; only V1-V2 remain on
    disk and nothing is pending — V3 must render as Missing."""
    collector = MigrationDataCollector(NullLog())
    v1 = _mk_versioned("1", rank=1, resolved=True)
    v2 = _mk_versioned("2", rank=2, resolved=True)
    v3 = _mk_versioned("3", rank=3, resolved=False)

    state = _build_state([v1, v2, v3], current_version="3")
    rows = collector._get_migration_data_from_state(
        migration_state=state,
        all_applied_migrations=[v1, v2, v3],
        scripts_dir=None,
    )

    by_version = {row["version"]: row for row in rows}
    assert by_version["1"]["state"] == "Success"
    assert by_version["2"]["state"] == "Success"
    assert by_version["3"]["state"] == "Missing"


def test_failed_applied_migration_with_deleted_script_shows_failed_missing():
    collector = MigrationDataCollector(NullLog())
    v1 = _mk_versioned("1", rank=1, success=False, resolved=False)

    state = _build_state([v1], current_version=None)
    rows = collector._get_migration_data_from_state(
        migration_state=state,
        all_applied_migrations=[v1],
        scripts_dir=None,
    )

    assert rows[0]["state"] == "Failed missing"


def test_applied_migrations_with_scripts_still_present_stay_success():
    """Regression guard for the _mark_resolved_status bug: applied migrations
    whose scripts are still on disk (and nothing is currently pending) must
    not be reported as Missing."""
    collector = MigrationDataCollector(NullLog())
    v1 = _mk_versioned("1", rank=1, resolved=True)
    v2 = _mk_versioned("2", rank=2, resolved=True)

    state = _build_state([v1, v2], current_version="2")
    rows = collector._get_migration_data_from_state(
        migration_state=state,
        all_applied_migrations=[v1, v2],
        scripts_dir=None,
    )

    assert [row["state"] for row in rows] == ["Success", "Success"]


def test_unresolved_future_version_shows_future():
    """An unresolved applied migration whose version is higher than the
    current schema version renders as Future (e.g. after undo of the
    current head), not plain Missing."""
    collector = MigrationDataCollector(NullLog())
    v5 = _mk_versioned("5", rank=1, resolved=False)

    state = _build_state([v5], current_version="3")
    rows = collector._get_migration_data_from_state(
        migration_state=state,
        all_applied_migrations=[v5],
        scripts_dir=None,
    )

    assert rows[0]["state"] == "Future"


def test_undone_migration_still_detected_with_resolved_scripts():
    """Regression guard: inserting the resolved-check ahead of the UNDONE
    lookahead must not break UNDONE detection for migrations whose scripts
    are still present."""
    collector = MigrationDataCollector(NullLog())
    sql = _mk_versioned("1", rank=1, resolved=True)
    undo = Migration(
        script_name="U1__test.sql",
        content="SELECT 1;",
        version="1",
        description="Undo",
        type=MigrationType.UNDO_SQL,
    )
    undo.success = True
    undo.installed_rank = 2

    state = _build_state([sql, undo], current_version=None, undone_versions=["1"])
    rows = collector._get_migration_data_from_state(
        migration_state=state,
        all_applied_migrations=[sql, undo],
        scripts_dir=None,
    )

    sql_row = next(row for row in rows if row["version"] == "1" and row["type"] != "UNDO_SQL")
    assert sql_row["state"] == "Undone"


def test_pending_migration_with_undo_script_shows_available():
    """Regression guard: _determine_pending_migration_status used to be a
    stub that always returned PENDING, so a pending versioned migration with
    an undo companion script on disk rendered as Pending instead of
    Available. The collector must now surface MigrationStateService's
    determine_pending_state() result instead."""
    import tempfile
    from pathlib import Path

    collector = MigrationDataCollector(NullLog())
    pending = Migration(
        script_name="V2__test.sql",
        content="SELECT 1;",
        version="2",
        description="Test",
        type=MigrationType.SQL,
    )
    pending.success = None

    with tempfile.TemporaryDirectory() as tmpdir:
        scripts_dir = Path(tmpdir)
        (scripts_dir / "U2__undo.sql").write_text("SELECT 1;", encoding="utf-8")

        state = _build_pending_state([pending], scripts_dir=scripts_dir)
        rows = collector._get_migration_data_from_state(
            migration_state=state,
            all_applied_migrations=[],
            scripts_dir=scripts_dir,
        )

    assert rows[0]["state"] == "Available"
