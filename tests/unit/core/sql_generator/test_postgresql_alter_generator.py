"""Tests for PostgreSQLAlterGenerator class."""

import pytest

from core.sql_model.base import ConstraintType, SqlColumn, SqlConstraint
from core.sql_model.table import Table
from core.sql_model.view import View
from db.plugins.postgresql.generator.alter_generator import PostgreSQLAlterGenerator


@pytest.mark.unit
class TestPostgreSQLAlterGeneratorInit:
    """Tests for PostgreSQLAlterGenerator initialization."""

    def test_init(self):
        """Test initialization."""
        generator = PostgreSQLAlterGenerator()
        assert generator.dialect == "postgresql"

    def test_init_with_dialect(self):
        """Test initialization with explicit dialect."""
        generator = PostgreSQLAlterGenerator("postgresql")
        assert generator.dialect == "postgresql"


@pytest.mark.unit
class TestPostgreSQLAlterGeneratorFormatIdentifier:
    """Tests for _format_identifier method."""

    def test_format_identifier_simple(self):
        """Test formatting simple identifier."""
        generator = PostgreSQLAlterGenerator()
        result = generator._format_identifier("users")
        assert result == '"users"'

    def test_format_identifier_with_special_chars(self):
        """Test formatting identifier with special characters."""
        generator = PostgreSQLAlterGenerator()
        result = generator._format_identifier("user-name")
        assert result == '"user-name"'


@pytest.mark.unit
class TestPostgreSQLAlterGeneratorAlterTable:
    """Tests for generate_alter_table_statements method."""

    def test_generate_alter_table_add_column(self):
        """Test generating ALTER TABLE ADD COLUMN."""
        generator = PostgreSQLAlterGenerator()
        table = Table(name="users", columns=[SqlColumn("id", "INTEGER")], dialect="postgresql")
        new_column = SqlColumn("email", "VARCHAR(100)")
        statements = generator.generate_alter_table_statements(table, add_columns=[new_column])
        assert len(statements) == 1
        assert "ALTER TABLE" in statements[0].upper()
        assert "ADD COLUMN" in statements[0].upper()
        assert "email" in statements[0].lower() or '"email"' in statements[0]

    def test_generate_alter_table_add_multiple_columns(self):
        """Test generating ALTER TABLE ADD COLUMN for multiple columns."""
        generator = PostgreSQLAlterGenerator()
        table = Table(name="users", columns=[SqlColumn("id", "INTEGER")], dialect="postgresql")
        columns = [
            SqlColumn("email", "VARCHAR(100)"),
            SqlColumn("name", "VARCHAR(50)"),
        ]
        statements = generator.generate_alter_table_statements(table, add_columns=columns)
        assert len(statements) == 2

    def test_generate_alter_table_add_column_with_schema(self):
        """Test generating ALTER TABLE ADD COLUMN with schema."""
        generator = PostgreSQLAlterGenerator()
        table = Table(
            name="users",
            schema="public",
            columns=[SqlColumn("id", "INTEGER")],
            dialect="postgresql",
        )
        new_column = SqlColumn("email", "VARCHAR(100)")
        statements = generator.generate_alter_table_statements(table, add_columns=[new_column])
        assert '"public"' in statements[0] or "public" in statements[0].lower()

    def test_generate_alter_table_drop_column(self):
        """Test generating ALTER TABLE DROP COLUMN."""
        generator = PostgreSQLAlterGenerator()
        table = Table(name="users", columns=[SqlColumn("id", "INTEGER")], dialect="postgresql")
        statements = generator.generate_alter_table_statements(table, drop_columns=["email"])
        assert len(statements) == 1
        assert "ALTER TABLE" in statements[0].upper()
        assert "DROP COLUMN" in statements[0].upper()
        assert "email" in statements[0].lower() or '"email"' in statements[0]

    def test_generate_alter_table_drop_multiple_columns(self):
        """Test generating ALTER TABLE DROP COLUMN for multiple columns."""
        generator = PostgreSQLAlterGenerator()
        table = Table(name="users", columns=[SqlColumn("id", "INTEGER")], dialect="postgresql")
        statements = generator.generate_alter_table_statements(
            table, drop_columns=["email", "name"]
        )
        assert len(statements) == 2

    def test_generate_alter_table_modify_column(self):
        """Test generating ALTER TABLE ALTER COLUMN TYPE."""
        generator = PostgreSQLAlterGenerator()
        table = Table(name="users", columns=[SqlColumn("id", "INTEGER")], dialect="postgresql")
        modified_column = SqlColumn("id", "BIGINT")
        statements = generator.generate_alter_table_statements(
            table, modify_columns=[modified_column]
        )
        assert len(statements) == 1
        assert "ALTER TABLE" in statements[0].upper()
        assert "ALTER COLUMN" in statements[0].upper()
        assert "TYPE" in statements[0].upper()
        assert "BIGINT" in statements[0].upper()

    def test_generate_alter_table_add_constraint(self):
        """Test generating ALTER TABLE ADD CONSTRAINT."""
        generator = PostgreSQLAlterGenerator()
        table = Table(name="users", columns=[SqlColumn("id", "INTEGER")], dialect="postgresql")
        constraint = SqlConstraint(
            name="pk_users",
            constraint_type=ConstraintType.PRIMARY_KEY,
            column_names=["id"],
        )
        statements = generator.generate_alter_table_statements(table, add_constraints=[constraint])
        assert len(statements) == 1
        assert "ALTER TABLE" in statements[0].upper()
        assert "ADD" in statements[0].upper()
        assert "PRIMARY KEY" in statements[0].upper()

    def test_generate_alter_table_add_foreign_key_constraint(self):
        """Test generating ALTER TABLE ADD FOREIGN KEY constraint."""
        generator = PostgreSQLAlterGenerator()
        table = Table(
            name="orders", columns=[SqlColumn("user_id", "INTEGER")], dialect="postgresql"
        )
        constraint = SqlConstraint(
            name="fk_orders_user",
            constraint_type=ConstraintType.FOREIGN_KEY,
            column_names=["user_id"],
            reference_table="users",
            reference_columns=["id"],
        )
        statements = generator.generate_alter_table_statements(table, add_constraints=[constraint])
        assert len(statements) == 1
        assert "FOREIGN KEY" in statements[0].upper()
        assert "REFERENCES" in statements[0].upper()

    def test_generate_alter_table_drop_constraint(self):
        """Test generating ALTER TABLE DROP CONSTRAINT."""
        generator = PostgreSQLAlterGenerator()
        table = Table(name="users", columns=[SqlColumn("id", "INTEGER")], dialect="postgresql")
        statements = generator.generate_alter_table_statements(table, drop_constraints=["pk_users"])
        assert len(statements) == 1
        assert "ALTER TABLE" in statements[0].upper()
        assert "DROP CONSTRAINT" in statements[0].upper()
        assert "pk_users" in statements[0].lower() or '"pk_users"' in statements[0]

    def test_generate_alter_table_multiple_operations(self):
        """Test generating multiple ALTER TABLE operations."""
        generator = PostgreSQLAlterGenerator()
        table = Table(name="users", columns=[SqlColumn("id", "INTEGER")], dialect="postgresql")
        new_column = SqlColumn("email", "VARCHAR(100)")
        constraint = SqlConstraint(
            name="pk_users",
            constraint_type=ConstraintType.PRIMARY_KEY,
            column_names=["id"],
        )
        statements = generator.generate_alter_table_statements(
            table,
            add_columns=[new_column],
            add_constraints=[constraint],
            drop_columns=["old_col"],
        )
        assert len(statements) == 3

    def test_generate_alter_table_empty(self):
        """Test generating ALTER TABLE with no operations."""
        generator = PostgreSQLAlterGenerator()
        table = Table(name="users", columns=[SqlColumn("id", "INTEGER")], dialect="postgresql")
        statements = generator.generate_alter_table_statements(table)
        assert len(statements) == 0


