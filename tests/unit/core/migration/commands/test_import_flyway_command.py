"""Unit tests for core.migration.commands.import_flyway_command module (story 17-5)."""

from pathlib import Path
from unittest.mock import Mock

import pytest

from core.migration.commands.import_flyway_command import ImportFlywayCommand


@pytest.mark.unit
class TestImportFlywayCommand:
    """Test ImportFlywayCommand.execute() logic."""

    @pytest.fixture
    def mock_dependencies(self):
        """Create mock dependencies for ImportFlywayCommand."""
        config = Mock()
        config.database.schema = "public"

        log = Mock()
        provider = Mock()
        history_manager = Mock()

        return {
            "config": config,
            "log": log,
            "provider": provider,
            "script_manager": Mock(),
            "history_manager": history_manager,
            "validator": Mock(),
            "execution_engine": Mock(),
            "migration_helpers": Mock(),
            "state_manager": Mock(),
            "migration_ui": Mock(),
            "migration_rules": Mock(),
        }

    @pytest.fixture
    def command(self, mock_dependencies):
        """Create an ImportFlywayCommand with mocked dependencies."""
        return ImportFlywayCommand(**mock_dependencies)

    def _make_flyway_row(self, version, script, checksum=12345, type_val="SQL"):
        """Helper to build a flyway row dict."""
        return {
            "installed_rank": 1,
            "version": version,
            "description": f"Description for {script}",
            "type": type_val,
            "script": script,
            "checksum": checksum,
            "installed_by": "admin",
            "installed_on": "2026-01-01 00:00:00",
            "execution_time": 150,
            "success": True,
        }

    # ------------------------------------------------------------------ AC#6.1
    def test_nominal_two_entries_imported(self, command, mock_dependencies):
        """Two Flyway entries → record_migration called twice with correct dicts."""
        row1 = self._make_flyway_row("1.0", "V1__init.sql")
        row2 = self._make_flyway_row("2.0", "V2__add_users.sql", checksum=67890)
        mock_dependencies["provider"].get_applied_migrations.side_effect = [[row1, row2], []]

        result = command.execute(scripts_dir=Path("/scripts"), dry_run=False)

        assert result.success is True
        assert "2 entries imported" in result.message

        provider = mock_dependencies["provider"]
        assert provider.record_migration.call_count == 2
        provider.record_migration.assert_any_call("public", row1, "dblift_schema_history")
        provider.record_migration.assert_any_call("public", row2, "dblift_schema_history")
        provider.commit_transaction.assert_called_once()

    # ------------------------------------------------------------------ AC#6.2
    def test_dry_run_no_record_migration(self, command, mock_dependencies):
        """dry_run=True → record_migration NOT called."""
        row = self._make_flyway_row("1.0", "V1__init.sql")
        mock_dependencies["provider"].get_applied_migrations.side_effect = [[row], []]

        result = command.execute(scripts_dir=Path("/scripts"), dry_run=True)

        assert result.success is True
        assert "would be imported" in result.message
        assert "1 entry" in result.message
        mock_dependencies["provider"].record_migration.assert_not_called()
        # BUG-06: dry-run preview now emitted via log.info so users see it
        # without enabling debug logging.
        info_calls = [str(c) for c in mock_dependencies["log"].info.call_args_list]
        assert any("V1__init.sql" in c for c in info_calls)
        assert any("DRY RUN" in c for c in info_calls)

    # ------------------------------------------------------------------ AC#6.3
    def test_empty_flyway_table_zero_imports(self, command, mock_dependencies):
        """Empty flyway_schema_history → 0 imports, success=True."""
        mock_dependencies["provider"].get_applied_migrations.return_value = []

        result = command.execute(scripts_dir=Path("/scripts"), dry_run=False)

        assert result.success is True
        assert "0 entries imported" in result.message
        mock_dependencies["provider"].record_migration.assert_not_called()

    # ------------------------------------------------------------------ AC#6.4
    def test_checksum_none_baseline(self, command, mock_dependencies):
        """BASELINE row with checksum=None → passed as-is to record_migration."""
        row = self._make_flyway_row("1.0", "V1__baseline.sql", checksum=None)
        mock_dependencies["provider"].get_applied_migrations.side_effect = [[row], []]

        result = command.execute(scripts_dir=Path("/scripts"), dry_run=False)

        assert result.success is True
        provider = mock_dependencies["provider"]
        provider.record_migration.assert_called_once_with("public", row, "dblift_schema_history")
        # Verify checksum is None in the dict passed
        call_row = provider.record_migration.call_args[0][1]
        assert call_row["checksum"] is None

    # ------------------------------------------------------------------ AC#5.2
    def test_record_migration_failure_propagates(self, command, mock_dependencies):
        """record_migration raises → result.success=False, error logged."""
        row = self._make_flyway_row("1.0", "V1__init.sql")
        mock_dependencies["provider"].get_applied_migrations.side_effect = [[row], []]
        mock_dependencies["provider"].record_migration.side_effect = RuntimeError("DB write error")

        result = command.execute(scripts_dir=Path("/scripts"), dry_run=False)

        assert result.success is False
        assert result.error_message is not None
        assert "DB write error" in result.error_message
        mock_dependencies["provider"].rollback_transaction.assert_called_once()
        mock_dependencies["log"].error.assert_called()

    # ------------------------------------------------------------------ AC#2.1
    def test_calls_get_applied_migrations_with_flyway_table(self, command, mock_dependencies):
        """Verifies get_applied_migrations is called with 'flyway_schema_history'."""
        mock_dependencies["provider"].get_applied_migrations.side_effect = [[], []]

        command.execute(scripts_dir=Path("/scripts"), dry_run=False)

        mock_dependencies["provider"].get_applied_migrations.assert_any_call(
            "public", "flyway_schema_history"
        )

    def test_oracle_default_flyway_table_normalized_to_uppercase(self, command, mock_dependencies):
        """Default (non-overridden) source table is uppercased for Oracle so it

        matches a real Flyway installation's table, which Oracle case-folds to
        uppercase because Flyway creates it via unquoted DDL.
        """
        row = {
            "INSTALLED_RANK": 1,
            "VERSION": "1",
            "DESCRIPTION": "init",
            "TYPE": "SQL",
            "SCRIPT": "V1__init.sql",
            "CHECKSUM": 123,
            "INSTALLED_BY": "flyway",
            "INSTALLED_ON": "2026-01-01 00:00:00",
            "EXECUTION_TIME": 42,
            "SUCCESS": True,
        }
        mock_dependencies["config"].database.type = "oracle"
        mock_dependencies["provider"].get_schema_qualified_name.return_value = (
            '"public"."FLYWAY_SCHEMA_HISTORY"'
        )
        mock_dependencies["provider"].execute_query.return_value = [row]
        mock_dependencies["provider"].get_applied_migrations.return_value = []

        command.execute(scripts_dir=Path("/scripts"), dry_run=False)

        mock_dependencies["provider"].get_schema_qualified_name.assert_called_once_with(
            "public", "FLYWAY_SCHEMA_HISTORY"
        )
        query = mock_dependencies["provider"].execute_query.call_args.args[0]
        assert 'FROM "public"."FLYWAY_SCHEMA_HISTORY"' in query
        mock_dependencies["provider"].get_applied_migrations.assert_called_once_with(
            "public", "dblift_schema_history"
        )
        imported = mock_dependencies["provider"].record_migration.call_args.args[1]
        assert imported["script"] == "V1__init.sql"

    def test_oracle_explicit_flyway_table_override_preserved_exactly(
        self, command, mock_dependencies
    ):
        """An explicit --flyway-table override is passed through verbatim,

        even on Oracle — only the unspecified default name gets normalized.
        """
        mock_dependencies["config"].database.type = "oracle"
        mock_dependencies["provider"].get_schema_qualified_name.return_value = (
            '"public"."Custom_Flyway_Tbl"'
        )
        mock_dependencies["provider"].execute_query.return_value = []
        mock_dependencies["provider"].get_applied_migrations.return_value = []

        command.execute(
            scripts_dir=Path("/scripts"), dry_run=False, flyway_table="Custom_Flyway_Tbl"
        )

        mock_dependencies["provider"].get_schema_qualified_name.assert_called_once_with(
            "public", "Custom_Flyway_Tbl"
        )

    # ------------------------------------------------------------------ BUG-05
    def test_missing_flyway_table_reports_error(self, command, mock_dependencies):
        """flyway_schema_history absent → error, not a silent 0-record success.

        Before BUG-05 was fixed, a user pointing import-flyway at a schema with no
        flyway_schema_history table would see "0 entries imported" and success=True,
        masking a configuration mistake.
        """
        mock_dependencies["provider"].table_exists.return_value = False

        result = command.execute(scripts_dir=Path("/scripts"), dry_run=False)

        assert result.success is False
        assert result.error_message is not None
        assert "flyway_schema_history" in result.error_message
        assert "not found" in result.error_message
        mock_dependencies["provider"].get_applied_migrations.assert_not_called()
        mock_dependencies["provider"].record_migration.assert_not_called()

    def test_skips_rows_already_present_in_target_history(self, command, mock_dependencies):
        """Existing DBLift history rows are not imported a second time."""
        row1 = self._make_flyway_row("1.0", "V1__init.sql")
        row2 = self._make_flyway_row("2.0", "V2__add_users.sql", checksum=67890)
        existing = {"version": "1.0", "script": "V1__init.sql"}
        mock_dependencies["provider"].get_applied_migrations.side_effect = [
            [row1, row2],
            [existing],
        ]

        result = command.execute(scripts_dir=Path("/scripts"), dry_run=False)

        assert result.success is True
        assert "1 entry imported" in result.message
        assert "1 duplicate skipped" in result.message
        mock_dependencies["provider"].record_migration.assert_called_once_with(
            "public", row2, "dblift_schema_history"
        )
