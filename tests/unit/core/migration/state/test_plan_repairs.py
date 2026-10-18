"""``MigrationStateManager.plan_repairs`` decides what repair fixes."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Optional
from unittest.mock import MagicMock

import pytest

from dblift.core.migration.migration import MigrationType
from dblift.core.migration.state.checksum_drift import ChecksumDrift
from dblift.core.migration.state.migration_state import MigrationState
from dblift.core.migration.state.migration_state_manager import MigrationStateManager
from dblift.core.migration.state.repair_plan import (
    RepairAction,
    RepairPlan,
    RepairSafetyError,
    _count_candidate_missing,
)

pytestmark = pytest.mark.unit


def _applied(script_name: str, version: str = "1", type_=MigrationType.SQL) -> SimpleNamespace:
    return SimpleNamespace(
        script_name=script_name, version=version, description="d", type=type_, checksum=1
    )


def _failed(script_name: str, version: Optional[str] = "1") -> SimpleNamespace:
    return SimpleNamespace(script_name=script_name, version=version, description="f")


def _on_disk(*script_names: str) -> dict:
    return {MigrationType.SQL: [SimpleNamespace(script_name=name) for name in script_names]}


def _plan(state: MigrationState, **overrides) -> RepairPlan:
    manager = MigrationStateManager(MagicMock(), MagicMock(), MagicMock(), MagicMock())
    manager.build_state = MagicMock(return_value=state)
    manager.get_grouped_migrations = MagicMock(return_value=overrides.pop("catalog", {}))
    kwargs = dict(recursive=True, additional_dirs=None, dir_recursive_map=None)
    kwargs.update(overrides)
    return manager.plan_repairs(Path("/migrations"), **kwargs)


def _kinds(plan: RepairPlan):
    return [(action.kind, action.script) for action in plan.actions]


class TestPlanRepairsKinds:
    def test_no_issue_plans_nothing_and_keeps_the_state(self):
        state = MigrationState(grouped_objects=_on_disk("V1__a.sql"))
        state.applied_objects = [_applied("V1__a.sql")]

        plan = _plan(state)

        assert plan.actions == ()
        assert plan.state is state

    def test_repeatable_checksum_change(self):
        state = MigrationState(grouped_objects=_on_disk("R__x.sql"))
        state.checksum_changes = [
            SimpleNamespace(script_name="R__x.sql", previous_checksum=1, current_checksum=2)
        ]

        plan = _plan(state)

        assert plan.actions == (
            RepairAction(
                kind="CHECKSUM_MISMATCH",
                script="R__x.sql",
                details={
                    "type": "CHECKSUM_MISMATCH",
                    "script": "R__x.sql",
                    "old_checksum": 1,
                    "new_checksum": 2,
                },
            ),
        )

    def test_versioned_checksum_drift(self):
        state = MigrationState(
            grouped_objects=_on_disk("V1__a.sql"),
            checksum_drift=(ChecksumDrift("V1__a.sql", 100, 200, False),),
        )

        plan = _plan(state)

        assert plan.actions == (
            RepairAction(
                kind="CHECKSUM_MISMATCH",
                script="V1__a.sql",
                details={
                    "type": "CHECKSUM_MISMATCH",
                    "script": "V1__a.sql",
                    "old_checksum": 100,
                    "new_checksum": 200,
                },
            ),
        )

    def test_missing_script_keeps_the_original_type(self):
        state = MigrationState(grouped_objects=_on_disk("V1__a.sql"))
        state.applied_objects = [_applied("V1__a.sql"), _applied("V2__gone.sql", "2")]

        plan = _plan(state)

        assert plan.actions == (
            RepairAction(
                kind="MISSING_SCRIPT",
                script="V2__gone.sql",
                details={
                    "type": "MISSING_SCRIPT",
                    "script": "V2__gone.sql",
                    "version": "2",
                    "description": "d",
                    "original_type": MigrationType.SQL,
                },
            ),
        )

    def test_failed_migration(self):
        state = MigrationState(grouped_objects=_on_disk("V1__a.sql"))
        state.failed_objects = [_failed("V1__a.sql")]

        plan = _plan(state)

        assert plan.actions == (
            RepairAction(
                kind="FAILED_MIGRATION",
                script="V1__a.sql",
                details={
                    "type": "FAILED_MIGRATION",
                    "script": "V1__a.sql",
                    "version": "1",
                    "description": "f",
                },
            ),
        )

    def test_actions_follow_detection_order(self):
        state = MigrationState(
            grouped_objects=_on_disk("R__x.sql", "V1__a.sql", "V3__c.sql"),
            checksum_drift=(ChecksumDrift("V3__c.sql", 1, 2, False),),
        )
        state.checksum_changes = [
            SimpleNamespace(script_name="R__x.sql", previous_checksum=1, current_checksum=2)
        ]
        state.applied_objects = [_applied("V2__gone.sql", "2")]
        state.failed_objects = [_failed("V1__a.sql")]

        plan = _plan(state)

        assert _kinds(plan) == [
            ("CHECKSUM_MISMATCH", "R__x.sql"),
            ("MISSING_SCRIPT", "V2__gone.sql"),
            ("FAILED_MIGRATION", "V1__a.sql"),
            ("CHECKSUM_MISMATCH", "V3__c.sql"),
        ]

    def test_drift_on_a_script_already_planned_is_not_repeated(self):
        state = MigrationState(
            grouped_objects=_on_disk("V1__a.sql"),
            checksum_drift=(ChecksumDrift("V1__a.sql", 1, 2, False),),
        )
        state.failed_objects = [_failed("V1__a.sql")]

        plan = _plan(state)

        assert _kinds(plan) == [("FAILED_MIGRATION", "V1__a.sql")]

    def test_state_without_a_catalog_is_rebuilt_for_drift(self):
        bare = MigrationState()
        built = MigrationState(
            grouped_objects=_on_disk("V1__a.sql"),
            checksum_drift=(ChecksumDrift("V1__a.sql", 1, 2, False),),
        )
        manager = MigrationStateManager(MagicMock(), MagicMock(), MagicMock(), MagicMock())
        manager.build_state = MagicMock(side_effect=[bare, built])
        manager.get_grouped_migrations = MagicMock(return_value=_on_disk("V1__a.sql"))

        plan = manager.plan_repairs(
            Path("/migrations"), recursive=True, additional_dirs=None, dir_recursive_map=None
        )

        assert plan.state is bare
        assert _kinds(plan) == [("CHECKSUM_MISMATCH", "V1__a.sql")]


class TestFailedRowRouting:
    def test_checksum_repair_on_a_failed_row_becomes_a_removal(self):
        state = MigrationState(grouped_objects=_on_disk("R__x.sql"))
        state.checksum_changes = [
            SimpleNamespace(script_name="R__x.sql", previous_checksum=1, current_checksum=2)
        ]
        state.failed_objects = [_failed("R__x.sql", None)]

        plan = _plan(state)

        assert _kinds(plan) == [("FAILED_MIGRATION", "R__x.sql")]
        # The action carries the detected repair as found.
        assert plan.actions[0].details["type"] == "CHECKSUM_MISMATCH"
        assert plan.actions[0].details["new_checksum"] == 2

    def test_a_failed_row_is_removed_once(self):
        state = MigrationState(grouped_objects=_on_disk("R__x.sql"))
        state.checksum_changes = [
            SimpleNamespace(script_name="R__x.sql", previous_checksum=1, current_checksum=2)
        ]
        state.failed_objects = [_failed("R__x.sql", None), _failed("R__x.sql", None)]

        plan = _plan(state)

        assert _kinds(plan) == [("FAILED_MIGRATION", "R__x.sql")]

    def test_checksum_repair_on_another_script_is_not_rerouted(self):
        state = MigrationState(grouped_objects=_on_disk("R__x.sql", "V1__a.sql"))
        state.checksum_changes = [
            SimpleNamespace(script_name="R__x.sql", previous_checksum=1, current_checksum=2)
        ]
        state.failed_objects = [_failed("V1__a.sql")]

        plan = _plan(state)

        assert _kinds(plan) == [
            ("CHECKSUM_MISMATCH", "R__x.sql"),
            ("FAILED_MIGRATION", "V1__a.sql"),
        ]


class TestMissingScripts:
    def test_legacy_directory_qualified_row_is_not_missing(self):
        state = MigrationState(grouped_objects=_on_disk("V1__a.sql"))
        state.applied_objects = [_applied("sub/dir/V1__a.sql")]

        assert _plan(state).actions == ()

    @pytest.mark.parametrize("type_", ["DELETE", "BASELINE"])
    def test_delete_and_baseline_rows_are_not_missing(self, type_):
        state = MigrationState(grouped_objects=_on_disk("V1__a.sql"))
        state.applied_objects = [_applied("V9__x.sql", "9", SimpleNamespace(name=type_))]

        assert _plan(state).actions == ()

    def test_already_deleted_script_is_not_missing(self):
        state = MigrationState(
            grouped_objects=_on_disk("V1__a.sql"), deleted_scripts=["V2__gone.sql"]
        )
        state.applied_objects = [_applied("V2__gone.sql", "2")]

        assert _plan(state).actions == ()

    def test_catalog_comes_from_the_manager_when_the_state_has_none(self):
        state = MigrationState()
        state.applied_objects = [_applied("V1__a.sql"), _applied("V2__gone.sql", "2")]

        plan = _plan(state, catalog=_on_disk("V1__a.sql"))

        # The drift pass then rebuilds the bare state; the mock hands the same one back.
        assert _kinds(plan) == [("MISSING_SCRIPT", "V2__gone.sql")]

    def test_zero_scripts_with_applied_history_is_refused(self):
        state = MigrationState(grouped_objects={})
        state.applied_objects = [_applied("V1__a.sql"), _applied("V2__b.sql", "2")]

        with pytest.raises(RepairSafetyError) as raised:
            _plan(state)

        assert str(raised.value) == (
            "Refusing to mark 2 applied migration(s) as missing: no migration scripts "
            "found in /migrations. Pass --scripts <dir> pointing to your migration files, "
            "or verify that the configured directory contains at least one matching file "
            "before retrying."
        )

    def test_zero_scripts_with_empty_history_plans_nothing(self):
        assert _plan(MigrationState(grouped_objects={})).actions == ()

    def test_load_failure_propagates(self):
        state = MigrationState()
        state.applied_objects = [_applied("V1__a.sql")]
        manager = MigrationStateManager(MagicMock(), MagicMock(), MagicMock(), MagicMock())
        manager.build_state = MagicMock(return_value=state)
        manager.get_grouped_migrations = MagicMock(side_effect=PermissionError("unreadable"))

        with pytest.raises(PermissionError, match="unreadable"):
            manager.plan_repairs(
                Path("/migrations"), recursive=True, additional_dirs=None, dir_recursive_map=None
            )


class TestPlanReads:
    def test_build_failure_propagates(self):
        manager = MigrationStateManager(MagicMock(), MagicMock(), MagicMock(), MagicMock())
        manager.build_state = MagicMock(side_effect=RuntimeError("history read failed"))

        with pytest.raises(RuntimeError, match="history read failed"):
            manager.plan_repairs(
                Path("/migrations"), recursive=True, additional_dirs=None, dir_recursive_map=None
            )

    def test_scan_options_and_snapshot_reach_the_state_build(self):
        manager = MigrationStateManager(MagicMock(), MagicMock(), MagicMock(), MagicMock())
        manager.build_state = MagicMock(return_value=MigrationState(grouped_objects={}))
        snapshot = MagicMock()
        extra = [Path("/extra")]
        recursive_map = {Path("/extra"): True}

        manager.plan_repairs(
            Path("/migrations"),
            recursive=False,
            additional_dirs=extra,
            dir_recursive_map=recursive_map,
            read_snapshot=snapshot,
        )

        manager.build_state.assert_called_once_with(
            Path("/migrations"),
            recursive=False,
            additional_dirs=extra,
            dir_recursive_map=recursive_map,
            read_snapshot=snapshot,
        )


def test_count_candidate_missing_skips_deleted_baseline_and_nameless_rows():
    applied = [
        _applied("V1__a.sql"),
        _applied("V2__b.sql", "2", SimpleNamespace(name="DELETE")),
        _applied("B3__c.sql", "3", "BASELINE"),
        _applied("V4__d.sql", "4"),
        SimpleNamespace(script_name="", version="5", type=None),
    ]

    assert _count_candidate_missing(applied, {"V4__d.sql"}) == 1
