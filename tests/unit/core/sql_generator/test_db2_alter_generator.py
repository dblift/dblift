"""Tests for DB2AlterGenerator class."""

import pytest

from core.sql_model.base import ConstraintType, SqlColumn, SqlConstraint
from core.sql_model.table import Table
from core.sql_model.view import View
from db.plugins.db2.generator.alter_generator import DB2AlterGenerator


@pytest.mark.unit
class TestDB2AlterGeneratorInit:
    """Tests for DB2AlterGenerator initialization."""

    def test_init(self):
        """Test initialization."""
        generator = DB2AlterGenerator()
        assert generator.dialect == "db2"


@pytest.mark.unit
class TestDB2AlterGeneratorFormatIdentifier:
    """Tests for _format_identifier method."""

    def test_format_identifier_simple(self):
        """Test formatting simple identifier."""
        generator = DB2AlterGenerator()
        result = generator._format_identifier("users")
        assert result == '"users"'


@pytest.mark.unit
class TestDB2AlterGeneratorAlterTable:
    """Tests for generate_alter_table_statements method."""

    def test_generate_alter_table_add_column(self):
        """Test generating ALTER TABLE ADD COLUMN."""
        generator = DB2AlterGenerator()
        table = Table(name="users", columns=[SqlColumn("id", "INTEGER")], dialect="db2")
        new_column = SqlColumn("email", "VARCHAR(100)")
        statements = generator.generate_alter_table_statements(table, add_columns=[new_column])
        assert len(statements) == 1
        assert "ADD COLUMN" in statements[0].upper()

    def test_generate_alter_table_modify_column(self):
        """Test generating ALTER TABLE ALTER COLUMN TYPE."""
        generator = DB2AlterGenerator()
        table = Table(name="users", columns=[SqlColumn("id", "INTEGER")], dialect="db2")
        modified_column = SqlColumn("id", "BIGINT")
        statements = generator.generate_alter_table_statements(
            table, modify_columns=[modified_column]
        )
        assert len(statements) == 1
        assert "ALTER COLUMN" in statements[0].upper()
        assert "TYPE" in statements[0].upper()


@pytest.mark.unit
class TestDB2AlterGeneratorAlterView:
    """Tests for generate_alter_view_statement method."""

    def test_generate_alter_view_statement_regular_view(self):
        """Test generating CREATE OR REPLACE VIEW for regular view."""
        generator = DB2AlterGenerator()
        view = View(name="active_users", query="SELECT 1", dialect="db2")
        result = generator.generate_alter_view_statement(view, "SELECT id FROM users")
        assert result is not None
        assert "CREATE OR REPLACE VIEW" in result.upper()

    def test_generate_alter_view_statement_materialized_view(self):
        """Test generating ALTER MATERIALIZED VIEW."""
        generator = DB2AlterGenerator()
        view = View(name="mv_users", query="SELECT 1", materialized=True, dialect="db2")
        result = generator.generate_alter_view_statement(view, "SELECT id FROM users")
        assert result is not None
        assert "ALTER MATERIALIZED VIEW" in result.upper()
