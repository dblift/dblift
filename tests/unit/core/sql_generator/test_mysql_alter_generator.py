"""Tests for MySQLAlterGenerator class."""

import pytest

from core.sql_model.base import ConstraintType, SqlColumn, SqlConstraint
from core.sql_model.table import Table
from core.sql_model.view import View
from db.plugins.mysql.generator.alter_generator import MySQLAlterGenerator


@pytest.mark.unit
class TestMySQLAlterGeneratorInit:
    """Tests for MySQLAlterGenerator initialization."""

    def test_init(self):
        """Test initialization."""
        generator = MySQLAlterGenerator()
        assert generator.dialect == "mysql"


@pytest.mark.unit
class TestMySQLAlterGeneratorFormatIdentifier:
    """Tests for _format_identifier method."""

    def test_format_identifier_simple(self):
        """Test formatting simple identifier."""
        generator = MySQLAlterGenerator()
        result = generator._format_identifier("users")
        assert result == "`users`"

    def test_format_identifier_with_special_chars(self):
        """Test formatting identifier with special characters."""
        generator = MySQLAlterGenerator()
        result = generator._format_identifier("user-name")
        assert result == "`user-name`"


@pytest.mark.unit
class TestMySQLAlterGeneratorAlterTable:
    """Tests for generate_alter_table_statements method."""

    def test_generate_alter_table_add_column(self):
        """Test generating ALTER TABLE ADD COLUMN."""
        generator = MySQLAlterGenerator()
        table = Table(name="users", columns=[SqlColumn("id", "INTEGER")], dialect="mysql")
        new_column = SqlColumn("email", "VARCHAR(100)")
        statements = generator.generate_alter_table_statements(table, add_columns=[new_column])
        assert len(statements) == 1
        assert "ALTER TABLE" in statements[0].upper()
        assert "ADD COLUMN" in statements[0].upper()

    def test_generate_alter_table_drop_column(self):
        """Test generating ALTER TABLE DROP COLUMN."""
        generator = MySQLAlterGenerator()
        table = Table(name="users", columns=[SqlColumn("id", "INTEGER")], dialect="mysql")
        statements = generator.generate_alter_table_statements(table, drop_columns=["email"])
        assert len(statements) == 1
        assert "DROP COLUMN" in statements[0].upper()

    def test_generate_alter_table_modify_column(self):
        """Test generating ALTER TABLE ALTER COLUMN TYPE."""
        generator = MySQLAlterGenerator()
        table = Table(name="users", columns=[SqlColumn("id", "INTEGER")], dialect="mysql")
        modified_column = SqlColumn("id", "BIGINT")
        statements = generator.generate_alter_table_statements(
            table, modify_columns=[modified_column]
        )
        assert len(statements) == 1
        assert "ALTER COLUMN" in statements[0].upper()
        assert "TYPE" in statements[0].upper()

    def test_generate_alter_table_add_constraint(self):
        """Test generating ALTER TABLE ADD CONSTRAINT."""
        generator = MySQLAlterGenerator()
        table = Table(name="users", columns=[SqlColumn("id", "INTEGER")], dialect="mysql")
        constraint = SqlConstraint(
            name="pk_users",
            constraint_type=ConstraintType.PRIMARY_KEY,
            column_names=["id"],
        )
        statements = generator.generate_alter_table_statements(table, add_constraints=[constraint])
        assert len(statements) == 1
        assert "ADD" in statements[0].upper()

    def test_generate_alter_table_drop_constraint_foreign_key(self):
        """Test generating ALTER TABLE DROP FOREIGN KEY."""
        generator = MySQLAlterGenerator()
        table = Table(name="users", columns=[SqlColumn("id", "INTEGER")], dialect="mysql")
        statements = generator.generate_alter_table_statements(table, drop_constraints=["fk_users"])
        assert len(statements) == 1
        assert "DROP FOREIGN KEY" in statements[0].upper()


@pytest.mark.unit
class TestMySQLAlterGeneratorAlterView:
    """Tests for generate_alter_view_statement method."""

    def test_generate_alter_view_statement_regular_view(self):
        """Test generating ALTER VIEW for regular view."""
        generator = MySQLAlterGenerator()
        view = View(name="active_users", query="SELECT 1", dialect="mysql")
        result = generator.generate_alter_view_statement(view, "SELECT id FROM users")
        assert result is not None
        assert "ALTER VIEW" in result.upper()

    def test_generate_alter_view_statement_materialized_view(self):
        """Test generating ALTER MATERIALIZED VIEW."""
        generator = MySQLAlterGenerator()
        view = View(name="mv_users", query="SELECT 1", materialized=True, dialect="mysql")
        result = generator.generate_alter_view_statement(view, "SELECT id FROM users")
        assert result is not None
        assert "ALTER MATERIALIZED VIEW" in result.upper()

    def test_generate_alter_view_statement_no_new_query(self):
        """Test generating ALTER VIEW without new query."""
        generator = MySQLAlterGenerator()
        view = View(name="active_users", query="SELECT 1", dialect="mysql")
        result = generator.generate_alter_view_statement(view, None)
        assert result is None
