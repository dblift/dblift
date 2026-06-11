"""Unit tests for core.logger.results module."""

from datetime import datetime, timedelta
from unittest.mock import Mock

import pytest

from core.logger.results import (
    BaselineResult,
    CleanResult,
    CommandResult,
    InfoResult,
    MigrateResult,
    MigrationInfo,
    MigrationSqlInfo,
    OperationResult,
    RepairResult,
    ValidateResult,
)

pytestmark = [pytest.mark.unit]


class TestOperationResult:
    """Test OperationResult base class."""

    def test_operation_result_initialization_default(self):
        """Test default initialization of OperationResult."""
        result = OperationResult()

        assert result.success is True
        assert result.error_message is None
        assert result.warnings == []
        assert isinstance(result.start_time, datetime)
        assert result.end_time is None
        assert result.data is None

    def test_operation_result_initialization_with_params(self):
        """Test initialization with parameters."""
        test_data = {"test": "data"}
        result = OperationResult(success=False, error_message="Test error", data=test_data)

        assert result.success is False
        assert result.error_message == "Test error"
        assert result.data == test_data

    def test_operation_result_initialization_with_error_param(self):
        """Test initialization with deprecated error parameter."""
        result = OperationResult(error="Legacy error")

        assert result.error_message == "Legacy error"

    def test_add_warning(self):
        """Test adding warnings."""
        result = OperationResult()

        result.add_warning("Warning 1")
        result.add_warning("Warning 2")

        assert len(result.warnings) == 2
        assert "Warning 1" in result.warnings
        assert "Warning 2" in result.warnings

    def test_set_error(self):
        """Test setting error."""
        result = OperationResult()

        result.set_error("Test error message")

        assert result.success is False
        assert result.error_message == "Test error message"

    def test_complete(self):
        """Test completing operation."""
        result = OperationResult()
        assert result.end_time is None

        result.complete()

        assert result.end_time is not None
        assert isinstance(result.end_time, datetime)

    def test_execution_time_not_completed(self):
        """Test execution time when not completed."""
        result = OperationResult()

        execution_time = result.execution_time()

        assert execution_time == 0

    def test_execution_time_completed(self):
        """Test execution time when completed."""
        result = OperationResult()

        # Manually set times for predictable test
        result.start_time = datetime.now()
        result.end_time = result.start_time + timedelta(milliseconds=500)

        execution_time = result.execution_time()

        assert execution_time == 500

    def test_operation_result_tracks_show_sql_payload(self):
        """Operation results can carry SQL visibility data for formatters."""
        result = OperationResult()
        sql_info = MigrationSqlInfo(
            script="V1__init.sql",
            version="1",
            description="init",
            statements=["CREATE TABLE users (id INTEGER);"],
        )

        result.show_sql = True
        result.add_sql_migration(sql_info)

        assert result.show_sql is True
        assert result.sql == [sql_info]


