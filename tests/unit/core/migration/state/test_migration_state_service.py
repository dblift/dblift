"""Unit tests for core.migration.state.migration_state_service module."""

from pathlib import Path
from unittest.mock import Mock

import pytest

from core.migration.migration import MigrationType
from core.migration.state.migration_display_state import MigrationDisplayState
from core.migration.state.migration_state_service import MigrationStateService


@pytest.mark.unit
class TestMigrationStateService:
    """Test MigrationStateService class."""

    @pytest.fixture
    def service(self):
        """Create a MigrationStateService instance."""
        logger = Mock()
        return MigrationStateService(logger)

    def test_init(self, service):
        """Test MigrationStateService initialization."""
        assert service.logger is not None

    def test_get_migration_type_string_none(self, service):
        """Test _get_migration_type_string with None."""
        result = service._get_migration_type_string(None)
        assert result == "UNKNOWN"

    def test_get_migration_type_string_enum(self, service):
        """Test _get_migration_type_string with enum."""
        result = service._get_migration_type_string(MigrationType.SQL)
        assert result == "SQL"

    def test_get_migration_type_string_string(self, service):
        """Test _get_migration_type_string with string."""
        result = service._get_migration_type_string("REPEATABLE")
        assert result == "REPEATABLE"

    def test_determine_state_none_migration(self, service):
        """Test determine_state with None migration."""
        result = service.determine_state(None, {})
        assert result == MigrationDisplayState.UNKNOWN

    def test_determine_state_delete_type(self, service):
        """Test determine_state for DELETE type migration."""
        migration = Mock()
        migration.type = "DELETE"
        result = service.determine_state(migration, {})
        assert result == MigrationDisplayState.DELETED

    def test_determine_state_baseline_type(self, service):
        """Test determine_state for BASELINE type migration."""
        migration = Mock()
        migration.type = "BASELINE"
        result = service.determine_state(migration, {})
        assert result == MigrationDisplayState.BASELINE

    def test_determine_state_failed(self, service):
        """Test determine_state for failed migration."""
        migration = Mock()
        migration.success = False
        migration.resolved = True
        result = service.determine_state(migration, {})
        assert result == MigrationDisplayState.FAILED

    def test_determine_state_failed_zero(self, service):
        """Test determine_state for failed migration (success=0)."""
        migration = Mock()
        migration.success = 0
        migration.resolved = True
        result = service.determine_state(migration, {})
        assert result == MigrationDisplayState.FAILED

    def test_determine_state_failed_missing_future(self, service):
        """Test determine_state for failed missing migration in future."""
        migration = Mock()
        migration.success = False
        migration.resolved = False
        migration.version = "2.0.0"
        context = {"current_version": "1.0.0"}
        result = service.determine_state(migration, context)
        assert result == MigrationDisplayState.FAILED_FUTURE

    def test_determine_state_failed_missing_past(self, service):
        """Test determine_state for failed missing migration in past."""
        migration = Mock()
        migration.success = False
        migration.resolved = False
        migration.version = "1.0.0"
        context = {"current_version": "2.0.0"}
        result = service.determine_state(migration, context)
        assert result == MigrationDisplayState.FAILED_MISSING

    def test_determine_state_failed_missing_no_version(self, service):
        """Test determine_state for failed missing migration without version."""
        migration = Mock()
        migration.success = False
        migration.resolved = False
        migration.version = None
        context = {"current_version": "1.0.0"}
        result = service.determine_state(migration, context)
        assert result == MigrationDisplayState.FAILED_MISSING

    def test_determine_state_success_undo_sql(self, service):
        """Test determine_state for successful UNDO_SQL migration."""
        migration = Mock()
        migration.success = True
        migration.type = "UNDO_SQL"
        result = service.determine_state(migration, {})
        assert result == MigrationDisplayState.SUCCESS

    def test_determine_state_success_undone(self, service):
        """Test determine_state for undone migration."""
        migration = Mock()
        migration.success = True
        migration.type = "SQL"
        migration.version = "1.0.0"
        migration.resolved = True
        context = {"undone_versions": {"1.0.0"}}
        result = service.determine_state(migration, context)
        assert result == MigrationDisplayState.UNDONE

    def test_determine_state_success_reapplied(self, service):
        """Test determine_state for reapplied migration."""
        migration = Mock()
        migration.success = True
        migration.type = "SQL"
        migration.version = "1.0.0"
        migration.resolved = True
        context = {"undone_versions": {"1.0.0"}, "reapplied_versions": {"1.0.0"}}
        result = service.determine_state(migration, context)
        assert result == MigrationDisplayState.SUCCESS

    def test_determine_state_success_out_of_order(self, service):
        """Test determine_state for out-of-order migration."""
        migration = Mock()
        migration.success = True
        migration.type = "SQL"
        migration.version = "1.0.0"
        migration.resolved = True
        context = {"out_of_order_migrations": {"1.0.0"}}
        result = service.determine_state(migration, context)
        assert result == MigrationDisplayState.OUT_OF_ORDER

    def test_determine_state_success_repeatable_outdated(self, service):
        """Test determine_state for outdated repeatable migration."""
        migration = Mock()
        migration.success = True
        migration.type = "REPEATABLE"
        migration.script_name = "R__test.sql"
        migration.checksum = "new_checksum"
        context = {"repeatable_checksums": {"R__test.sql": "old_checksum"}}
        result = service.determine_state(migration, context)
        assert result == MigrationDisplayState.OUTDATED

    def test_determine_state_success_repeatable_current(self, service):
        """Test determine_state for current repeatable migration."""
        migration = Mock()
        migration.success = True
        migration.type = "REPEATABLE"
        migration.script_name = "R__test.sql"
        migration.checksum = "same_checksum"
        context = {"repeatable_checksums": {"R__test.sql": "same_checksum"}}
        result = service.determine_state(migration, context)
        assert result == MigrationDisplayState.SUCCESS

    def test_determine_state_success_missing_future(self, service):
        """Test determine_state for successful missing migration in future."""
        migration = Mock()
        migration.success = True
        migration.type = "SQL"
        migration.version = "2.0.0"
        migration.resolved = False
        context = {"current_version": "1.0.0"}
        result = service.determine_state(migration, context)
        assert result == MigrationDisplayState.FUTURE

    def test_determine_state_success_missing_past(self, service):
        """Test determine_state for successful missing migration in past."""
        migration = Mock()
        migration.success = True
        migration.type = "SQL"
        migration.version = "1.0.0"
        migration.resolved = False
        context = {"current_version": "2.0.0"}
        result = service.determine_state(migration, context)
        assert result == MigrationDisplayState.MISSING

    def test_determine_state_success_missing_no_version(self, service):
        """Test determine_state for successful missing migration without version."""
        migration = Mock()
        migration.success = True
        migration.type = "SQL"
        migration.version = None
        migration.resolved = False
        context = {"current_version": "1.0.0"}
        result = service.determine_state(migration, context)
        assert result == MigrationDisplayState.MISSING

    def test_determine_state_success_default(self, service):
        """Test determine_state for successful migration (default)."""
        migration = Mock()
        migration.success = True
        migration.type = "SQL"
        migration.version = "1.0.0"
        migration.resolved = True
        result = service.determine_state(migration, {})
        assert result == MigrationDisplayState.SUCCESS

    def test_determine_state_needs_repair(self, service):
        """Test determine_state for migration needing repair."""
        migration = Mock()
        migration.success = None
        result = service.determine_state(migration, {})
        assert result == MigrationDisplayState.NEEDS_REPAIR

    def test_determine_state_unknown_fallback(self, service):
        """Test determine_state fallback to UNKNOWN."""
        migration = Mock()
        migration.success = "unexpected_value"
        result = service.determine_state(migration, {})
        assert result == MigrationDisplayState.UNKNOWN

    def test_determine_pending_state_repeatable(self, service):
        """Test determine_pending_state for repeatable migration."""
        migration = Mock()
        migration.type = "REPEATABLE"
        context = {}
        result = service.determine_pending_state(migration, context)
        assert result == MigrationDisplayState.PENDING

    def test_determine_pending_state_undo_sql(self, service):
        """Test determine_pending_state for UNDO_SQL migration."""
        migration = Mock()
        migration.type = "UNDO_SQL"
        context = {}
        result = service.determine_pending_state(migration, context)
        assert result == MigrationDisplayState.AVAILABLE

    def test_determine_pending_state_below_baseline(self, service):
        """Test determine_pending_state for version below baseline."""
        migration = Mock()
        migration.type = "SQL"
        migration.version = "1.0.0"
        context = {"baseline_version": "2.0.0"}
        result = service.determine_pending_state(migration, context)
        assert result == MigrationDisplayState.BELOW_BASELINE

    def test_determine_pending_state_above_target(self, service):
        """Test determine_pending_state for version above target."""
        migration = Mock()
        migration.type = "SQL"
        migration.version = "3.0.0"
        context = {"target_version": "2.0.0"}
        result = service.determine_pending_state(migration, context)
        assert result == MigrationDisplayState.ABOVE_TARGET

    def test_determine_pending_state_with_undo_script(self, service, tmp_path):
        """Test determine_pending_state for version with undo script."""
        migration = Mock()
        migration.type = "SQL"
        migration.version = "1.0.0"

        # Create undo script
        undo_file = tmp_path / "U1.0.0__undo.sql"
        undo_file.write_text("DROP TABLE test;")

        context = {"scripts_dir": str(tmp_path)}
        result = service.determine_pending_state(migration, context)
        assert result == MigrationDisplayState.AVAILABLE

    def test_determine_pending_state_default(self, service):
        """Test determine_pending_state default to PENDING."""
        migration = Mock()
        migration.type = "SQL"
        migration.version = "1.0.0"
        context = {}
        result = service.determine_pending_state(migration, context)
        assert result == MigrationDisplayState.PENDING

    def test_compare_versions_both_none(self, service):
        """Test _compare_versions with both None."""
        result = service._compare_versions(None, None)
        assert result == 0

    def test_compare_versions_first_none(self, service):
        """Test _compare_versions with first None."""
        result = service._compare_versions(None, "1.0.0")
        assert result == -1

    def test_compare_versions_second_none(self, service):
        """Test _compare_versions with second None."""
        result = service._compare_versions("1.0.0", None)
        assert result == 1

    def test_compare_versions_equal(self, service):
        """Test _compare_versions with equal versions."""
        result = service._compare_versions("1.0.0", "1.0.0")
        assert result == 0

    def test_compare_versions_first_greater(self, service):
        """Test _compare_versions with first greater."""
        result = service._compare_versions("2.0.0", "1.0.0")
        assert result == 1

    def test_compare_versions_first_lesser(self, service):
        """Test _compare_versions with first lesser."""
        result = service._compare_versions("1.0.0", "2.0.0")
        assert result == -1

    def test_compare_versions_with_underscores(self, service):
        """Test _compare_versions with underscores."""
        result = service._compare_versions("1_0_0", "1.0.0")
        assert result == 0

    def test_compare_versions_different_lengths(self, service):
        """Test _compare_versions with different lengths."""
        # When versions have different lengths, shorter is padded with zeros
        # So "1.0.0.0" vs "1.0.0" becomes "1.0.0.0" vs "1.0.0.0" which equals 0
        result = service._compare_versions("1.0.0.0", "1.0.0")
        assert result == 0

        # Test with actually different values
        result = service._compare_versions("2.0.0.0", "1.0.0")
        assert result == 1

    def test_compare_versions_non_numeric_parts(self, service):
        """Test _compare_versions with non-numeric parts."""
        result = service._compare_versions("1.0.0a", "1.0.0")
        # Should fallback to string comparison
        assert isinstance(result, int)

    def test_compare_version_parts_equal(self, service):
        """Test _compare_version_parts with equal parts."""
        result = service._compare_version_parts([1, 0, 0], [1, 0, 0])
        assert result == 0

    def test_compare_version_parts_first_greater(self, service):
        """Test _compare_version_parts with first greater."""
        result = service._compare_version_parts([2, 0, 0], [1, 0, 0])
        assert result == 1

    def test_compare_version_parts_first_lesser(self, service):
        """Test _compare_version_parts with first lesser."""
        result = service._compare_version_parts([1, 0, 0], [2, 0, 0])
        assert result == -1

    def test_compare_version_parts_different_lengths(self, service):
        """Test _compare_version_parts with different lengths."""
        result = service._compare_version_parts([1, 0, 0, 1], [1, 0, 0])
        assert result == 1

    def test_version_has_undo_script_true(self, service, tmp_path):
        """Test _version_has_undo_script returns True when script exists."""
        undo_file = tmp_path / "U1.0.0__undo.sql"
        undo_file.write_text("DROP TABLE test;")

        result = service._version_has_undo_script("1.0.0", tmp_path)
        assert result is True

    def test_version_has_undo_script_false(self, service, tmp_path):
        """Test _version_has_undo_script returns False when script doesn't exist."""
        result = service._version_has_undo_script("1.0.0", tmp_path)
        assert result is False

    def test_version_has_undo_script_no_scripts_dir(self, service):
        """Test _version_has_undo_script with no scripts_dir."""
        result = service._version_has_undo_script("1.0.0", None)
        assert result is False

    def test_version_has_undo_script_no_version(self, service, tmp_path):
        """Test _version_has_undo_script with no version."""
        result = service._version_has_undo_script(None, tmp_path)
        assert result is False

    def test_version_has_undo_script_exception(self, service):
        """Test _version_has_undo_script handles exceptions."""
        # Pass invalid path type to trigger exception
        result = service._version_has_undo_script("1.0.0", 123)
        assert result is False
