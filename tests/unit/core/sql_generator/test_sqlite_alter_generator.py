"""Tests for SQLiteAlterGenerator class."""

import pytest

from core.sql_generator.alter.alter_generator_factory import AlterGeneratorFactory
from core.sql_model.base import ConstraintType, SqlColumn, SqlConstraint
from core.sql_model.table import Table
from core.sql_model.view import View
from db.plugins.sqlite.generator.alter_generator import SQLiteAlterGenerator


@pytest.mark.unit
class TestSQLiteAlterGenerator:
    """Tests for SQLite-specific ALTER generation."""

    def test_factory_supports_sqlite(self):
        """Test factory creates SQLite ALTER generators."""
        assert isinstance(AlterGeneratorFactory.create_generator("sqlite"), SQLiteAlterGenerator)
        assert isinstance(AlterGeneratorFactory.create_generator("sqlite3"), SQLiteAlterGenerator)

    def test_generate_add_column(self):
        """Test SQLite-supported ADD COLUMN generation."""
        generator = SQLiteAlterGenerator()
        table = Table(name="users", columns=[SqlColumn("id", "INTEGER")], dialect="sqlite")
        new_column = SqlColumn("email", "TEXT")

        statements = generator.generate_alter_table_statements(table, add_columns=[new_column])

        assert statements == ['ALTER TABLE "users" ADD COLUMN "email" TEXT']

    def test_generate_comments_for_unsupported_table_alterations(self):
        """Test unsupported SQLite ALTER operations become explanatory comments."""
        generator = SQLiteAlterGenerator()
        table = Table(name="users", columns=[SqlColumn("id", "INTEGER")], dialect="sqlite")
        constraint = SqlConstraint(
            name="pk_users",
            constraint_type=ConstraintType.PRIMARY_KEY,
            column_names=["id"],
        )

        statements = generator.generate_alter_table_statements(
            table,
            add_constraints=[constraint],
            drop_constraints=["pk_users"],
            drop_columns=["email"],
            modify_columns=[SqlColumn("name", "TEXT")],
        )

        assert len(statements) == 4
        assert all(statement.startswith("-- SQLite") for statement in statements)
        assert any("rebuilding the table" in statement for statement in statements)

    def test_generate_view_replacement(self):
        """Test SQLite view changes use drop/create replacement."""
        generator = SQLiteAlterGenerator()
        view = View(name="active_users", query="SELECT 1", dialect="sqlite")

        statement = generator.generate_alter_view_statement(view, "SELECT id FROM users")

        assert statement == (
            'DROP VIEW IF EXISTS "active_users";\n'
            'CREATE VIEW "active_users" AS SELECT id FROM users'
        )
