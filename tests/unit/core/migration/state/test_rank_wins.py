"""Shared undo/reapply latest-rank-wins helper.

Guards two regressions: (1) undone-then-reapplied rows resolve to the latest
rank, and (2) the four former copies cannot drift — they must call
``latest_successful_ranks``.
"""

from __future__ import annotations

import inspect
from types import SimpleNamespace

import pytest

from dblift.core.migration.migration import MigrationType
from dblift.core.migration.state.rank_wins import latest_successful_ranks

pytestmark = [pytest.mark.unit]


def _row(version, mtype, rank, success=True):
    return SimpleNamespace(version=version, type=mtype, installed_rank=rank, success=success)


class TestLatestSuccessfulRanks:
    def test_undone_then_reapplied_latest_rank_wins(self):
        rows = [
            _row("1", "SQL", 1),
            _row("1", "UNDO_SQL", 2),
            _row("1", "SQL", 3),
        ]

        state = latest_successful_ranks(rows)["1"]

        assert state.versioned == 3
        assert state.undo == 2
        assert state.reapplied is True
        assert state.currently_undone is False

    def test_undone_again_after_reapply_undo_wins(self):
        rows = [
            _row("2", "SQL", 2),
            _row("2", "UNDO_SQL", 3),
            _row("2", "SQL", 4),
            _row("2", "UNDO_SQL", 5),
        ]

        state = latest_successful_ranks(rows)["2"]

        assert state.versioned == 4
        assert state.undo == 5
        assert state.reapplied is False
        assert state.currently_undone is True

    def test_never_undone_is_not_reapplied(self):
        rows = [_row("1", "SQL", 1)]

        state = latest_successful_ranks(rows)["1"]

        assert state.reapplied is False
        assert state.currently_undone is False
        assert state.undo == 0
        assert state.versioned == 1

    def test_failed_versioned_row_does_not_count_as_reapply(self):
        rows = [
            _row("1", "SQL", 1),
            _row("1", "UNDO_SQL", 2),
            _row("1", "SQL", 3, success=False),
        ]

        state = latest_successful_ranks(rows)["1"]

        assert state.versioned == 1
        assert state.reapplied is False
        assert state.currently_undone is True

    def test_failed_undo_is_ignored(self):
        rows = [
            _row("1", "SQL", 1),
            _row("1", "UNDO_SQL", 2, success=False),
        ]

        state = latest_successful_ranks(rows)["1"]

        assert state.undo == 0
        assert state.currently_undone is False

    def test_string_success_one_counts(self):
        rows = [
            _row("1", "SQL", 1, success="1"),
            _row("1", "UNDO_SQL", 2, success="1"),
            _row("1", "SQL", 3, success="1"),
        ]

        assert latest_successful_ranks(rows)["1"].reapplied is True

    def test_python_versioned_type_counts_as_reapply(self):
        rows = [
            _row("2", MigrationType.PYTHON, 1),
            _row("2", MigrationType.UNDO_SQL, 2),
            _row("2", MigrationType.PYTHON, 3),
        ]

        assert latest_successful_ranks(rows)["2"].reapplied is True

    def test_missing_rank_defaults_to_zero(self):
        row = SimpleNamespace(version="1", type="SQL", success=True)
        state = latest_successful_ranks([row])["1"]
        assert state.versioned == 0


class TestCallSitesUseSharedHelper:
    """If a site re-inlines the loop, this fails even when behaviour happens to match."""

    def test_four_sites_import_and_call_the_same_function(self):
        from dblift.core.migration.commands import migrate_command
        from dblift.core.migration.rules import migration_rules
        from dblift.core.migration.state import migration_data_service, migration_state_manager
        from dblift.core.migration.state.rank_wins import latest_successful_ranks as helper

        sites = (
            (
                migrate_command,
                migrate_command.MigrateCommand._filter_already_applied,
            ),
            (
                migration_rules,
                migration_rules.MigrationRules._is_currently_undone,
            ),
            (
                migration_data_service,
                migration_data_service.MigrationDataService._get_reapplied_versions,
            ),
            (
                migration_state_manager,
                migration_state_manager.MigrationStateManager._compute_pending_migrations,
            ),
        )
        for module, method in sites:
            source = inspect.getsource(method)
            assert (
                "latest_successful_ranks" in source
            ), f"{method.__qualname__} must call latest_successful_ranks"
            if module is migration_rules:
                # Function-level import: a module-level import of the state
                # package from rules cycles through state/__init__.py.
                continue
            assert module.latest_successful_ranks is helper, (
                f"{module.__name__} must import latest_successful_ranks from "
                "dblift.core.migration.state.rank_wins"
            )