@pytest.mark.unit
class TestPostgreSQLAlterGeneratorAlterView:
    """Tests for generate_alter_view_statement method."""

    def test_generate_alter_view_statement_regular_view(self):
        """Test generating CREATE OR REPLACE VIEW for regular view."""
        generator = PostgreSQLAlterGenerator()
        view = View(name="active_users", query="SELECT 1", dialect="postgresql")
        result = generator.generate_alter_view_statement(view, "SELECT id FROM users")
        assert result is not None
        assert "CREATE OR REPLACE VIEW" in result.upper()
        assert "active_users" in result.lower() or '"active_users"' in result
        assert "SELECT id FROM users" in result

    def test_generate_alter_view_statement_materialized_view(self):
        """Test generating ALTER MATERIALIZED VIEW."""
        generator = PostgreSQLAlterGenerator()
        view = View(name="mv_users", query="SELECT 1", materialized=True, dialect="postgresql")
        result = generator.generate_alter_view_statement(view, "SELECT id FROM users")
        assert result is not None
        assert "ALTER MATERIALIZED VIEW" in result.upper()
        assert "mv_users" in result.lower() or '"mv_users"' in result

    def test_generate_alter_view_statement_with_schema(self):
        """Test generating ALTER VIEW with schema."""
        generator = PostgreSQLAlterGenerator()
        view = View(name="active_users", schema="public", query="SELECT 1", dialect="postgresql")
        result = generator.generate_alter_view_statement(view, "SELECT id FROM users")
        assert '"public"' in result or "public" in result.lower()

    def test_generate_alter_view_statement_no_new_query(self):
        """Test generating ALTER VIEW without new query."""
        generator = PostgreSQLAlterGenerator()
        view = View(name="active_users", query="SELECT 1", dialect="postgresql")
        result = generator.generate_alter_view_statement(view, None)
        assert result is None

    def test_generate_alter_view_statement_empty_query(self):
        """Test generating ALTER VIEW with empty query."""
        generator = PostgreSQLAlterGenerator()
        view = View(name="active_users", query="SELECT 1", dialect="postgresql")
        result = generator.generate_alter_view_statement(view, "")
        assert result is None
