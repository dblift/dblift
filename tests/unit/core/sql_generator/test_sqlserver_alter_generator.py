"""Tests for SQLServerAlterGenerator class."""

import pytest

from core.sql_model.base import ConstraintType, SqlColumn, SqlConstraint
from core.sql_model.table import Table
from core.sql_model.view import View
from db.plugins.sqlserver.generator.alter_generator import SQLServerAlterGenerator


@pytest.mark.unit
class TestSQLServerAlterGeneratorInit:
    """Tests for SQLServerAlterGenerator initialization."""

    def test_init(self):
        """Test initialization."""
        generator = SQLServerAlterGenerator()
        assert generator.dialect == "sqlserver"


@pytest.mark.unit
class TestSQLServerAlterGeneratorFormatIdentifier:
    """Tests for _format_identifier method."""

    def test_format_identifier_simple(self):
        """Test formatting simple identifier."""
        generator = SQLServerAlterGenerator()
        result = generator._format_identifier("users")
        assert result == "[users]"

    def test_format_identifier_with_special_chars(self):
        """Test formatting identifier with special characters."""
        generator = SQLServerAlterGenerator()
        result = generator._format_identifier("user-name")
        assert result == "[user-name]"


@pytest.mark.unit
class TestSQLServerAlterGeneratorAlterTable:
    """Tests for generate_alter_table_statements method."""

    def test_generate_alter_table_add_column(self):
        """Test generating ALTER TABLE ADD COLUMN."""
        generator = SQLServerAlterGenerator()
        table = Table(name="users", columns=[SqlColumn("id", "INTEGER")], dialect="sqlserver")
        new_column = SqlColumn("email", "VARCHAR(100)")
        statements = generator.generate_alter_table_statements(table, add_columns=[new_column])
        assert len(statements) == 1
        assert "ALTER TABLE" in statements[0].upper()
        assert "ADD COLUMN" in statements[0].upper()

    def test_generate_alter_table_modify_column(self):
        """Test generating ALTER TABLE ALTER COLUMN."""
        generator = SQLServerAlterGenerator()
        table = Table(name="users", columns=[SqlColumn("id", "INTEGER")], dialect="sqlserver")
        modified_column = SqlColumn("id", "BIGINT")
        statements = generator.generate_alter_table_statements(
            table, modify_columns=[modified_column]
        )
        assert len(statements) == 1
        assert "ALTER COLUMN" in statements[0].upper()

    def test_generate_alter_table_drop_constraint(self):
        """Test generating ALTER TABLE DROP CONSTRAINT."""
        generator = SQLServerAlterGenerator()
        table = Table(name="users", columns=[SqlColumn("id", "INTEGER")], dialect="sqlserver")
        statements = generator.generate_alter_table_statements(table, drop_constraints=["pk_users"])
        assert len(statements) == 1
        assert "DROP CONSTRAINT" in statements[0].upper()


@pytest.mark.unit
class TestSQLServerAlterGeneratorAlterView:
    """Tests for generate_alter_view_statement method."""

    def test_generate_alter_view_statement_regular_view(self):
        """Test generating ALTER VIEW for regular view."""
        generator = SQLServerAlterGenerator()
        view = View(name="active_users", query="SELECT 1", dialect="sqlserver")
        result = generator.generate_alter_view_statement(view, "SELECT id FROM users")
        assert result is not None
        assert "ALTER VIEW" in result.upper()

    def test_generate_alter_view_statement_materialized_view(self):
        """Test generating ALTER MATERIALIZED VIEW."""
        generator = SQLServerAlterGenerator()
        view = View(name="mv_users", query="SELECT 1", materialized=True, dialect="sqlserver")
        result = generator.generate_alter_view_statement(view, "SELECT id FROM users")
        assert result is not None
        assert "ALTER MATERIALIZED VIEW" in result.upper()

    def test_generate_alter_view_statement_no_new_query(self):
        """Test generating ALTER VIEW without new query."""
        generator = SQLServerAlterGenerator()
        view = View(name="active_users", query="SELECT 1", dialect="sqlserver")
        result = generator.generate_alter_view_statement(view, None)
        assert result is None
