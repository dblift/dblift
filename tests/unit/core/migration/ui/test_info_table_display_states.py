"""Info table State cells come from build_state() catalog labels.

Below baseline, Above target, Pending, and Outdated must be produced by
``MigrationStateManager.build_state()`` (via determine_state /
determine_pending_state), then copied into the collector ``state`` cell and
``TableRenderer`` text. Status is never hand-set on MigrationEntry.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from core.logger import NullLog
from core.migration.ui.data_collector import MigrationDataCollector
from core.migration.ui.table_renderer import TableRenderer
from tests.unit.core.migration.test_migration_state_manager_extended import (
    _mk_baseline,
    _mk_manager,
    _mk_repeatable,
    _mk_undo,
    _mk_versioned,
)

pytestmark = pytest.mark.unit


def _pipeline(mgr, scripts_dir, **build_kwargs):
    """build_state → collector rows → table text. No hand-set statuses."""
    state = mgr.build_state(scripts_dir, **build_kwargs)
    rows = MigrationDataCollector(NullLog())._get_migration_data_from_state(
        migration_state=state,
        all_applied_migrations=list(state.all_applied_objects),
        scripts_dir=scripts_dir,
    )
    table = TableRenderer(NullLog()).format_migration_table(rows)
    return state, rows, table


def _row_by_script(rows, script):
    matches = [row for row in rows if row["script"] == script]
    assert len(matches) == 1, f"expected one row for {script}, got {matches}"
    return matches[0]


def _catalog_mgr_and_dir():
    """Baseline 2 + on-disk V1 / V3 / V5 / U3, matching the Task 1 catalog fixture."""
    v1 = _mk_versioned("1")
    v3 = _mk_versioned("3")
    v5 = _mk_versioned("5")
    u3 = _mk_undo("3", rank=99)
    mgr = _mk_manager(applied=[_mk_baseline("2")], scripts=[v1, v3, v5, u3])
    tmp = tempfile.TemporaryDirectory()
    scripts_dir = Path(tmp.name)
    (scripts_dir / u3.script_name).write_text(u3.content)
    return mgr, scripts_dir, tmp, v1, v3, v5, u3


@pytest.mark.parametrize(
    "script_attr, expected",
    [
        ("v1", "Below baseline"),
        ("v3", "Pending"),
        ("v5", "Above target"),
    ],
    ids=["below_baseline", "pending", "above_target"],
)
def test_versioned_catalog_label_reaches_info_table(script_attr, expected):
    mgr, scripts_dir, tmp, v1, v3, v5, u3 = _catalog_mgr_and_dir()
    scripts = {"v1": v1, "v3": v3, "v5": v5}
    try:
        state, rows, table = _pipeline(mgr, scripts_dir, target_version="3")
        script = scripts[script_attr].script_name

        pending_by_script = {entry.script: entry.status for entry in state.pending}
        assert pending_by_script[script] == expected

        row = _row_by_script(rows, script)
        assert row["state"] == expected
        assert expected in table
    finally:
        tmp.cleanup()


def test_undo_sql_omitted_from_table_undoable_yes_for_companion():
    mgr, scripts_dir, tmp, v1, v3, v5, u3 = _catalog_mgr_and_dir()
    try:
        state, rows, table = _pipeline(mgr, scripts_dir, target_version="3")

        undo_status = {entry.script: entry.status for entry in state.pending}
        assert undo_status[u3.script_name] == "Available"

        scripts = [row["script"] for row in rows]
        assert u3.script_name not in scripts
        assert u3.script_name not in table

        pending_row = _row_by_script(rows, v3.script_name)
        assert pending_row["state"] == "Pending"
        assert pending_row["undoable"] is True
        assert "Yes" in table
    finally:
        tmp.cleanup()


def test_matching_numeric_checksum_applied_repeatable_is_success_not_outdated():
    """Applied R with the same CRC32 as the file is Success, even if history
    indexed the checksum as a string (the playground Outdated false positive).
    """
    applied = _mk_repeatable("R__report.sql", rank=1, checksum=732078983)
    on_disk = _mk_repeatable("R__report.sql", checksum=732078983)
    mgr = _mk_manager(applied=[applied], scripts=[on_disk])

    with tempfile.TemporaryDirectory() as tmp:
        scripts_dir = Path(tmp)
        (scripts_dir / on_disk.script_name).write_text(on_disk.content)
        state, rows, table = _pipeline(mgr, scripts_dir)

    assert [entry.status for entry in state.applied] == ["Success"]
    assert state.pending == []
    row = _row_by_script(rows, "R__report.sql")
    assert row["state"] == "Success"
    assert "Outdated" not in table


def test_outdated_applied_repeatable_and_pending_file_reach_info_table():
    """On-disk checksum change: applied row Outdated, pending file Pending."""
    applied = _mk_repeatable("R__data.sql", rank=1, checksum="old")
    on_disk = _mk_repeatable("R__data.sql", checksum="new")
    mgr = _mk_manager(applied=[applied], scripts=[on_disk])

    with tempfile.TemporaryDirectory() as tmp:
        scripts_dir = Path(tmp)
        (scripts_dir / on_disk.script_name).write_text(on_disk.content)
        state, rows, table = _pipeline(mgr, scripts_dir)

    assert [entry.status for entry in state.applied] == ["Outdated"]
    assert [entry.status for entry in state.pending] == ["Pending"]
    assert [entry.script for entry in state.pending] == ["R__data.sql"]

    # Collector lists applied first, then pending; both share the script name.
    named = [row for row in rows if row["script"] == "R__data.sql"]
    assert [row["state"] for row in named] == ["Outdated", "Pending"]
    assert "Outdated" in table
    assert "Pending" in table
