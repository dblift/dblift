"""Migrate selects Pending from the catalog; tags/versions are command filters."""

from __future__ import annotations

import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from dblift.core.migration.commands.migrate_command import MigrateCommand
from dblift.core.migration.migration import MigrationType
from dblift.core.migration.state.migration_state import (
    CatalogMigration,
    MigrationEligibility,
    MigrationState,
)
from tests.unit.core.migration.commands._plan_migrate_wiring import wire_plan_migrate


def _migration(script_name, version, type_=MigrationType.SQL):
    return SimpleNamespace(
        script_name=script_name,
        version=version,
        description="test",
        type=type_,
        checksum=123,
    )


def _catalog_state(*rows):
    return MigrationState(
        catalog=tuple(CatalogMigration(obj, eligibility) for obj, eligibility in rows),
        applied_objects=[],
    )


def _make_cmd(state, *, strict_mode=False):
    config = MagicMock()
    config.database.schema = "public"
    config.database.type = "postgresql"
    config.strict_mode = strict_mode

    provider = MagicMock()
    provider.acquire_migration_lock.return_value = True
    provider.release_migration_lock.return_value = None

    history_manager = MagicMock()
    history_manager.get_applied_migration_records.return_value = []

    state_manager = wire_plan_migrate(MagicMock())
    state_manager.build_state.return_value = state
    state_manager.get_current_version.return_value = None
    state_manager.apply_filters_to_migrations.side_effect = lambda migrations, **kwargs: list(
        migrations
    )

    migration_helpers = MagicMock()
    migration_helpers.validate_migrations_for_migrate.return_value = (True, None, 0.0)
    cmd = MigrateCommand(
        config=config,
        log=MagicMock(),
        provider=provider,
        script_manager=MagicMock(),
        history_manager=history_manager,
        validator=MagicMock(),
        execution_engine=MagicMock(),
        migration_helpers=migration_helpers,
        state_manager=state_manager,
        migration_ui=MagicMock(),
        migration_rules=MagicMock(),
    )
    return cmd


def _execute(cmd, **kwargs):
    cmd.migration_helpers.setup_migration_parameters.return_value = (True, [])
    with patch.object(cmd, "_run_preflight"):
        with patch.object(cmd, "_log_command_header_update"):
            with patch.object(cmd, "_update_final_state"):
                with patch.object(cmd, "_log_command_completion"):
                    return cmd.execute(Path("/migrations"), **kwargs)


class TestMigrateSelectsPendingFromCatalog(unittest.TestCase):
    def test_executes_only_pending_not_below_baseline_above_target_or_available(self):
        below = _migration("V1__old.sql", "1")
        pending = _migration("V3__new.sql", "3")
        above = _migration("V5__future.sql", "5")
        available = _migration("U3__new.sql", "3", MigrationType.UNDO_SQL)
        state = _catalog_state(
            (below, MigrationEligibility.BELOW_BASELINE),
            (pending, MigrationEligibility.PENDING),
            (above, MigrationEligibility.ABOVE_TARGET),
            (available, MigrationEligibility.UNDO_AVAILABLE),
        )
        cmd = _make_cmd(state)

        with patch.object(cmd, "_execute_migration_loop") as loop:
            _execute(cmd)

        loop.assert_called_once()
        executed = loop.call_args.args[0]
        self.assertEqual(executed, [pending])

    def test_apply_filters_does_not_receive_target_version(self):
        pending = _migration("V3__new.sql", "3")
        state = _catalog_state((pending, MigrationEligibility.PENDING))
        cmd = _make_cmd(state)

        with patch.object(cmd, "_execute_migration_loop"):
            _execute(cmd, target_version="4", tags="feature", versions="3")

        kwargs = cmd.state_manager.apply_filters_to_migrations.call_args.kwargs
        self.assertNotIn("target_version", kwargs)
        self.assertEqual(kwargs.get("tags"), "feature")
        self.assertEqual(kwargs.get("versions"), "3")

    def test_build_state_does_not_receive_tag_or_version_omit_filters(self):
        pending = _migration("V3__new.sql", "3")
        state = _catalog_state((pending, MigrationEligibility.PENDING))
        cmd = _make_cmd(state)

        with patch.object(cmd, "_execute_migration_loop"):
            _execute(cmd, target_version="4", tags="feature", versions="3", exclude_versions="1")

        kwargs = cmd.state_manager.build_state.call_args.kwargs
        self.assertEqual(kwargs.get("target_version"), "4")
        self.assertIsNone(kwargs.get("tags"))
        self.assertIsNone(kwargs.get("exclude_tags"))
        self.assertIsNone(kwargs.get("versions"))
        self.assertIsNone(kwargs.get("exclude_versions"))

    def test_strict_mode_fails_when_selecting_out_of_order_pending(self):
        out_of_order = _migration("V1.5__late.sql", "1.5")
        state = _catalog_state((out_of_order, MigrationEligibility.PENDING))
        cmd = _make_cmd(state, strict_mode=True)
        state.current_version = "2"
        cmd.state_manager.build_state.side_effect = None
        cmd.state_manager.build_state.return_value = state

        result = _execute(cmd)

        cmd.state_manager.build_state.assert_called()
        self.assertFalse(result.success)
        self.assertIn("Strict mode: out-of-order migration", result.error_message or "")
        self.assertNotIn("Migration operation failed", result.error_message or "")
        cmd.execution_engine.execute_migration.assert_not_called()

    def test_strict_mode_failure_still_reports_the_current_schema_version(self):
        out_of_order = _migration("V1.5__late.sql", "1.5")
        state = _catalog_state((out_of_order, MigrationEligibility.PENDING))
        cmd = _make_cmd(state, strict_mode=True)
        state.current_version = "2"

        result = _execute(cmd)

        self.assertFalse(result.success)
        self.assertEqual(result.current_schema_version, "2")
