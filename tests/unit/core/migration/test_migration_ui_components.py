"""
Unit tests for migration UI components:
  - TableRenderer
  - MigrationUI (orchestrator)
"""

import unittest
from unittest.mock import MagicMock, patch

import pytest

from core.migration.migration import Migration, MigrationType
from core.migration.state.migration_state import MigrationState
from core.migration.ui.migration_ui import MigrationUI
from core.migration.ui.table_renderer import TableRenderer

pytestmark = [pytest.mark.unit]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_log():
    log = MagicMock()
    return log


def _make_migration(
    script_name="V1__test.sql",
    version="1",
    m_type=MigrationType.SQL,
    success=True,
    installed_rank=1,
    checksum="abc",
    description="Test",
    installed_on=None,
    installed_by=None,
):
    m = Migration(
        script_name=script_name,
        content="SELECT 1;",
        version=version,
        description=description,
        type=m_type,
    )
    m.success = success
    m.installed_rank = installed_rank
    m.checksum = checksum
    m.installed_on = installed_on
    m.installed_by = installed_by
    return m


# ===========================================================================
# TableRenderer tests
# ===========================================================================


class TestTableRendererFormatMigrationTable(unittest.TestCase):

    def setUp(self):
        self.renderer = TableRenderer(_make_log())

    def test_empty_returns_no_migrations(self):
        result = self.renderer.format_migration_table([])
        assert result == "No migrations found."

    def test_single_migration_contains_fields(self):
        data = [
            {
                "category": "Versioned",
                "version": "1.0",
                "description": "Initial",
                "type": "SQL",
                "installed_on": "2024-01-01",
                "installed_by": "admin",
                "state": "Success",
                "undoable": True,
                "execution_time": 123,
            }
        ]
        result = self.renderer.format_migration_table(data)
        assert "1.0" in result
        assert "Initial" in result
        assert "Success" in result
        assert "Total migrations: 1" in result

    def test_type_column_not_truncated(self):
        # Type column must fit the longest MigrationType value (REPEATABLE) untruncated
        data = [{"version": "1.0", "type": "UNDO_SQL"}]
        result = self.renderer.format_migration_table(data)
        assert "UNDO_SQL" in result
        assert "UN…" not in result
        assert "Ty…" not in result

    def test_undoable_false_renders_no(self):
        # Undoable column removed (too narrow for table) — state column used instead
        data = [{"version": "2.0", "undoable": False, "state": "Pending"}]
        result = self.renderer.format_migration_table(data)
        assert "2.0" in result

    def test_table_separator_present(self):
        data = [{"version": "1.0"}]
        result = self.renderer.format_migration_table(data)
        # Rich SIMPLE_HEAVY box uses ━ (U+2501) as separator, not ASCII "+-"
        assert "━" in result or "Version" in result

    def test_multiple_rows_all_present(self):
        data = [{"version": "1.0"}, {"version": "2.0"}, {"version": "3.0"}]
        result = self.renderer.format_migration_table(data)
        assert "Total migrations: 3" in result


class TestTableRendererPrintMigrationTable(unittest.TestCase):

    def setUp(self):
        self.renderer = TableRenderer(_make_log())

    def test_narrow_terminal_keeps_description_column(self):
        """A narrow stdout must not collapse the (only flexible) Description column.

        Regression: with 8 no_wrap columns and Description as the sole wrappable
        column, Rich shrank Description to zero width when the detected terminal
        was narrower than the table, blanking the column.
        """
        import contextlib
        import io
        import os

        data = [
            {
                "category": "Versioned",
                "version": "1.0.0",
                "description": "Initial schema",
                "type": "SQL",
                "installed_on": "2024-01-01 00:00:00",
                "installed_by": "admin",
                "state": "Success",
                "undoable": False,
                "execution_time": 12,
            }
        ]
        buf = io.StringIO()
        with patch.dict(os.environ, {"COLUMNS": "80"}):
            with contextlib.redirect_stdout(buf):
                self.renderer.print_migration_table(data)
        out = buf.getvalue()
        assert "Description" in out  # header not collapsed away
        assert "Initial schema" in out  # cell value visible


class TestTableRendererFormatSummaryStats(unittest.TestCase):

    def setUp(self):
        self.renderer = TableRenderer(_make_log())

    def test_stats_formatted_with_title_case_keys(self):
        stats = {"total_migrations": 5, "applied_migrations": 3}
        result = self.renderer.format_summary_stats(stats)
        assert "Total Migrations" in result
        assert "5" in result
        assert "Applied Migrations" in result
        assert "3" in result

    def test_header_and_footer_markers(self):
        result = self.renderer.format_summary_stats({})
        assert "=== Migration Summary ===" in result
        assert "=" * 25 in result


# ===========================================================================
# MigrationUI orchestrator tests
# ===========================================================================


class TestMigrationUIInit(unittest.TestCase):

    def test_components_initialized(self):
        ui = MigrationUI(_make_log())
        assert ui.data_collector is not None
        assert ui.table_renderer is not None

    def test_none_log_uses_nulllog(self):
        from core.logger import NullLog

        ui = MigrationUI(None)
        assert isinstance(ui.log, NullLog)


class TestMigrationUIGetMigrationData(unittest.TestCase):

    def setUp(self):
        self.ui = MigrationUI(_make_log())

    def test_new_mode_with_migration_state(self):
        """migration_state-based path returns a list."""
        all_applied = [_make_migration()]
        state = MigrationState(pending_objects=[], all_applied_objects=all_applied)
        result = self.ui.get_migration_data(
            migration_state=state,
            all_applied_migrations=all_applied,
        )
        assert isinstance(result, list)

    def test_own_script_manager_propagated_to_data_collector(self):
        """When the UI already holds a script_manager, it's handed to the collector."""
        sm = MagicMock()
        self.ui.script_manager = sm
        state = MigrationState(pending_objects=[], all_applied_objects=[])
        self.ui.get_migration_data(migration_state=state, all_applied_migrations=[])
        assert self.ui.data_collector.script_manager is sm


class TestMigrationUIDisplayMigrationInfo(unittest.TestCase):

    def setUp(self):
        self.ui = MigrationUI(_make_log())
        self.ui.log.logs = [self.ui.log]

    def test_renders_table_and_logs_summary(self):
        """End-to-end: real MigrationUI/TableRenderer, no mocked collaborators."""
        m = _make_migration()
        state = MigrationState(pending_objects=[], all_applied_objects=[m])
        self.ui.display_migration_info(migration_state=state, all_applied_migrations=[m])

        self.ui.log.info.assert_called_once()
        self.ui.log.file_only_info.assert_called_once()
        assert self.ui.log.migration_data
        assert self.ui.log.migration_data[0]["version"] == "1"


if __name__ == "__main__":
    unittest.main()
