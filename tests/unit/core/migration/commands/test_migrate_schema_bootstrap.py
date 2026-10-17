"""A real migrate may create its target schema without baseline semantics."""

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from dblift.core.logger.results import MigrateResult
from dblift.core.migration.commands.base_command import BaseCommand
from dblift.core.migration.history.migration_history_manager import MigrationHistoryManager

pytestmark = pytest.mark.unit


def test_history_bootstrap_creates_schema_without_baseline_history_checks():
    provider = MagicMock()
    schema_exists = False

    def create_schema(schema):
        nonlocal schema_exists
        assert schema == "app"
        schema_exists = True

    def create_history(schema, create_schema, table):
        assert schema_exists, "target schema must exist before the history table"
        assert create_schema is False, "migrate must not invoke baseline safety checks"

    provider.get_normalized_object_name.side_effect = lambda name: name
    provider.create_schema_if_not_exists.side_effect = create_schema
    provider.create_history_table_if_not_exists.side_effect = create_history
    manager = MigrationHistoryManager(provider, "app", "tester", MagicMock())

    manager.create_schema_and_history_table(ensure_schema=True)

    assert schema_exists


def test_dry_run_preflight_does_not_bootstrap_schema_or_history():
    command = BaseCommand.__new__(BaseCommand)
    command.config = MagicMock()
    command.config.database.type = "postgresql"
    command.config.database.schema = "app"
    command.history_manager = MagicMock()
    command._ensure_connected = MagicMock()
    command._populate_database_info = MagicMock()

    command._run_preflight(MigrateResult(), ensure_history=True, dry_run=True, ensure_schema=True)

    command.history_manager.create_schema_and_history_table.assert_not_called()


@pytest.mark.parametrize("dry_run", [False, True])
def test_migrate_preflight_requests_schema_bootstrap_and_preserves_dry_run(dry_run):
    from tests.unit.core.migration.commands.test_migrate_command_repeatable_lock_race import _cmd

    command = _cmd([], applied_after_lock=[])
    preflight = MagicMock()
    command._run_preflight = preflight
    command._log_command_header_update = MagicMock()
    command._log_command_completion = MagicMock()

    command.execute(Path("migrations"), dry_run=dry_run)

    first = preflight.call_args_list[0]
    assert first.kwargs["ensure_schema"] is True
    assert first.kwargs["dry_run"] is dry_run
