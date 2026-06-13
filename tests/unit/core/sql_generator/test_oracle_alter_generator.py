"""Tests for OracleAlterGenerator class."""

import pytest

from core.sql_model.base import ConstraintType, SqlColumn, SqlConstraint
from core.sql_model.table import Table
from core.sql_model.view import View
from db.plugins.oracle.generator.alter_generator import OracleAlterGenerator


@pytest.mark.unit
class TestOracleAlterGeneratorInit:
    """Tests for OracleAlterGenerator initialization."""

    def test_init(self):
        """Test initialization."""
        generator = OracleAlterGenerator()
        assert generator.dialect == "oracle"


@pytest.mark.unit
class TestOracleAlterGeneratorFormatIdentifier:
    """Tests for _format_identifier method."""

    def test_format_identifier_simple(self):
        """Test formatting simple identifier."""
        generator = OracleAlterGenerator()
        result = generator._format_identifier("users")
        assert result == '"users"'


@pytest.mark.unit
class TestOracleAlterGeneratorFormatColumnDefinition:
    """Tests for _format_column_definition method."""

    def test_format_column_definition_with_null(self):
        """Test formatting column definition with explicit NULL (Oracle).

        Oracle requires explicit NULL for nullable columns. Verify NOT NULL is absent
        to guard against regression (since 'NOT NULL' contains 'NULL').
        """
        generator = OracleAlterGenerator()
        column = SqlColumn("id", "INTEGER", is_nullable=True)
        result = generator._format_column_definition(column)
        assert "NULL" in result
        assert "NOT NULL" not in result

    def test_format_column_definition_with_not_null(self):
        """Test formatting column definition with NOT NULL."""
        generator = OracleAlterGenerator()
        column = SqlColumn("id", "INTEGER", is_nullable=False)
        result = generator._format_column_definition(column)
        assert "NOT NULL" in result

    def test_format_column_definition_with_default(self):
        """Test formatting column definition with DEFAULT."""
        generator = OracleAlterGenerator()
        column = SqlColumn("id", "INTEGER", default_value="1")
        result = generator._format_column_definition(column)
        assert "DEFAULT 1" in result


@pytest.mark.unit
class TestOracleAlterGeneratorAlterTable:
    """Tests for generate_alter_table_statements method."""

    def test_generate_alter_table_add_column(self):
        """Test generating ALTER TABLE ADD COLUMN."""
        generator = OracleAlterGenerator()
        table = Table(name="users", columns=[SqlColumn("id", "INTEGER")], dialect="oracle")
        new_column = SqlColumn("email", "VARCHAR2(100)")
        statements = generator.generate_alter_table_statements(table, add_columns=[new_column])
        assert len(statements) == 1
        assert "ADD COLUMN" in statements[0].upper()

    def test_generate_alter_table_modify_column(self):
        """Test generating ALTER TABLE MODIFY."""
        generator = OracleAlterGenerator()
        table = Table(name="users", columns=[SqlColumn("id", "INTEGER")], dialect="oracle")
        modified_column = SqlColumn("id", "NUMBER")
        statements = generator.generate_alter_table_statements(
            table, modify_columns=[modified_column]
        )
        assert len(statements) == 1
        assert "MODIFY" in statements[0].upper()

    def test_generate_alter_table_drop_constraint(self):
        """Test generating ALTER TABLE DROP CONSTRAINT."""
        generator = OracleAlterGenerator()
        table = Table(name="users", columns=[SqlColumn("id", "INTEGER")], dialect="oracle")
        statements = generator.generate_alter_table_statements(table, drop_constraints=["pk_users"])
        assert len(statements) == 1
        assert "DROP CONSTRAINT" in statements[0].upper()


@pytest.mark.unit
class TestOracleAlterGeneratorAlterView:
    """Tests for generate_alter_view_statement method."""

    def test_generate_alter_view_statement_regular_view(self):
        """Test generating CREATE OR REPLACE VIEW for regular view."""
        generator = OracleAlterGenerator()
        view = View(name="active_users", query="SELECT 1", dialect="oracle")
        result = generator.generate_alter_view_statement(view, "SELECT id FROM users")
        assert result is not None
        assert "CREATE OR REPLACE VIEW" in result.upper()

    def test_generate_alter_view_statement_materialized_view(self):
        """Test generating CREATE MATERIALIZED VIEW (no OR REPLACE)."""
        generator = OracleAlterGenerator()
        view = View(name="mv_users", query="SELECT 1", materialized=True, dialect="oracle")
        result = generator.generate_alter_view_statement(view, "SELECT id FROM users")
        assert result is not None
        assert "CREATE MATERIALIZED VIEW" in result.upper()
        assert "OR REPLACE" not in result.upper()
