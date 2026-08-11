"""Baseline rows expose MigrationDisplayState-aligned status in collector output."""

import pytest

from core.logger import NullLog
from core.migration.migration import Migration
from core.migration.state.migration_state import MigrationEntry, MigrationState
from core.migration.ui.data_collector import MigrationDataCollector

pytestmark = pytest.mark.unit


def test_migration_data_from_state_successful_baseline_uses_baseline_state():
    collector = MigrationDataCollector(NullLog())
    baseline = Migration.create_baseline_migration(
        content="baseline",
        version="1.0.0",
        description="Production baseline",
    )
    baseline.success = True
    baseline.installed_rank = 1

    # applied/all_applied_objects mirror what MigrationStateManager.build_state()
    # produces: MigrationEntry.status is computed by MigrationStateService.
    state = MigrationState(
        pending_objects=[],
        all_applied_objects=[baseline],
        applied=[MigrationEntry.from_migration(baseline, status="Baseline")],
    )
    rows = collector._get_migration_data_from_state(
        migration_state=state,
        all_applied_migrations=[baseline],
        scripts_dir=None,
    )
    assert len(rows) == 1
    assert rows[0]["state"] == "Baseline"


