"""Tests for BaseAlterGenerator class."""

from unittest.mock import MagicMock

import pytest

from core.sql_generator.alter.base_alter_generator import BaseAlterGenerator
from core.sql_model.base import ConstraintType, SqlColumn, SqlConstraint


@pytest.mark.unit
class TestBaseAlterGeneratorInit:
    """Tests for BaseAlterGenerator initialization."""

    def test_init_lowercase_dialect(self):
        """Test initialization with lowercase dialect."""

        # Create a concrete implementation for testing
        class ConcreteAlterGenerator(BaseAlterGenerator):
            def generate_alter_table_statements(self, table, **kwargs):
                return []

            def generate_alter_view_statement(self, view, new_query=None):
                return None

            def _format_identifier(self, identifier: str) -> str:
                return identifier

        generator = ConcreteAlterGenerator("postgresql")
        assert generator.dialect == "postgresql"

    def test_init_uppercase_dialect(self):
        """Test initialization with uppercase dialect."""

        class ConcreteAlterGenerator(BaseAlterGenerator):
            def generate_alter_table_statements(self, table, **kwargs):
                return []

            def generate_alter_view_statement(self, view, new_query=None):
                return None

            def _format_identifier(self, identifier: str) -> str:
                return identifier

        generator = ConcreteAlterGenerator("POSTGRESQL")
        assert generator.dialect == "postgresql"


@pytest.mark.unit
class TestBaseAlterGeneratorFormatSchemaPrefix:
    """Tests for _format_schema_prefix method."""

    def test_format_schema_prefix_with_schema(self):
        """Test formatting schema prefix with schema."""

        class ConcreteAlterGenerator(BaseAlterGenerator):
            def generate_alter_table_statements(self, table, **kwargs):
                return []

            def generate_alter_view_statement(self, view, new_query=None):
                return None

            def _format_identifier(self, identifier: str) -> str:
                return f'"{identifier}"'

        generator = ConcreteAlterGenerator("postgresql")
        result = generator._format_schema_prefix("public")
        assert result == '"public".'

    def test_format_schema_prefix_none(self):
        """Test formatting schema prefix with None."""

        class ConcreteAlterGenerator(BaseAlterGenerator):
            def generate_alter_table_statements(self, table, **kwargs):
                return []

            def generate_alter_view_statement(self, view, new_query=None):
                return None

            def _format_identifier(self, identifier: str) -> str:
                return identifier

        generator = ConcreteAlterGenerator("postgresql")
        result = generator._format_schema_prefix(None)
        assert result == ""

    def test_format_schema_prefix_empty_string(self):
        """Test formatting schema prefix with empty string."""

        class ConcreteAlterGenerator(BaseAlterGenerator):
            def generate_alter_table_statements(self, table, **kwargs):
                return []

            def generate_alter_view_statement(self, view, new_query=None):
                return None

            def _format_identifier(self, identifier: str) -> str:
                return identifier

        generator = ConcreteAlterGenerator("postgresql")
        result = generator._format_schema_prefix("")
        assert result == ""


