"""Bare ``undo`` (no ``--target-version``) must pick the migration with the highest
installed_rank -- i.e. the migration actually applied most recently -- not the one
with the highest version number.

Every provider's ``get_applied_migrations()`` query returns rows ``ORDER BY
installed_rank`` (ascending), and the ``--target-version`` path in this same file
already walks that list via ``reversed(applied_migrations)`` to get newest-installed
first. The no-target-version path must use the same install-rank convention instead
of re-sorting by version number, otherwise migrations applied out of version order
(e.g. V10 installed before V1 and V2) are undone in the wrong order.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from core.migration.commands.undo_command import UndoCommand
from core.migration.migration import MigrationType


def _make_migration(version, mtype=MigrationType.SQL, success=True):
    m = MagicMock()
    m.version = version
    m.type = mtype
    m.success = success
    m.script_name = f"V{version}__test.sql"
    m.description = "test"
    m.checksum = "abc"
    m.content = None
    return m


def _make_command(applied_migrations):
    state_manager = MagicMock()
    migration_state = MagicMock()
    migration_state.applied_objects = applied_migrations
    state_manager.build_state.return_value = migration_state
    state_manager.get_current_version.return_value = None

    migration_rules = MagicMock()
    migration_rules.should_undo_version.return_value = (True, None)

    executor_factory = MagicMock()
    executor_factory.get_executor.return_value = None

    execution_engine = MagicMock()
    execution_engine.executor_factory = executor_factory

    history_manager = MagicMock()
    script_manager = MagicMock()
    script_manager.get_migration_scripts.return_value = []

    config = MagicMock()
    config.database.schema = "test"

    cmd = UndoCommand(
        config=config,
        log=MagicMock(),
        provider=MagicMock(),
        script_manager=script_manager,
        history_manager=history_manager,
        validator=MagicMock(),
        execution_engine=execution_engine,
        migration_helpers=MagicMock(),
        state_manager=state_manager,
        migration_ui=MagicMock(),
        migration_rules=migration_rules,
    )
    cmd.journal = None
    cmd.placeholder_service = MagicMock()
    cmd.migration_helpers.setup_migration_parameters.return_value = (True, None)
    return cmd


@pytest.mark.unit
class TestNoTargetVersionUsesInstallRankNotVersionOrder:
    """Migrations applied out of version order must be undone in install-rank
    order (most recently applied first), not version-number order."""

    def test_last_installed_is_undone_even_when_its_version_is_lowest(self):
        # Installed in this order: V10 (rank 1), V1 (rank 2), V2 (rank 3).
        # applied_objects reflects the DB's "ORDER BY installed_rank" result,
        # i.e. ascending install order.
        v10 = _make_migration(10)
        v1 = _make_migration(1)
        v2 = _make_migration(2)
        cmd = _make_command([v10, v1, v2])

        cmd.execute(scripts_dir=MagicMock())

        checked_versions = [
            call.args[0] for call in cmd.migration_rules.should_undo_version.call_args_list
        ]
        assert checked_versions == ["2"], (
            f"Expected V2 (highest installed_rank / most recently applied) to be "
            f"the only candidate checked, got {checked_versions} -- bare undo must "
            "follow install-rank order, not version-number order."
        )

    def test_skips_non_versioned_migration_type_and_falls_through(self):
        # A REPEATABLE migration installed most recently must be skipped (it's
        # not undoable), falling through to the next SQL/PYTHON candidate.
        v1 = _make_migration(1)
        repeatable = _make_migration(None, mtype=MigrationType.REPEATABLE)
        cmd = _make_command([v1, repeatable])

        cmd.execute(scripts_dir=MagicMock())

        checked_versions = [
            call.args[0] for call in cmd.migration_rules.should_undo_version.call_args_list
        ]
        assert checked_versions == ["1"]

    def test_skips_migration_that_fails_tag_filter(self):
        # Neither migration carries the requested tag, so both are skipped
        # and nothing is undone.
        v1 = _make_migration(1)
        v2 = _make_migration(2)
        cmd = _make_command([v1, v2])

        cmd.execute(scripts_dir=MagicMock(), tags="special")

        assert cmd.migration_rules.should_undo_version.call_args_list == []

    def test_skips_failed_migration_and_falls_through(self):
        # The most recently applied migration failed and must be skipped,
        # falling through to the next successful one.
        v1 = _make_migration(1, success=True)
        v2 = _make_migration(2, success=False)
        cmd = _make_command([v1, v2])

        cmd.execute(scripts_dir=MagicMock())

        checked_versions = [
            call.args[0] for call in cmd.migration_rules.should_undo_version.call_args_list
        ]
        assert checked_versions == ["1"]

    def test_skips_migration_with_no_version(self):
        # An SQL/PYTHON-typed migration with no version (edge case) must be
        # skipped, falling through to the next versioned candidate.
        v1 = _make_migration(1)
        no_version = _make_migration(None)
        cmd = _make_command([v1, no_version])

        cmd.execute(scripts_dir=MagicMock())

        checked_versions = [
            call.args[0] for call in cmd.migration_rules.should_undo_version.call_args_list
        ]
        assert checked_versions == ["1"]

    def test_versions_filter_excludes_non_matching_migration(self):
        # --versions=1 excludes V2 (most recently applied), falling through
        # to V1.
        v1 = _make_migration(1)
        v2 = _make_migration(2)
        cmd = _make_command([v1, v2])

        cmd.execute(scripts_dir=MagicMock(), versions="1")

        checked_versions = [
            call.args[0] for call in cmd.migration_rules.should_undo_version.call_args_list
        ]
        assert checked_versions == ["1"]

    def test_exclude_versions_filter_skips_migration(self):
        # --exclude-versions=2 excludes V2 (most recently applied), falling
        # through to V1.
        v1 = _make_migration(1)
        v2 = _make_migration(2)
        cmd = _make_command([v1, v2])

        cmd.execute(scripts_dir=MagicMock(), exclude_versions="2")

        checked_versions = [
            call.args[0] for call in cmd.migration_rules.should_undo_version.call_args_list
        ]
        assert checked_versions == ["1"]
