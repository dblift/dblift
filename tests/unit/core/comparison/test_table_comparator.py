"""Tests for Table Comparator.

This module tests the TableComparator class which compares table objects
and generates diff results.
"""

import pytest

from core.comparison.diff_models import ColumnDiff, ConstraintDiff, SchemaDiff, TableDiff
from core.comparison.table_comparator import TableComparator
from core.comparison.type_normalizer import DataTypeNormalizer
from core.sql_model.base import ConstraintType, SqlColumn, SqlConstraint
from core.sql_model.table import Table


@pytest.mark.unit
class TestTableComparator:
    """Test TableComparator class."""

    def setup_method(self):
        """Set up test fixtures."""
        self.normalizer = DataTypeNormalizer()
        self.comparator = TableComparator(self.normalizer)

    def test_init(self):
        """Test TableComparator initialization."""
        comparator = TableComparator(self.normalizer)
        assert comparator.type_normalizer == self.normalizer

    def test_compare_tables_identical(self):
        """Test comparing identical tables."""
        col1 = SqlColumn("id", "INTEGER", is_nullable=False)
        col2 = SqlColumn("name", "VARCHAR(100)", is_nullable=True)

        expected = Table("users", columns=[col1, col2], dialect="postgresql")
        actual = Table("users", columns=[col1, col2], dialect="postgresql")

        diff = self.comparator.compare_tables(expected, actual)

        assert isinstance(diff, TableDiff)
        assert diff.has_diffs is False

    def test_compare_tables_derived_table_skips_comparison(self):
        """Test that derived tables skip column/constraint comparison."""
        expected = Table("users", columns=[], dialect="postgresql")
        expected.derived_from = "SELECT * FROM other_table"

        actual = Table("users", columns=[], dialect="postgresql")

        diff = self.comparator.compare_tables(expected, actual)

        assert isinstance(diff, TableDiff)
        # Should have no column/constraint diffs for derived tables
        assert len(diff.missing_columns) == 0
        assert len(diff.extra_columns) == 0
        assert len(diff.modified_columns) == 0

    def test_compare_tables_missing_columns(self):
        """Test detecting missing columns."""
        col1 = SqlColumn("id", "INTEGER")
        col2 = SqlColumn("name", "VARCHAR(100)")

        expected = Table("users", columns=[col1, col2], dialect="postgresql")
        actual = Table("users", columns=[col1], dialect="postgresql")

        diff = self.comparator.compare_tables(expected, actual)

        assert diff.has_diffs is True
        assert "name" in diff.missing_columns

    def test_compare_tables_extra_columns(self):
        """Test detecting extra columns."""
        col1 = SqlColumn("id", "INTEGER")
        col2 = SqlColumn("email", "VARCHAR(255)")

        expected = Table("users", columns=[col1], dialect="postgresql")
        actual = Table("users", columns=[col1, col2], dialect="postgresql")

        diff = self.comparator.compare_tables(expected, actual)

        assert diff.has_diffs is True
        assert "email" in diff.extra_columns

    def test_compare_tables_modified_columns(self):
        """Test detecting modified columns."""
        expected_col = SqlColumn("age", "INTEGER", is_nullable=True)
        actual_col = SqlColumn("age", "INTEGER", is_nullable=False)

        expected = Table("users", columns=[expected_col], dialect="postgresql")
        actual = Table("users", columns=[actual_col], dialect="postgresql")

        diff = self.comparator.compare_tables(expected, actual)

        assert diff.has_diffs is True
        assert len(diff.modified_columns) == 1
        assert diff.modified_columns[0].column_name == "age"

    def test_compare_tables_missing_constraints(self):
        """Test detecting missing constraints."""
        col1 = SqlColumn("id", "INTEGER")
        constraint = SqlConstraint(
            name="pk_users", constraint_type=ConstraintType.PRIMARY_KEY, column_names=["id"]
        )

        expected = Table("users", columns=[col1], constraints=[constraint], dialect="postgresql")
        actual = Table("users", columns=[col1], constraints=[], dialect="postgresql")

        diff = self.comparator.compare_tables(expected, actual)

        assert diff.has_diffs is True
        assert len(diff.missing_constraints) > 0

    def test_compare_tables_extra_constraints(self):
        """Test detecting extra constraints."""
        col1 = SqlColumn("id", "INTEGER")
        constraint = SqlConstraint(
            name="pk_users", constraint_type=ConstraintType.PRIMARY_KEY, column_names=["id"]
        )

        expected = Table("users", columns=[col1], constraints=[], dialect="postgresql")
        actual = Table("users", columns=[col1], constraints=[constraint], dialect="postgresql")

        diff = self.comparator.compare_tables(expected, actual)

        assert diff.has_diffs is True
        assert len(diff.extra_constraints) > 0

    def test_compare_tables_temporary_changed(self):
        """Test detecting temporary property change."""
        col1 = SqlColumn("id", "INTEGER")

        expected = Table("users", columns=[col1], dialect="postgresql")
        expected.temporary = False

        actual = Table("users", columns=[col1], dialect="postgresql")
        actual.temporary = True

        diff = self.comparator.compare_tables(expected, actual)

        assert diff.has_diffs is True
        assert diff.temporary_changed is True

    def test_compare_tables_sqlserver_filegroup_changed(self):
        """Test detecting SQL Server filegroup change."""
        col1 = SqlColumn("id", "INTEGER")

        expected = Table("users", columns=[col1], dialect="sqlserver")
        expected.filegroup = "PRIMARY"

        actual = Table("users", columns=[col1], dialect="sqlserver")
        actual.filegroup = "SECONDARY"

        diff = self.comparator.compare_tables(expected, actual, dialect="sqlserver")

        assert diff.has_diffs is True
        assert diff.filegroup_changed is True

    def test_compare_tables_sqlserver_filegroup_primary_normalized(self):
        """Test that PRIMARY filegroup is normalized to None."""
        col1 = SqlColumn("id", "INTEGER")

        expected = Table("users", columns=[col1], dialect="sqlserver")
        expected.filegroup = None

        actual = Table("users", columns=[col1], dialect="sqlserver")
        actual.filegroup = "PRIMARY"

        diff = self.comparator.compare_tables(expected, actual, dialect="sqlserver")

        # Should not detect difference (PRIMARY is normalized to None)
        assert diff.filegroup_changed is False

    def test_compare_tables_sqlserver_memory_optimized_changed(self):
        """Test detecting SQL Server memory-optimized change."""
        col1 = SqlColumn("id", "INTEGER")

        expected = Table("users", columns=[col1], dialect="sqlserver")
        expected.memory_optimized = False

        actual = Table("users", columns=[col1], dialect="sqlserver")
        actual.memory_optimized = True

        diff = self.comparator.compare_tables(expected, actual, dialect="sqlserver")

        assert diff.has_diffs is True
        assert diff.memory_optimized_changed is True

    def test_compare_tables_sqlserver_system_versioned_changed(self):
        """Test detecting SQL Server system-versioned change."""
        col1 = SqlColumn("id", "INTEGER")

        expected = Table("users", columns=[col1], dialect="sqlserver")
        expected.system_versioned = False

        actual = Table("users", columns=[col1], dialect="sqlserver")
        actual.system_versioned = True

        diff = self.comparator.compare_tables(expected, actual, dialect="sqlserver")

        assert diff.has_diffs is True
        assert diff.system_versioned_changed is True

    def test_compare_tables_sqlserver_history_table_changed(self):
        """Test detecting SQL Server history table change."""
        col1 = SqlColumn("id", "INTEGER")

        expected = Table("users", columns=[col1], dialect="sqlserver")
        expected.system_versioned = True
        expected.history_table = "users_history"

        actual = Table("users", columns=[col1], dialect="sqlserver")
        actual.system_versioned = True
        actual.history_table = "users_history_new"

        diff = self.comparator.compare_tables(expected, actual, dialect="sqlserver")

        assert diff.has_diffs is True
        assert diff.history_table_changed is True

    def test_compare_tables_db2_compress_changed(self):
        """Test detecting DB2 compress change."""
        col1 = SqlColumn("id", "INTEGER")

        expected = Table("users", columns=[col1], dialect="db2")
        expected.compress = False

        actual = Table("users", columns=[col1], dialect="db2")
        actual.compress = True

        diff = self.comparator.compare_tables(expected, actual, dialect="db2")

        assert diff.has_diffs is True
        assert diff.compress_changed is True

    def test_compare_tables_db2_compress_none_normalized(self):
        """Test that None compress is normalized to False in DB2."""
        col1 = SqlColumn("id", "INTEGER")

        expected = Table("users", columns=[col1], dialect="db2")
        expected.compress = None

        actual = Table("users", columns=[col1], dialect="db2")
        actual.compress = False

        diff = self.comparator.compare_tables(expected, actual, dialect="db2")

        # Should not detect difference (None normalized to False)
        assert diff.compress_changed is False

    def test_compare_tables_db2_compress_type_changed(self):
        """Test detecting DB2 compress_type change."""
        col1 = SqlColumn("id", "INTEGER")

        expected = Table("users", columns=[col1], dialect="db2")
        expected.compress = True
        expected.compress_type = "ROW"

        actual = Table("users", columns=[col1], dialect="db2")
        actual.compress = True
        actual.compress_type = "VALUE"

        diff = self.comparator.compare_tables(expected, actual, dialect="db2")

        assert diff.has_diffs is True
        assert diff.compress_type_changed is True

    def test_compare_tables_db2_logged_changed(self):
        """Test detecting DB2 logged change."""
        col1 = SqlColumn("id", "INTEGER")

        expected = Table("users", columns=[col1], dialect="db2")
        expected.logged = False

        actual = Table("users", columns=[col1], dialect="db2")
        actual.logged = True

        diff = self.comparator.compare_tables(expected, actual, dialect="db2")

        assert diff.has_diffs is True
        assert diff.logged_changed is True

    def test_compare_tables_db2_logged_none_ignored(self):
        """Test that None logged values are ignored in DB2."""
        col1 = SqlColumn("id", "INTEGER")

        expected = Table("users", columns=[col1], dialect="db2")
        expected.logged = None

        actual = Table("users", columns=[col1], dialect="db2")
        actual.logged = True

        diff = self.comparator.compare_tables(expected, actual, dialect="db2")

        # Should not detect difference when one is None
        assert diff.logged_changed is False

    def test_compare_tables_db2_organize_by_changed(self):
        """Test detecting DB2 organize_by change."""
        col1 = SqlColumn("id", "INTEGER")

        expected = Table("users", columns=[col1], dialect="db2")
        expected.organize_by = ["id"]

        actual = Table("users", columns=[col1], dialect="db2")
        actual.organize_by = ["name"]

        diff = self.comparator.compare_tables(expected, actual, dialect="db2")

        assert diff.has_diffs is True
        assert diff.organize_by_changed is True

    def test_compare_tables_partition_method_changed(self):
        """Test detecting partition method change."""
        col1 = SqlColumn("id", "INTEGER")

        expected = Table("users", columns=[col1], dialect="postgresql")
        expected.partition_method = "RANGE"

        actual = Table("users", columns=[col1], dialect="postgresql")
        actual.partition_method = "HASH"

        diff = self.comparator.compare_tables(expected, actual)

        assert diff.has_diffs is True
        assert diff.partition_method_changed is True

    def test_compare_tables_partition_columns_changed(self):
        """Test detecting partition columns change."""
        col1 = SqlColumn("id", "INTEGER")
        col2 = SqlColumn("name", "VARCHAR(100)")

        expected = Table("users", columns=[col1, col2], dialect="postgresql")
        expected.partition_method = "RANGE"
        expected.partition_columns = ["id"]

        actual = Table("users", columns=[col1, col2], dialect="postgresql")
        actual.partition_method = "RANGE"
        actual.partition_columns = ["name"]

        diff = self.comparator.compare_tables(expected, actual)

        assert diff.has_diffs is True
        assert diff.partition_columns_changed is True

    def test_compare_tables_postgresql_inherits_changed(self):
        """Test detecting PostgreSQL table inheritance change."""
        col1 = SqlColumn("id", "INTEGER")

        expected = Table("users", columns=[col1], dialect="postgresql")
        expected.inherits = ["base_table"]

        actual = Table("users", columns=[col1], dialect="postgresql")
        actual.inherits = []

        diff = self.comparator.compare_tables(expected, actual, dialect="postgresql")

        assert diff.has_diffs is True
        assert diff.inherits_changed is not None

    def test_compare_schemas(self):
        """Test comparing schemas."""
        col1 = SqlColumn("id", "INTEGER")

        expected_table1 = Table("users", columns=[col1], dialect="postgresql")
        expected_table2 = Table("orders", columns=[col1], dialect="postgresql")

        actual_table1 = Table("users", columns=[col1], dialect="postgresql")

        diff = self.comparator.compare_schemas(
            expected_tables=[expected_table1, expected_table2],
            actual_tables=[actual_table1],
            dialect="postgresql",
            schema_name="public",
        )

        assert isinstance(diff, SchemaDiff)
        assert "orders" in diff.missing_tables
        assert len(diff.extra_tables) == 0

    def test_compare_schemas_extra_tables(self):
        """Test detecting extra tables in schema."""
        col1 = SqlColumn("id", "INTEGER")

        expected_table1 = Table("users", columns=[col1], dialect="postgresql")

        actual_table1 = Table("users", columns=[col1], dialect="postgresql")
        actual_table2 = Table("extra_table", columns=[col1], dialect="postgresql")

        diff = self.comparator.compare_schemas(
            expected_tables=[expected_table1],
            actual_tables=[actual_table1, actual_table2],
            dialect="postgresql",
            schema_name="public",
        )

        assert isinstance(diff, SchemaDiff)
        assert "extra_table" in diff.extra_tables

    def test_compare_schemas_modified_tables(self):
        """Test detecting modified tables in schema."""
        expected_col = SqlColumn("id", "INTEGER", is_nullable=True)
        actual_col = SqlColumn("id", "INTEGER", is_nullable=False)

        expected_table = Table("users", columns=[expected_col], dialect="postgresql")
        actual_table = Table("users", columns=[actual_col], dialect="postgresql")

        diff = self.comparator.compare_schemas(
            expected_tables=[expected_table],
            actual_tables=[actual_table],
            dialect="postgresql",
            schema_name="public",
        )

        assert isinstance(diff, SchemaDiff)
        assert len(diff.modified_tables) == 1
        assert diff.modified_tables[0].table_name == "users"

    def test_compare_columns(self):
        """Test _compare_columns method."""
        expected_col1 = SqlColumn("id", "INTEGER")
        expected_col2 = SqlColumn("name", "VARCHAR(100)")

        actual_col1 = SqlColumn("id", "INTEGER")

        missing, extra, modified = self.comparator._compare_columns(
            expected_columns=[expected_col1, expected_col2],
            actual_columns=[actual_col1],
            dialect="postgresql",
        )

        assert len(missing) == 1
        assert missing[0].name == "name"
        assert len(extra) == 0
        assert len(modified) == 0

    def test_compare_columns_case_insensitive(self):
        """Test that column comparison is case-insensitive."""
        expected_col = SqlColumn("ID", "INTEGER")
        actual_col = SqlColumn("id", "INTEGER")

        missing, extra, modified = self.comparator._compare_columns(
            expected_columns=[expected_col], actual_columns=[actual_col], dialect="postgresql"
        )

        assert len(missing) == 0
        assert len(extra) == 0
        assert len(modified) == 0

    def test_compare_constraints(self):
        """Test _compare_constraints method."""
        col1 = SqlColumn("id", "INTEGER")

        expected_constraint = SqlConstraint(
            name="pk_users", constraint_type=ConstraintType.PRIMARY_KEY, column_names=["id"]
        )

        missing, extra, modified = self.comparator._compare_constraints(
            expected_constraints=[expected_constraint], actual_constraints=[], dialect="postgresql"
        )

        assert len(missing) == 1
        assert len(extra) == 0
        assert len(modified) == 0

    def test_compare_column_details_data_type_diff(self):
        """Test _compare_column_details with data type difference."""
        expected_col = SqlColumn("age", "INTEGER")
        actual_col = SqlColumn("age", "VARCHAR(10)")

        diff = self.comparator._compare_column_details(expected_col, actual_col, "postgresql")

        assert diff is not None
        assert diff.data_type_diff is not None
        assert diff.column_name == "age"

    def test_compare_column_details_nullable_diff(self):
        """Test _compare_column_details with nullable difference."""
        expected_col = SqlColumn("email", "VARCHAR(255)", is_nullable=True)
        actual_col = SqlColumn("email", "VARCHAR(255)", is_nullable=False)

        diff = self.comparator._compare_column_details(expected_col, actual_col, "postgresql")

        assert diff is not None
        assert diff.nullable_diff == (True, False)

    def test_compare_column_details_default_diff(self):
        """Test _compare_column_details with default value difference."""
        expected_col = SqlColumn("status", "VARCHAR(10)", default_value="active")
        actual_col = SqlColumn("status", "VARCHAR(10)", default_value="inactive")

        diff = self.comparator._compare_column_details(expected_col, actual_col, "postgresql")

        assert diff is not None
        assert diff.default_diff is not None

    def test_compare_column_details_identity_diff(self):
        """Test _compare_column_details with identity difference."""
        expected_col = SqlColumn("id", "INTEGER")
        expected_col.is_identity = True

        actual_col = SqlColumn("id", "INTEGER")
        actual_col.is_identity = False

        diff = self.comparator._compare_column_details(expected_col, actual_col, "postgresql")

        assert diff is not None
        assert diff.identity_diff is not None

    def test_compare_column_details_computed_flag_diff(self):
        """Test _compare_column_details with computed flag difference."""
        expected_col = SqlColumn("full_name", "VARCHAR(200)")
        expected_col.is_computed = True
        expected_col.computed_expression = "first_name || last_name"

        actual_col = SqlColumn("full_name", "VARCHAR(200)")
        actual_col.is_computed = False

        diff = self.comparator._compare_column_details(expected_col, actual_col, "postgresql")

        assert diff is not None
        assert diff.computed_diff is not None
        assert diff.computed_diff == (True, False)

    def test_compare_column_details_collation_diff(self):
        """Test _compare_column_details with collation difference."""
        expected_col = SqlColumn("name", "VARCHAR(100)")
        expected_col.collation = "en_US.utf8"

        actual_col = SqlColumn("name", "VARCHAR(100)")
        actual_col.collation = "C"

        diff = self.comparator._compare_column_details(expected_col, actual_col, "postgresql")

        assert diff is not None
        assert diff.collation_diff == ("en_US.utf8", "C")

    def test_compare_constraint_details_columns_diff(self):
        """Test _compare_constraint_details with column difference."""
        expected_const = SqlConstraint(
            name="pk_users",
            constraint_type=ConstraintType.PRIMARY_KEY,
            column_names=["id", "version"],
        )

        actual_const = SqlConstraint(
            name="pk_users", constraint_type=ConstraintType.PRIMARY_KEY, column_names=["id"]
        )

        diff = self.comparator._compare_constraint_details(expected_const, actual_const)

        assert diff is not None
        assert diff.columns_diff is not None

    def test_compare_constraint_details_references_diff(self):
        """Test _compare_constraint_details with foreign key reference difference."""
        expected_const = SqlConstraint(
            name="fk_orders_users",
            constraint_type=ConstraintType.FOREIGN_KEY,
            column_names=["user_id"],
            reference_table="users",
            reference_columns=["id"],
        )

        actual_const = SqlConstraint(
            name="fk_orders_users",
            constraint_type=ConstraintType.FOREIGN_KEY,
            column_names=["user_id"],
            reference_table="customers",
            reference_columns=["id"],
        )

        diff = self.comparator._compare_constraint_details(expected_const, actual_const)

        assert diff is not None
        assert diff.references_diff is not None

    def test_compare_constraint_details_check_clause_diff(self):
        """Test _compare_constraint_details with check clause difference."""
        expected_const = SqlConstraint(
            name="chk_age",
            constraint_type=ConstraintType.CHECK,
            column_names=["age"],
            check_expression="age > 0",
        )

        actual_const = SqlConstraint(
            name="chk_age",
            constraint_type=ConstraintType.CHECK,
            column_names=["age"],
            check_expression="age >= 0",
        )

        diff = self.comparator._compare_constraint_details(expected_const, actual_const)

        assert diff is not None
        assert diff.check_clause_diff is not None

    def test_compare_constraint_details_enabled_diff(self):
        """Test _compare_constraint_details with enabled difference."""
        expected_const = SqlConstraint(
            name="pk_users", constraint_type=ConstraintType.PRIMARY_KEY, column_names=["id"]
        )
        expected_const.is_enabled = True

        actual_const = SqlConstraint(
            name="pk_users", constraint_type=ConstraintType.PRIMARY_KEY, column_names=["id"]
        )
        actual_const.is_enabled = False

        diff = self.comparator._compare_constraint_details(expected_const, actual_const)

        assert diff is not None
        assert diff.enabled_diff == (True, False)

    def test_compare_constraint_details_validated_diff(self):
        """Test _compare_constraint_details with validated difference."""
        expected_const = SqlConstraint(
            name="pk_users", constraint_type=ConstraintType.PRIMARY_KEY, column_names=["id"]
        )
        expected_const.is_validated = True

        actual_const = SqlConstraint(
            name="pk_users", constraint_type=ConstraintType.PRIMARY_KEY, column_names=["id"]
        )
        actual_const.is_validated = False

        diff = self.comparator._compare_constraint_details(expected_const, actual_const)

        assert diff is not None
        assert diff.validated_diff == (True, False)

    def test_compare_constraint_details_deferrable_diff(self):
        """Test _compare_constraint_details with deferrable difference."""
        expected_const = SqlConstraint(
            name="pk_users", constraint_type=ConstraintType.PRIMARY_KEY, column_names=["id"]
        )
        expected_const.is_deferrable = True

        actual_const = SqlConstraint(
            name="pk_users", constraint_type=ConstraintType.PRIMARY_KEY, column_names=["id"]
        )
        actual_const.is_deferrable = False

        diff = self.comparator._compare_constraint_details(expected_const, actual_const)

        assert diff is not None
        assert diff.deferrable_diff == (True, False)
