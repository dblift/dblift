"""Regression tests for clean dry-run enumeration.

Dry-run now uses the same lightweight provider droppable-object contract as
actual clean. It must not fall back to SchemaIntrospector.
"""

from unittest.mock import MagicMock

import pytest

from dblift.core.migration.commands.clean_command import CleanCommand
from dblift.db.provider_interfaces import DroppableObject


def _make_command(provider):
    config = MagicMock()
    config.database.schema = "myschema"
    log = MagicMock()
    cmd = CleanCommand(
        config=config,
        log=log,
        provider=provider,
        script_manager=MagicMock(),
        history_manager=MagicMock(),
        validator=MagicMock(),
        execution_engine=MagicMock(),
        migration_helpers=MagicMock(),
        state_manager=MagicMock(),
        migration_ui=MagicMock(),
        migration_rules=MagicMock(),
    )
    return cmd, log


@pytest.mark.unit
class TestCleanCommandDryRunDroppableObjects:
    def test_dry_run_lists_provider_droppable_objects(self):
        provider = MagicMock()
        provider.list_droppable_objects.return_value = [
            DroppableObject(name="tbl_a", object_type="table", drop_sql='DROP TABLE "tbl_a"'),
            DroppableObject(name="EmailType", object_type="type", drop_sql='DROP TYPE "EmailType"'),
        ]
        cmd, log = _make_command(provider)

        result = cmd.execute(dry_run=True)

        assert result.success is True
        provider.list_droppable_objects.assert_called_once_with("myschema")
        provider.execute_statement.assert_not_called()

        info_calls = [str(c) for c in log.info.call_args_list]
        assert any("Would drop table: tbl_a" in c for c in info_calls), info_calls
        assert any("Would drop type: EmailType" in c for c in info_calls), info_calls
        assert not any("schema appears empty" in c for c in info_calls), info_calls

    def test_dry_run_empty_provider_listing_logs_empty_message(self):
        provider = MagicMock()
        provider.list_droppable_objects.return_value = []
        cmd, log = _make_command(provider)

        result = cmd.execute(dry_run=True)

        assert result.success is True
        info_calls = [str(c) for c in log.info.call_args_list]
        assert any("schema appears empty" in c for c in info_calls), info_calls

    def test_dry_run_enumeration_error_is_reported(self):
        provider = MagicMock()
        provider.list_droppable_objects.side_effect = RuntimeError("preview boom")
        cmd, _ = _make_command(provider)

        result = cmd.execute(dry_run=True)

        assert result.success is False
        assert "preview boom" in result.error_message
