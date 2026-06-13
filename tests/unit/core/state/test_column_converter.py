"""Unit tests for column converter."""

import pytest

from core.comparison.diff_models import ColumnDiff, DiffSeverity
from core.sql_generator.diff_converters.column_converter import ColumnConverter
from core.sql_generator.sql_statement import GenerationOptions

pytestmark = [pytest.mark.unit]


class TestColumnConverter:
    """Test cases for ColumnConverter."""

    def test_nullable_change_postgresql_set_not_null(self):
        """Test setting NOT NULL on PostgreSQL."""
        converter = ColumnConverter(dialect="postgresql")
        options = GenerationOptions(dialect="postgresql")

        column_diff = ColumnDiff(
            object_name="test_column",
            column_name="test_column",
            nullable_diff=(False, True),  # Setting NOT NULL
        )

        statements = converter.convert(column_diff, "public.test_table", options)

        assert len(statements) == 1
        assert statements[0].statement_type == "ALTER"
        assert statements[0].object_type == "COLUMN"
        assert "SET NOT NULL" in statements[0].sql
        assert statements[0].pre_check is not None
        assert statements[0].error_if_check_fails is True

    def test_nullable_change_postgresql_drop_not_null(self):
        """Test dropping NOT NULL on PostgreSQL."""
        converter = ColumnConverter(dialect="postgresql")
        options = GenerationOptions(dialect="postgresql")

        column_diff = ColumnDiff(
            object_name="test_column",
            column_name="test_column",
            nullable_diff=(True, False),  # Dropping NOT NULL
        )

        statements = converter.convert(column_diff, "public.test_table", options)

        assert len(statements) == 1
        assert statements[0].statement_type == "ALTER"
        assert "DROP NOT NULL" in statements[0].sql
        assert statements[0].pre_check is None

    def test_nullable_change_oracle(self):
        """Test nullable change on Oracle."""
        converter = ColumnConverter(dialect="oracle")
        options = GenerationOptions(dialect="oracle")

        column_diff = ColumnDiff(
            object_name="test_column",
            column_name="test_column",
            nullable_diff=(False, True),  # Setting NOT NULL
        )

        statements = converter.convert(column_diff, "schema.test_table", options)

        assert len(statements) == 1
        assert "MODIFY" in statements[0].sql
        assert "NOT NULL" in statements[0].sql

    def test_default_change_postgresql_set_default(self):
        """Test setting default value on PostgreSQL."""
        converter = ColumnConverter(dialect="postgresql")
        options = GenerationOptions(dialect="postgresql")

        column_diff = ColumnDiff(
            object_name="test_column",
            column_name="test_column",
            default_diff=("'default_value'", None),
        )

        statements = converter.convert(column_diff, "public.test_table", options)

        assert len(statements) == 1
        assert "SET DEFAULT" in statements[0].sql
        assert "'default_value'" in statements[0].sql

    def test_default_change_postgresql_drop_default(self):
        """Test dropping default value on PostgreSQL."""
        converter = ColumnConverter(dialect="postgresql")
        options = GenerationOptions(dialect="postgresql")

        column_diff = ColumnDiff(
            object_name="test_column",
            column_name="test_column",
            default_diff=(None, "'old_default'"),
        )

        statements = converter.convert(column_diff, "public.test_table", options)

        assert len(statements) == 1
        assert "DROP DEFAULT" in statements[0].sql

    def test_type_change_postgresql(self):
        """Test type change on PostgreSQL."""
        converter = ColumnConverter(dialect="postgresql")
        options = GenerationOptions(dialect="postgresql")

        column_diff = ColumnDiff(
            object_name="test_column",
            column_name="test_column",
            data_type_diff=("VARCHAR(200)", "VARCHAR(100)"),
        )

        statements = converter.convert(column_diff, "public.test_table", options)

        assert len(statements) == 1
        assert "TYPE" in statements[0].sql
        assert "VARCHAR(200)" in statements[0].sql

    def test_collation_change_postgresql(self):
        """Test collation change on PostgreSQL."""
        converter = ColumnConverter(dialect="postgresql")
        options = GenerationOptions(dialect="postgresql")

        column_diff = ColumnDiff(
            object_name="test_column",
            column_name="test_column",
            collation_diff=("en_US", "C"),
        )

        statements = converter.convert(column_diff, "public.test_table", options)

        assert len(statements) == 1
        assert "SET COLLATION" in statements[0].sql
        assert "en_US" in statements[0].sql

    def test_multiple_changes(self):
        """Test multiple column changes in one diff."""
        converter = ColumnConverter(dialect="postgresql")
        options = GenerationOptions(dialect="postgresql")

        column_diff = ColumnDiff(
            object_name="test_column",
            column_name="test_column",
            nullable_diff=(False, True),
            default_diff=("'default'", None),
        )

        statements = converter.convert(column_diff, "public.test_table", options)

        assert len(statements) == 2
        assert any("SET NOT NULL" in stmt.sql for stmt in statements)
        assert any("SET DEFAULT" in stmt.sql for stmt in statements)

    def test_table_name_parsing(self):
        """Test parsing of table names with and without schema."""
        converter = ColumnConverter(dialect="postgresql")
        options = GenerationOptions(dialect="postgresql")

        column_diff = ColumnDiff(
            object_name="test_column",
            column_name="test_column",
            nullable_diff=(False, True),
        )

        # Test with schema
        statements = converter.convert(column_diff, "public.test_table", options)
        assert '"public"' in statements[0].sql
        assert '"test_table"' in statements[0].sql

        # Test without schema
        statements = converter.convert(column_diff, "test_table", options)
        assert '"test_table"' in statements[0].sql
        assert '"public"' not in statements[0].sql
