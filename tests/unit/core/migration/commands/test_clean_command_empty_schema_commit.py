"""Regression tests for BUG-06: clean() must not commit when schema has no objects.

Root cause: commit_transaction() was called unconditionally after clean enumeration,
even when no DDL was issued. PostgreSQL raises PSQLException
"Cannot commit when autoCommit is enabled" when commit() is called on a
connection whose autoCommit has not been disabled.
"""

from unittest.mock import MagicMock

import pytest

from dblift.core.migration.commands.clean_command import CleanCommand
from dblift.db.provider_interfaces import DroppableObject


def _make_command():
    provider = MagicMock()
    provider.list_droppable_objects.return_value = []
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
    return cmd, provider, log


@pytest.mark.unit
class TestCleanCommandEmptySchemaCommit:
    """BUG-06: commit_transaction must not be called when no DDL was issued."""

    def test_empty_schema_does_not_call_commit(self):
        """When enumeration returns no objects, commit_transaction is not called."""
        cmd, provider, _ = _make_command()

        result = cmd.execute()

        assert result.success is True
        provider.commit_transaction.assert_not_called()

    def test_empty_schema_autocommit_error_is_not_raised(self):
        """Even if commit_transaction would throw on autoCommit=True, empty clean succeeds."""
        cmd, provider, _ = _make_command()
        provider.commit_transaction.side_effect = Exception(
            "Cannot commit when autoCommit is enabled"
        )

        result = cmd.execute()

        assert result.success is True
        provider.commit_transaction.assert_not_called()

    def test_non_empty_schema_calls_commit(self):
        """When DDL statements were issued, commit_transaction must be called."""
        cmd, provider, _ = _make_command()
        provider.list_droppable_objects.return_value = [
            DroppableObject(name="t1", object_type="table", drop_sql="DROP TABLE myschema.t1")
        ]
        provider.commit_transaction.return_value = None

        result = cmd.execute()

        assert result.success is True
        provider.commit_transaction.assert_called_once()

    def test_empty_droppable_list_does_not_call_commit(self):
        """Providers returning an empty droppable list skip the commit."""
        cmd, provider, _ = _make_command()

        result = cmd.execute()

        assert result.success is True
        provider.commit_transaction.assert_not_called()

    def test_non_empty_droppable_list_calls_commit(self):
        """Providers returning a non-empty droppable list still commit."""
        cmd, provider, _ = _make_command()
        provider.list_droppable_objects.return_value = [
            DroppableObject(name="t1", object_type="table", drop_sql="DROP TABLE myschema.t1")
        ]
        provider.commit_transaction.return_value = None

        result = cmd.execute()

        assert result.success is True
        provider.commit_transaction.assert_called_once()