class TestMigrationInfo:
    """Test MigrationInfo class."""

    def test_migration_info_initialization_minimal(self):
        """Test minimal MigrationInfo initialization."""
        migration = MigrationInfo("test_script.sql")

        assert migration.script == "test_script.sql"
        assert migration.version is None
        assert migration.description == ""
        assert migration.type == "SQL"
        assert migration.status == "PENDING"
        assert migration.installed_on is None
        assert migration.installed_by is None
        assert migration.checksum is None
        assert migration.execution_time == 0
        assert migration.error is None

    def test_migration_info_initialization_full(self):
        """Test complete MigrationInfo initialization."""
        installed_on = datetime.now()
        migration = MigrationInfo(
            script="V1.0.1__test.sql",
            version="1.0.1",
            description="Test migration",
            type="SQL",
            status="SUCCESS",
            installed_on=installed_on,
            installed_by="test_user",
            checksum="abc123",
            execution_time=250,
            error="Test error",
        )

        assert migration.script == "V1.0.1__test.sql"
        assert migration.version == "1.0.1"
        assert migration.description == "Test migration"
        assert migration.type == "SQL"
        assert migration.status == "SUCCESS"
        assert migration.installed_on == installed_on
        assert migration.installed_by == "test_user"
        assert migration.checksum == "abc123"
        assert migration.execution_time == 250
        assert migration.error == "Test error"

    def test_migration_info_str_representation(self):
        """Test string representation of MigrationInfo."""
        migration = MigrationInfo(
            script="V1.0.1__test.sql",
            version="1.0.1",
            description="Test migration",
            type="SQL",
            status="SUCCESS",
        )

        str_repr = str(migration)

        assert "V1.0.1__test.sql" in str_repr
        assert "1.0.1" in str_repr
        assert "Test migration" in str_repr
        assert "SQL" in str_repr
        assert "SUCCESS" in str_repr

    def test_migration_info_with_integer_version(self):
        """Test MigrationInfo with integer version."""
        migration = MigrationInfo("test.sql", version=1)

        assert migration.version == 1


class TestCommandResult:
    """Test CommandResult class."""

    def test_command_result_initialization(self):
        """Test CommandResult initialization."""
        result = CommandResult()

        assert result.success is True
        assert result.command_type == ""
        assert result.output == []

    def test_add_output(self):
        """Test adding output."""
        result = CommandResult()

        result.add_output("Line 1")
        result.add_output("Line 2")

        assert len(result.output) == 2
        assert result.output[0] == "Line 1"
        assert result.output[1] == "Line 2"

    def test_get_output(self):
        """Test getting output."""
        result = CommandResult()
        result.add_output("Test output")

        output = result.get_output()

        assert output == ["Test output"]


class TestMigrateResult:
    """Test MigrateResult class."""

    def test_migrate_result_initialization(self):
        """Test MigrateResult initialization."""
        result = MigrateResult()

        assert result.success is True
        assert result.migrations == []
        assert result.target_schema == ""
        assert result.init_schema is False
        assert result.init_version is None

    def test_add_migration_success(self):
        """Test adding successful migration."""
        result = MigrateResult()
        migration = MigrationInfo("test.sql", status="SUCCESS")

        result.add_migration(migration)

        assert len(result.migrations) == 1
        assert result.migrations[0] == migration
        assert result.success is True

    def test_add_migration_failure(self):
        """Test adding failed migration."""
        result = MigrateResult()
        migration = MigrationInfo("test.sql", status="FAILED")

        result.add_migration(migration)

        assert len(result.migrations) == 1
        assert result.success is False

    def test_is_successful_no_migrations(self):
        """Test is_successful with no migrations."""
        result = MigrateResult()

        assert result.is_successful() is True

    def test_is_successful_all_success(self):
        """Test is_successful with all successful migrations."""
        result = MigrateResult()
        result.add_migration(MigrationInfo("test1.sql", status="SUCCESS"))
        result.add_migration(MigrationInfo("test2.sql", status="SUCCESS"))

        assert result.is_successful() is True

    def test_is_successful_with_failure(self):
        """Test is_successful with some failed migrations."""
        result = MigrateResult()
        result.add_migration(MigrationInfo("test1.sql", status="SUCCESS"))
        result.add_migration(MigrationInfo("test2.sql", status="FAILED"))

        assert result.is_successful() is False

    def test_error_property(self):
        """Test error property."""
        result = MigrateResult()
        result.set_error("Test error")

        assert result.error == "Test error"

    def test_set_error_with_typo_fix(self):
        """Test set_error with typo correction."""
        result = MigrateResult()

        result.set_error("Test\nVersion error with nversion")

        assert "Version" in result.error_message
        assert "version" in result.error_message
        assert "\nVersion" not in result.error_message
        assert "nversion" not in result.error_message

    def test_migrations_applied_empty(self):
        """Test migrations_applied with no migrations."""
        result = MigrateResult()

        applied = result.migrations_applied

        assert applied == []

    def test_migrations_applied_with_versioned(self):
        """Test migrations_applied with versioned migrations."""
        result = MigrateResult()
        result.add_migration(MigrationInfo("V1.0.1__test.sql", version="1.0.1", status="SUCCESS"))
        result.add_migration(MigrationInfo("V1.0.2__test.sql", version="1.0.2", status="FAILED"))

        applied = result.migrations_applied

        assert applied == ["1.0.1"]

    def test_migrations_applied_with_repeatable(self):
        """Test migrations_applied with repeatable migrations."""
        result = MigrateResult()
        migration = MigrationInfo("R__test.sql", status="SUCCESS")
        migration.script = "R__test.sql"  # For repeatable migrations
        result.add_migration(migration)

        applied = result.migrations_applied

        assert applied == ["R__test.sql"]


