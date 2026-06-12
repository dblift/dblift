"""Unit tests for core.migration.state.migration_formatter module."""

from datetime import datetime
from unittest.mock import Mock

import pytest

from core.migration.state.migration_formatter import MigrationFormatter


@pytest.mark.unit
class TestMigrationFormatter:
    """Test MigrationFormatter class."""

    @pytest.fixture
    def formatter(self):
        """Create a MigrationFormatter instance."""
        logger = Mock()
        return MigrationFormatter(logger)

    def test_init(self, formatter):
        """Test MigrationFormatter initialization."""
        assert formatter.logger is not None

    def test_format_as_table_empty(self, formatter):
        """Test format_as_table with empty data."""
        result = formatter.format_as_table([])
        assert result == "No migrations found."

    def test_format_as_table_single_migration(self, formatter):
        """Test format_as_table with single migration."""
        migration_data = [
            {
                "category": "Versioned",
                "version": "1.0.0",
                "description": "Test migration",
                "type": "SQL",
                "installed_on": datetime(2023, 1, 1, 12, 0, 0),
                "state": "Success",
                "execution_time": 100,
            }
        ]
        result = formatter.format_as_table(migration_data)
        assert "Versioned" in result
        assert "1.0.0" in result
        assert "Test migration" in result
        assert "100ms" in result

    def test_format_as_table_multiple_migrations(self, formatter):
        """Test format_as_table with multiple migrations."""
        migration_data = [
            {
                "category": "Versioned",
                "version": "1.0.0",
                "description": "First migration",
                "type": "SQL",
                "installed_on": datetime(2023, 1, 1, 12, 0, 0),
                "state": "Success",
                "execution_time": 100,
            },
            {
                "category": "Versioned",
                "version": "2.0.0",
                "description": "Second migration",
                "type": "SQL",
                "installed_on": datetime(2023, 1, 2, 12, 0, 0),
                "state": "Pending",
                "execution_time": 0,
            },
        ]
        result = formatter.format_as_table(migration_data)
        assert "1.0.0" in result
        assert "2.0.0" in result

    def test_format_as_table_no_execution_time(self, formatter):
        """Test format_as_table with no execution time."""
        migration_data = [
            {
                "category": "Versioned",
                "version": "1.0.0",
                "description": "Test",
                "type": "SQL",
                "installed_on": None,
                "state": "Success",
                "execution_time": None,
            }
        ]
        result = formatter.format_as_table(migration_data)
        assert "1.0.0" in result

    def test_format_as_table_execution_time_zero(self, formatter):
        """Test format_as_table with execution time zero."""
        migration_data = [
            {
                "category": "Versioned",
                "version": "1.0.0",
                "description": "Test",
                "type": "SQL",
                "installed_on": None,
                "state": "Success",
                "execution_time": 0,
            }
        ]
        result = formatter.format_as_table(migration_data)
        assert "1.0.0" in result

    def test_format_as_table_long_description(self, formatter):
        """Test format_as_table with long description."""
        long_desc = "A" * 60
        migration_data = [
            {
                "category": "Versioned",
                "version": "1.0.0",
                "description": long_desc,
                "type": "SQL",
                "installed_on": None,
                "state": "Success",
                "execution_time": 100,
            }
        ]
        result = formatter.format_as_table(migration_data)
        assert "..." in result

    def test_format_as_table_missing_fields(self, formatter):
        """Test format_as_table with missing fields."""
        migration_data = [{}]
        result = formatter.format_as_table(migration_data)
        assert isinstance(result, str)

    def test_format_as_json_empty(self, formatter):
        """Test format_as_json with empty data."""
        result = formatter.format_as_json([])
        assert result["migrations"] == []
        assert result["summary"]["total"] == 0

    def test_format_as_json_single_migration(self, formatter):
        """Test format_as_json with single migration."""
        installed_on = datetime(2023, 1, 1, 12, 0, 0)
        migration_data = [
            {
                "category": "Versioned",
                "version": "1.0.0",
                "description": "Test migration",
                "type": "SQL",
                "installed_on": installed_on,
                "state": "Success",
                "execution_time": 100,
            }
        ]
        result = formatter.format_as_json(migration_data)
        assert len(result["migrations"]) == 1
        assert result["summary"]["total"] == 1
        assert result["summary"]["successful"] == 1
        assert isinstance(result["migrations"][0]["installed_on"], str)

    def test_format_as_json_multiple_states(self, formatter):
        """Test format_as_json with multiple states."""
        migration_data = [
            {"state": "Success"},
            {"state": "Failed"},
            {"state": "Pending"},
            {"state": "Other"},
        ]
        result = formatter.format_as_json(migration_data)
        assert result["summary"]["total"] == 4
        assert result["summary"]["successful"] == 1
        assert result["summary"]["failed"] == 1
        assert result["summary"]["pending"] == 1

    def test_format_as_json_no_installed_on(self, formatter):
        """Test format_as_json with no installed_on."""
        migration_data = [
            {
                "category": "Versioned",
                "version": "1.0.0",
                "state": "Success",
            }
        ]
        result = formatter.format_as_json(migration_data)
        assert len(result["migrations"]) == 1

    def test_format_as_html_empty(self, formatter):
        """Test format_as_html with empty data."""
        result = formatter.format_as_html([])
        assert "<p>No migrations found.</p>" in result

    def test_format_as_html_single_migration(self, formatter):
        """Test format_as_html with single migration."""
        migration_data = [
            {
                "category": "Versioned",
                "version": "1.0.0",
                "description": "Test migration",
                "type": "SQL",
                "installed_on": datetime(2023, 1, 1, 12, 0, 0),
                "state": "Success",
                "execution_time": 100,
            }
        ]
        result = formatter.format_as_html(migration_data)
        assert "<table" in result
        assert "1.0.0" in result
        assert "Test migration" in result
        assert "100ms" in result
        assert "Total migrations: 1" in result

    def test_format_as_html_multiple_migrations(self, formatter):
        """Test format_as_html with multiple migrations."""
        migration_data = [
            {
                "category": "Versioned",
                "version": "1.0.0",
                "description": "First",
                "type": "SQL",
                "installed_on": None,
                "state": "Success",
                "execution_time": 100,
            },
            {
                "category": "Versioned",
                "version": "2.0.0",
                "description": "Second",
                "type": "SQL",
                "installed_on": None,
                "state": "Failed",
                "execution_time": 0,
            },
        ]
        result = formatter.format_as_html(migration_data)
        assert "Total migrations: 2" in result
        assert "state-success" in result
        assert "state-failed" in result

    def test_format_as_html_no_execution_time(self, formatter):
        """Test format_as_html with no execution time."""
        migration_data = [
            {
                "category": "Versioned",
                "version": "1.0.0",
                "description": "Test",
                "type": "SQL",
                "installed_on": None,
                "state": "Success",
                "execution_time": None,
            }
        ]
        result = formatter.format_as_html(migration_data)
        assert "1.0.0" in result

    def test_format_as_html_execution_time_zero(self, formatter):
        """Test format_as_html with execution time zero."""
        migration_data = [
            {
                "category": "Versioned",
                "version": "1.0.0",
                "description": "Test",
                "type": "SQL",
                "installed_on": None,
                "state": "Success",
                "execution_time": 0,
            }
        ]
        result = formatter.format_as_html(migration_data)
        assert "1.0.0" in result

    def test_get_state_color_success(self, formatter):
        """Test _get_state_color for success state."""
        result = formatter._get_state_color("Success")
        assert result == "success"

    def test_get_state_color_failed(self, formatter):
        """Test _get_state_color for failed state."""
        result = formatter._get_state_color("Failed")
        assert result == "error"

    def test_get_state_color_pending(self, formatter):
        """Test _get_state_color for pending state."""
        result = formatter._get_state_color("Pending")
        assert result == "pending"

    def test_get_state_color_undone(self, formatter):
        """Test _get_state_color for undone state."""
        result = formatter._get_state_color("Undone")
        assert result == "warning"

    def test_get_state_color_missing(self, formatter):
        """Test _get_state_color for missing state."""
        result = formatter._get_state_color("Missing")
        assert result == "error"

    def test_get_state_color_ignored(self, formatter):
        """Test _get_state_color for ignored state."""
        result = formatter._get_state_color("Ignored")
        assert result == "muted"

    def test_get_state_color_deleted(self, formatter):
        """Test _get_state_color for deleted state."""
        result = formatter._get_state_color("Deleted")
        assert result == "muted"

    def test_get_state_color_available(self, formatter):
        """Test _get_state_color for available state."""
        result = formatter._get_state_color("Available")
        assert result == "info"

    def test_get_state_color_above_target(self, formatter):
        """Test _get_state_color for above target state."""
        result = formatter._get_state_color("Above target")
        assert result == "muted"

    def test_get_state_color_baseline(self, formatter):
        """Test _get_state_color for baseline state."""
        result = formatter._get_state_color("Baseline")
        assert result == "info"

    def test_get_state_color_below_baseline(self, formatter):
        """Test _get_state_color for below baseline state."""
        result = formatter._get_state_color("Below baseline")
        assert result == "muted"

    def test_get_state_color_failed_missing(self, formatter):
        """Test _get_state_color for failed missing state."""
        result = formatter._get_state_color("Failed missing")
        assert result == "error"

    def test_get_state_color_failed_future(self, formatter):
        """Test _get_state_color for failed future state."""
        result = formatter._get_state_color("Failed future")
        assert result == "error"

    def test_get_state_color_future(self, formatter):
        """Test _get_state_color for future state."""
        result = formatter._get_state_color("Future")
        assert result == "warning"

    def test_get_state_color_out_of_order(self, formatter):
        """Test _get_state_color for out of order state."""
        result = formatter._get_state_color("Out of order")
        assert result == "warning"

    def test_get_state_color_outdated(self, formatter):
        """Test _get_state_color for outdated state."""
        result = formatter._get_state_color("Outdated")
        assert result == "warning"

    def test_get_state_color_superseded(self, formatter):
        """Test _get_state_color for superseded state."""
        result = formatter._get_state_color("Superseded")
        assert result == "muted"

    def test_get_state_color_unknown(self, formatter):
        """Test _get_state_color for unknown state."""
        result = formatter._get_state_color("Unknown State")
        assert result == "default"

    def test_get_state_color_lowercase(self, formatter):
        """Test _get_state_color with lowercase input."""
        result = formatter._get_state_color("success")
        assert result == "success"