@pytest.mark.unit
class TestBaseAlterGeneratorFormatColumnDefinition:
    """Tests for _format_column_definition method."""

    def test_format_column_definition_simple(self):
        """Test formatting simple column definition."""

        class ConcreteAlterGenerator(BaseAlterGenerator):
            def generate_alter_table_statements(self, table, **kwargs):
                return []

            def generate_alter_view_statement(self, view, new_query=None):
                return None

            def _format_identifier(self, identifier: str) -> str:
                return identifier

        generator = ConcreteAlterGenerator("postgresql")
        column = SqlColumn("id", "INTEGER")
        result = generator._format_column_definition(column)
        assert "id" in result
        assert "INTEGER" in result
        assert "NOT NULL" not in result

    def test_format_column_definition_with_not_null(self):
        """Test formatting column definition with NOT NULL."""

        class ConcreteAlterGenerator(BaseAlterGenerator):
            def generate_alter_table_statements(self, table, **kwargs):
                return []

            def generate_alter_view_statement(self, view, new_query=None):
                return None

            def _format_identifier(self, identifier: str) -> str:
                return identifier

        generator = ConcreteAlterGenerator("postgresql")
        column = SqlColumn("id", "INTEGER", is_nullable=False)
        result = generator._format_column_definition(column)
        assert "NOT NULL" in result

    def test_format_column_definition_nullable_true_no_not_null(self):
        """Test that nullable=True does NOT produce NOT NULL."""

        class ConcreteAlterGenerator(BaseAlterGenerator):
            def generate_alter_table_statements(self, table, **kwargs):
                return []

            def generate_alter_view_statement(self, view, new_query=None):
                return None

            def _format_identifier(self, identifier: str) -> str:
                return identifier

        generator = ConcreteAlterGenerator("postgresql")
        column = SqlColumn("id", "INTEGER", is_nullable=True)
        result = generator._format_column_definition(column)
        assert "NOT NULL" not in result

    def test_format_column_definition_nullable_none_must_not_add_not_null(self):
        """nullable=None (unknown) must NOT be treated as NOT NULL."""

        class ConcreteAlterGenerator(BaseAlterGenerator):
            def generate_alter_table_statements(self, table, **kwargs):
                return []

            def generate_alter_view_statement(self, view, new_query=None):
                return None

            def _format_identifier(self, identifier: str) -> str:
                return identifier

        generator = ConcreteAlterGenerator("postgresql")
        column = SqlColumn("id", "INTEGER", is_nullable=True)
        column.nullable = None  # Simulate introspection with unknown nullability
        result = generator._format_column_definition(column)
        assert "NOT NULL" not in result

    def test_format_column_definition_with_default(self):
        """Test formatting column definition with DEFAULT."""

        class ConcreteAlterGenerator(BaseAlterGenerator):
            def generate_alter_table_statements(self, table, **kwargs):
                return []

            def generate_alter_view_statement(self, view, new_query=None):
                return None

            def _format_identifier(self, identifier: str) -> str:
                return identifier

        generator = ConcreteAlterGenerator("postgresql")
        column = SqlColumn("id", "INTEGER", default_value="1")
        result = generator._format_column_definition(column)
        assert "DEFAULT 1" in result

    def test_format_column_definition_no_data_type(self):
        """Test formatting column definition without data type."""

        class ConcreteAlterGenerator(BaseAlterGenerator):
            def generate_alter_table_statements(self, table, **kwargs):
                return []

            def generate_alter_view_statement(self, view, new_query=None):
                return None

            def _format_identifier(self, identifier: str) -> str:
                return identifier

        generator = ConcreteAlterGenerator("postgresql")
        column = SqlColumn("id", None)
        result = generator._format_column_definition(column)
        assert "VARCHAR(255)" in result  # Default fallback