class TestCleanResult:
    """Test CleanResult class."""

    def test_clean_result_initialization(self):
        """Test CleanResult initialization."""
        result = CleanResult()

        assert result.success is True
        assert result.target_schema == ""
        assert result.schema_name == ""
        assert len(result.schemas_dropped) == 0
        assert len(result.tables_dropped) == 0

    def test_add_schema_dropped(self):
        """Test adding dropped schema."""
        result = CleanResult()

        result.add_schema_dropped("test_schema")
        result.add_schema_dropped("another_schema")

        assert len(result.schemas_dropped) == 2
        assert "test_schema" in result.schemas_dropped
        assert "another_schema" in result.schemas_dropped

    def test_add_table_dropped(self):
        """Test adding dropped table."""
        result = CleanResult()

        result.add_table_dropped("test_table")
        result.add_table_dropped("another_table")

        assert len(result.tables_dropped) == 2
        assert "test_table" in result.tables_dropped
        assert "another_table" in result.tables_dropped

    def test_add_duplicate_schema_dropped(self):
        """Test adding duplicate schema (should not duplicate in set)."""
        result = CleanResult()

        result.add_schema_dropped("test_schema")
        result.add_schema_dropped("test_schema")  # Duplicate

        assert len(result.schemas_dropped) == 1
        assert "test_schema" in result.schemas_dropped

    def test_add_cleaned_object_generic(self):
        """Test adding a cleaned object through the generic API."""
        result = CleanResult()

        result.add_cleaned_object(
            object_type="synonym", name="syn_t", schema="test_schema", details={"target": "foo"}
        )

        objects_map = result.get_objects_by_type()
        assert "synonym" in objects_map
        assert "syn_t" in objects_map["synonym"]
        detail = result.get_object_details("synonym", "syn_t")
        assert detail["schema"] == "test_schema"
        assert detail["target"] == "foo"


class TestValidateResult:
    """Test ValidateResult class."""

    def test_validate_result_initialization(self):
        """Test ValidateResult initialization."""
        result = ValidateResult()

        assert result.success is True
        assert result.target_schema == ""
        assert result.migration_data is None
        assert result.error_count == 0
        assert result.validated_migrations == []
        assert result.failed_migrations == []

    def test_add_validated_migration(self):
        """Test adding validated migration."""
        result = ValidateResult()
        migration = MigrationInfo("test.sql", status="SUCCESS")

        result.add_validated_migration(migration)

        assert len(result.validated_migrations) == 1
        assert result.validated_migrations[0] == migration

    def test_add_failed_migration(self):
        """Test adding failed migration."""
        result = ValidateResult()
        migration = MigrationInfo("test.sql", status="FAILED")

        result.add_failed_migration(migration)

        assert len(result.failed_migrations) == 1
        assert result.failed_migrations[0] == migration
        assert result.error_count == 1
        assert result.success is False

    def test_multiple_failed_migrations(self):
        """Test multiple failed migrations increment error count."""
        result = ValidateResult()

        result.add_failed_migration(MigrationInfo("test1.sql", status="FAILED"))
        result.add_failed_migration(MigrationInfo("test2.sql", status="FAILED"))

        assert result.error_count == 2
        assert result.success is False


