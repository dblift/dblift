"""``import-flyway`` validates every row before it writes any of them.

Two defects motivated these tests, both reproduced against the published
3.10.1 wheel as well as 4.0.0, so neither is a regression — they are simply
wrong, and the documented migration path from Flyway runs straight through
them:

* ``--dry-run`` reported success for a history table the real run cannot
  import. The type mapping, which is the check that decides whether an import
  can proceed at all, was only reached on the write path, so a dry run never
  saw the row it would choke on.
* The real run wrote rows until it reached the unmappable one and then
  aborted, leaving the target history table half-populated with no rollback.
"""

from pathlib import Path
from unittest.mock import Mock

import pytest

from dblift.core.migration.commands.import_flyway_command import ImportFlywayCommand


def _flyway_row(version, script, type_val="SQL", success=True):
    return {
        "installed_rank": 1,
        "version": version,
        "description": f"Description for {script}",
        "type": type_val,
        "script": script,
        "checksum": 12345,
        "installed_by": "admin",
        "installed_on": "2026-01-01 00:00:00",
        "execution_time": 150,
        "success": success,
    }


@pytest.fixture
def mock_dependencies():
    config = Mock()
    config.database.schema = "public"
    return {
        "config": config,
        "log": Mock(),
        "provider": Mock(),
        "script_manager": Mock(),
        "history_manager": Mock(),
        "validator": Mock(),
        "execution_engine": Mock(),
        "migration_helpers": Mock(),
        "state_manager": Mock(),
        "migration_ui": Mock(),
        "migration_rules": Mock(),
    }


@pytest.fixture
def command(mock_dependencies):
    return ImportFlywayCommand(**mock_dependencies)


@pytest.mark.unit
class TestImportFlywayAllOrNothing:
    def test_dry_run_fails_on_a_type_the_real_run_cannot_import(self, command, mock_dependencies):
        """A dry run must refuse what the real run refuses.

        Reporting "2 entries would be imported" and then failing on the very
        next invocation is worse than failing twice: the dry run is what a
        cautious operator runs first, precisely to find this out.
        """
        rows = [_flyway_row("1", "V1__init.sql"), _flyway_row("2", "V2__x.sql", "UNDO_JDBC")]
        mock_dependencies["provider"].get_applied_migrations.side_effect = [rows, []]

        result = command.execute(scripts_dir=Path("/scripts"), dry_run=True)

        assert result.success is False
        assert "UNDO_JDBC" in str(result.error_message or result.message)
        mock_dependencies["provider"].record_migration.assert_not_called()

    def test_an_unmappable_row_writes_nothing_at_all(self, command, mock_dependencies):
        """The abort must happen before the first write, not partway through.

        The first row here is perfectly importable. Writing it and then
        failing leaves the history table holding one of two versions, which
        reads to every later command as a real applied state.
        """
        rows = [_flyway_row("1", "V1__init.sql"), _flyway_row("2", "V2__x.sql", "UNDO_JDBC")]
        mock_dependencies["provider"].get_applied_migrations.side_effect = [rows, []]

        result = command.execute(scripts_dir=Path("/scripts"), dry_run=False)

        assert result.success is False
        mock_dependencies["provider"].record_migration.assert_not_called()
        mock_dependencies["provider"].commit_transaction.assert_not_called()

    def test_a_fully_mappable_history_still_imports(self, command, mock_dependencies):
        """The guard must not cost the happy path."""
        rows = [_flyway_row("1", "V1__init.sql"), _flyway_row("2", "V2__orders.sql")]
        mock_dependencies["provider"].get_applied_migrations.side_effect = [rows, []]

        result = command.execute(scripts_dir=Path("/scripts"), dry_run=False)

        assert result.success is True
        assert "2 entries imported" in result.message
        assert mock_dependencies["provider"].record_migration.call_count == 2
        mock_dependencies["provider"].commit_transaction.assert_called_once()

    @pytest.mark.parametrize("raw_success", [1, 0, "1", True, False])
    def test_success_is_carried_as_a_boolean(self, command, mock_dependencies, raw_success):
        """Flyway's ``success`` column type varies by engine; ours does not.

        Flyway declares BOOLEAN on PostgreSQL but an integer type on MySQL and
        SQLite, and a hand-built table can hold anything. Our PostgreSQL
        history column is BOOLEAN, and psycopg refuses an int for it, so the
        value is normalised on the way in rather than trusted.
        """
        rows = [_flyway_row("1", "V1__init.sql", success=raw_success)]
        mock_dependencies["provider"].get_applied_migrations.side_effect = [rows, []]

        result = command.execute(scripts_dir=Path("/scripts"), dry_run=False)

        assert result.success is True
        written = mock_dependencies["provider"].record_migration.call_args[0][1]
        assert isinstance(written["success"], bool)
        assert written["success"] is bool(raw_success and raw_success != "0")