@pytest.mark.unit
class TestBaseAlterGeneratorFormatConstraintDefinition:
    """Tests for _format_constraint_definition method."""

    def test_format_constraint_definition_primary_key(self):
        """Test formatting PRIMARY KEY constraint."""

        class ConcreteAlterGenerator(BaseAlterGenerator):
            def generate_alter_table_statements(self, table, **kwargs):
                return []

            def generate_alter_view_statement(self, view, new_query=None):
                return None

            def _format_identifier(self, identifier: str) -> str:
                return identifier

        generator = ConcreteAlterGenerator("postgresql")
        constraint = SqlConstraint(
            name="pk_test",
            constraint_type=ConstraintType.PRIMARY_KEY,
            column_names=["id"],
        )
        result = generator._format_constraint_definition(constraint)
        assert result is not None
        assert "PRIMARY KEY" in result
        assert "id" in result

    def test_format_constraint_definition_foreign_key(self):
        """Test formatting FOREIGN KEY constraint."""

        class ConcreteAlterGenerator(BaseAlterGenerator):
            def generate_alter_table_statements(self, table, **kwargs):
                return []

            def generate_alter_view_statement(self, view, new_query=None):
                return None

            def _format_identifier(self, identifier: str) -> str:
                return identifier

        generator = ConcreteAlterGenerator("postgresql")
        constraint = SqlConstraint(
            name="fk_test",
            constraint_type=ConstraintType.FOREIGN_KEY,
            column_names=["user_id"],
            reference_table="users",
            reference_columns=["id"],
        )
        result = generator._format_constraint_definition(constraint)
        assert result is not None
        assert "FOREIGN KEY" in result
        assert "REFERENCES" in result
        assert "users" in result

    def test_format_constraint_definition_foreign_key_with_schema(self):
        """Test formatting FOREIGN KEY constraint with reference schema."""

        class ConcreteAlterGenerator(BaseAlterGenerator):
            def generate_alter_table_statements(self, table, **kwargs):
                return []

            def generate_alter_view_statement(self, view, new_query=None):
                return None

            def _format_identifier(self, identifier: str) -> str:
                return identifier

        generator = ConcreteAlterGenerator("postgresql")
        constraint = SqlConstraint(
            name="fk_test",
            constraint_type=ConstraintType.FOREIGN_KEY,
            column_names=["user_id"],
            reference_table="users",
            reference_columns=["id"],
        )
        # Set reference_schema as an attribute (not a constructor parameter)
        constraint.reference_schema = "public"
        result = generator._format_constraint_definition(constraint)
        assert result is not None
        assert "public.users" in result or '"public"."users"' in result

    def test_format_constraint_definition_foreign_key_no_reference_table(self):
        """Test formatting FOREIGN KEY constraint without reference table."""

        class ConcreteAlterGenerator(BaseAlterGenerator):
            def generate_alter_table_statements(self, table, **kwargs):
                return []

            def generate_alter_view_statement(self, view, new_query=None):
                return None

            def _format_identifier(self, identifier: str) -> str:
                return identifier

        generator = ConcreteAlterGenerator("postgresql")
        constraint = SqlConstraint(
            name="fk_test",
            constraint_type=ConstraintType.FOREIGN_KEY,
            column_names=["user_id"],
            reference_columns=["id"],
        )
        result = generator._format_constraint_definition(constraint)
        assert result is None

    def test_format_constraint_definition_unique(self):
        """Test formatting UNIQUE constraint."""

        class ConcreteAlterGenerator(BaseAlterGenerator):
            def generate_alter_table_statements(self, table, **kwargs):
                return []

            def generate_alter_view_statement(self, view, new_query=None):
                return None

            def _format_identifier(self, identifier: str) -> str:
                return identifier

        generator = ConcreteAlterGenerator("postgresql")
        constraint = SqlConstraint(
            name="uk_email",
            constraint_type=ConstraintType.UNIQUE,
            column_names=["email"],
        )
        result = generator._format_constraint_definition(constraint)
        assert result is not None
        assert "UNIQUE" in result
        assert "email" in result

    def test_format_constraint_definition_unique_with_name(self):
        """Test formatting UNIQUE constraint with name."""

        class ConcreteAlterGenerator(BaseAlterGenerator):
            def generate_alter_table_statements(self, table, **kwargs):
                return []

            def generate_alter_view_statement(self, view, new_query=None):
                return None

            def _format_identifier(self, identifier: str) -> str:
                return identifier

        generator = ConcreteAlterGenerator("postgresql")
        constraint = SqlConstraint(
            name="uk_email",
            constraint_type=ConstraintType.UNIQUE,
            column_names=["email"],
        )
        result = generator._format_constraint_definition(constraint)
        assert "CONSTRAINT" in result
        assert "uk_email" in result

    def test_format_constraint_definition_check(self):
        """Test formatting CHECK constraint."""

        class ConcreteAlterGenerator(BaseAlterGenerator):
            def generate_alter_table_statements(self, table, **kwargs):
                return []

            def generate_alter_view_statement(self, view, new_query=None):
                return None

            def _format_identifier(self, identifier: str) -> str:
                return identifier

        generator = ConcreteAlterGenerator("postgresql")
        constraint = SqlConstraint(
            name="ck_age",
            constraint_type=ConstraintType.CHECK,
            column_names=["age", ">=", "0"],
        )
        result = generator._format_constraint_definition(constraint)
        assert result is not None
        assert "CHECK" in result
        assert "age >= 0" in result

    def test_format_constraint_definition_check_no_columns(self):
        """Test formatting CHECK constraint without columns."""

        class ConcreteAlterGenerator(BaseAlterGenerator):
            def generate_alter_table_statements(self, table, **kwargs):
                return []

            def generate_alter_view_statement(self, view, new_query=None):
                return None

            def _format_identifier(self, identifier: str) -> str:
                return identifier

        generator = ConcreteAlterGenerator("postgresql")
        constraint = SqlConstraint(
            name="ck_test",
            constraint_type=ConstraintType.CHECK,
            column_names=[],
        )
        result = generator._format_constraint_definition(constraint)
        assert result is not None
        assert "CHECK" in result
        assert "1=1" in result  # Default fallback

    def test_format_constraint_definition_check_with_name(self):
        """Test formatting CHECK constraint with name."""

        class ConcreteAlterGenerator(BaseAlterGenerator):
            def generate_alter_table_statements(self, table, **kwargs):
                return []

            def generate_alter_view_statement(self, view, new_query=None):
                return None

            def _format_identifier(self, identifier: str) -> str:
                return identifier

        generator = ConcreteAlterGenerator("postgresql")
        constraint = SqlConstraint(
            name="ck_age",
            constraint_type=ConstraintType.CHECK,
            column_names=["age", ">=", "0"],
        )
        result = generator._format_constraint_definition(constraint)
        assert "CONSTRAINT" in result
        assert "ck_age" in result

    def test_format_constraint_definition_unknown_type(self):
        """Test formatting unknown constraint type."""

        class ConcreteAlterGenerator(BaseAlterGenerator):
            def generate_alter_table_statements(self, table, **kwargs):
                return []

            def generate_alter_view_statement(self, view, new_query=None):
                return None

            def _format_identifier(self, identifier: str) -> str:
                return identifier

        generator = ConcreteAlterGenerator("postgresql")
        constraint = SqlConstraint(
            name="unknown_constraint",
            constraint_type="UNKNOWN_TYPE",
            column_names=["id"],
        )
        result = generator._format_constraint_definition(constraint)
        assert result is None

    def test_format_constraint_definition_primary_key_multiple_columns(self):
        """Test formatting PRIMARY KEY constraint with multiple columns."""

        class ConcreteAlterGenerator(BaseAlterGenerator):
            def generate_alter_table_statements(self, table, **kwargs):
                return []

            def generate_alter_view_statement(self, view, new_query=None):
                return None

            def _format_identifier(self, identifier: str) -> str:
                return identifier

        generator = ConcreteAlterGenerator("postgresql")
        constraint = SqlConstraint(
            name="pk_test",
            constraint_type=ConstraintType.PRIMARY_KEY,
            column_names=["id", "name"],
        )
        result = generator._format_constraint_definition(constraint)
        assert result is not None
        assert "PRIMARY KEY" in result
        assert "id" in result
        assert "name" in result

    def test_format_constraint_definition_foreign_key_multiple_columns(self):
        """Test formatting FOREIGN KEY constraint with multiple columns."""

        class ConcreteAlterGenerator(BaseAlterGenerator):
            def generate_alter_table_statements(self, table, **kwargs):
                return []

            def generate_alter_view_statement(self, view, new_query=None):
                return None

            def _format_identifier(self, identifier: str) -> str:
                return identifier

        generator = ConcreteAlterGenerator("postgresql")
        constraint = SqlConstraint(
            name="fk_test",
            constraint_type=ConstraintType.FOREIGN_KEY,
            column_names=["user_id", "order_id"],
            reference_table="users",
            reference_columns=["id", "order_num"],
        )
        result = generator._format_constraint_definition(constraint)
        assert result is not None
        assert "FOREIGN KEY" in result
        assert "user_id" in result
        assert "order_id" in result

    def test_format_constraint_definition_unique_multiple_columns(self):
        """Test formatting UNIQUE constraint with multiple columns."""

        class ConcreteAlterGenerator(BaseAlterGenerator):
            def generate_alter_table_statements(self, table, **kwargs):
                return []

            def generate_alter_view_statement(self, view, new_query=None):
                return None

            def _format_identifier(self, identifier: str) -> str:
                return identifier

        generator = ConcreteAlterGenerator("postgresql")
        constraint = SqlConstraint(
            name="uk_email_name",
            constraint_type=ConstraintType.UNIQUE,
            column_names=["email", "name"],
        )
        result = generator._format_constraint_definition(constraint)
        assert result is not None
        assert "UNIQUE" in result
        assert "email" in result
        assert "name" in result

    def test_format_constraint_definition_unique_no_name(self):
        """Test formatting UNIQUE constraint without name."""

        class ConcreteAlterGenerator(BaseAlterGenerator):
            def generate_alter_table_statements(self, table, **kwargs):
                return []

            def generate_alter_view_statement(self, view, new_query=None):
                return None

            def _format_identifier(self, identifier: str) -> str:
                return identifier

        generator = ConcreteAlterGenerator("postgresql")
        constraint = SqlConstraint(
            name=None,
            constraint_type=ConstraintType.UNIQUE,
            column_names=["email"],
        )
        result = generator._format_constraint_definition(constraint)
        assert result is not None
        assert "UNIQUE" in result
        assert "CONSTRAINT" not in result

    def test_format_constraint_definition_check_no_name(self):
        """Test formatting CHECK constraint without name."""

        class ConcreteAlterGenerator(BaseAlterGenerator):
            def generate_alter_table_statements(self, table, **kwargs):
                return []

            def generate_alter_view_statement(self, view, new_query=None):
                return None

            def _format_identifier(self, identifier: str) -> str:
                return identifier

        generator = ConcreteAlterGenerator("postgresql")
        constraint = SqlConstraint(
            name=None,
            constraint_type=ConstraintType.CHECK,
            column_names=["age", ">=", "0"],
        )
        result = generator._format_constraint_definition(constraint)
        assert result is not None
        assert "CHECK" in result
        assert "CONSTRAINT" not in result

    def test_format_constraint_definition_foreign_key_no_name(self):
        """Test formatting FOREIGN KEY constraint without name."""

        class ConcreteAlterGenerator(BaseAlterGenerator):
            def generate_alter_table_statements(self, table, **kwargs):
                return []

            def generate_alter_view_statement(self, view, new_query=None):
                return None

            def _format_identifier(self, identifier: str) -> str:
                return identifier

        generator = ConcreteAlterGenerator("postgresql")
        constraint = SqlConstraint(
            name=None,
            constraint_type=ConstraintType.FOREIGN_KEY,
            column_names=["user_id"],
            reference_table="users",
            reference_columns=["id"],
        )
        result = generator._format_constraint_definition(constraint)
        assert result is not None
        assert "FOREIGN KEY" in result
        assert "CONSTRAINT" not in result