class TestInfoResult:
    """Test InfoResult class."""

    def test_info_result_initialization(self):
        """Test InfoResult initialization."""
        result = InfoResult()

        assert result.success is True
        assert result.target_schema == ""
        assert result.migration_data is None
        assert result.current_schema_version is None
        assert result.schema_name == ""
        assert result.migrations == []

    def test_add_migration(self):
        """Test adding migration."""
        result = InfoResult()
        migration = MigrationInfo("test.sql")

        result.add_migration(migration)

        assert len(result.migrations) == 1
        assert result.migrations[0] == migration

    def test_get_current_version(self):
        """Test getting current version."""
        result = InfoResult()
        result.current_schema_version = "1.2.3"

        version = result.get_current_version()

        assert version == "1.2.3"

    def test_migrations_applied_returns_successful_versions_and_repeatables(self):
        """Test InfoResult applied migration convenience property."""
        result = InfoResult()
        result.add_migration(MigrationInfo("V1__init.sql", version="1", status="SUCCESS"))
        result.add_migration(MigrationInfo("V2__pending.sql", version="2", status="PENDING"))
        result.add_migration(MigrationInfo("R__refresh.sql", status="Success"))

        assert result.migrations_applied == ["1", "R__refresh.sql"]


class TestBaselineResult:
    """Test BaselineResult class."""

    def test_baseline_result_initialization(self):
        """Test BaselineResult initialization."""
        result = BaselineResult()

        assert result.success is True
        assert result.target_schema == ""
        assert result.schema_name == ""
        assert result.baseline_version == ""

    def test_set_baseline_version(self):
        """Test setting baseline version."""
        result = BaselineResult()

        result.set_baseline_version("1.0.0")

        assert result.baseline_version == "1.0.0"


class TestRepairResult:
    """Test RepairResult class."""

    def test_repair_result_initialization(self):
        """Test RepairResult initialization."""
        result = RepairResult()

        assert result.success is True
        assert result.target_schema == ""
        assert result.schema_name == ""
        assert result.repaired_migrations == []
        assert result.removed_migrations == []
        assert result.aligned_migrations == []

    def test_add_repaired_migration(self):
        """Test adding repaired migration."""
        result = RepairResult()
        migration = MigrationInfo("test.sql")

        result.add_repaired_migration(migration)

        assert len(result.repaired_migrations) == 1
        assert result.repaired_migrations[0] == migration

    def test_add_removed_migration(self):
        """Test adding removed migration."""
        result = RepairResult()
        migration = MigrationInfo("test.sql")

        result.add_removed_migration(migration)

        assert len(result.removed_migrations) == 1
        assert result.removed_migrations[0] == migration

    def test_add_aligned_migration(self):
        """Test adding aligned migration."""
        result = RepairResult()
        migration = MigrationInfo("test.sql")

        result.add_aligned_migration(migration)

        assert len(result.aligned_migrations) == 1
        assert result.aligned_migrations[0] == migration

    def test_multiple_migration_types(self):
        """Test adding different types of migrations."""
        result = RepairResult()

        repaired = MigrationInfo("repaired.sql")
        removed = MigrationInfo("removed.sql")
        aligned = MigrationInfo("aligned.sql")

        result.add_repaired_migration(repaired)
        result.add_removed_migration(removed)
        result.add_aligned_migration(aligned)

        assert len(result.repaired_migrations) == 1
        assert len(result.removed_migrations) == 1
        assert len(result.aligned_migrations) == 1
        assert result.repaired_migrations[0] == repaired
        assert result.removed_migrations[0] == removed
        assert result.aligned_migrations[0] == aligned
