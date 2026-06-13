"""Tests for CosmosDbAlterGenerator class."""

import pytest

from core.sql_model.base import ConstraintType, SqlColumn, SqlConstraint
from core.sql_model.table import Table
from core.sql_model.view import View
from db.plugins.cosmosdb.generator.alter_generator import CosmosDbAlterGenerator


@pytest.mark.unit
class TestCosmosDbAlterGeneratorInit:
    """Tests for CosmosDbAlterGenerator initialization."""

    def test_init(self):
        """Test initialization."""
        generator = CosmosDbAlterGenerator("cosmosdb")
        assert generator.dialect == "cosmosdb"


@pytest.mark.unit
class TestCosmosDbAlterGeneratorFormatIdentifier:
    """Tests for _format_identifier method."""

    def test_format_identifier_simple(self):
        """Test formatting simple identifier."""
        generator = CosmosDbAlterGenerator("cosmosdb")
        result = generator._format_identifier("users")
        assert result == '"users"'


@pytest.mark.unit
class TestCosmosDbAlterGeneratorAlterTable:
    """Tests for generate_alter_table_statements method."""

    def test_generate_alter_table_add_column(self):
        """Test generating comment for ADD COLUMN."""
        generator = CosmosDbAlterGenerator("cosmosdb")
        table = Table(name="users", columns=[SqlColumn("id", "INTEGER")], dialect="cosmosdb")
        new_column = SqlColumn("email", "VARCHAR(100)")
        statements = generator.generate_alter_table_statements(table, add_columns=[new_column])
        assert len(statements) == 1
        assert "--" in statements[0]
        assert "CosmosDB is schema-less" in statements[0]

    def test_generate_alter_table_drop_column(self):
        """Test generating comment for DROP COLUMN."""
        generator = CosmosDbAlterGenerator("cosmosdb")
        table = Table(name="users", columns=[SqlColumn("id", "INTEGER")], dialect="cosmosdb")
        statements = generator.generate_alter_table_statements(table, drop_columns=["email"])
        assert len(statements) == 1
        assert "--" in statements[0]
        assert "drop column" in statements[0].lower()

    def test_generate_alter_table_modify_column(self):
        """Test generating comment for MODIFY COLUMN."""
        generator = CosmosDbAlterGenerator("cosmosdb")
        table = Table(name="users", columns=[SqlColumn("id", "INTEGER")], dialect="cosmosdb")
        modified_column = SqlColumn("id", "BIGINT")
        statements = generator.generate_alter_table_statements(
            table, modify_columns=[modified_column]
        )
        assert len(statements) == 1
        assert "--" in statements[0]
        assert "modify column" in statements[0].lower()

    def test_generate_alter_table_add_constraint(self):
        """Test generating comment for ADD CONSTRAINT."""
        generator = CosmosDbAlterGenerator("cosmosdb")
        table = Table(name="users", columns=[SqlColumn("id", "INTEGER")], dialect="cosmosdb")
        constraint = SqlConstraint(
            name="pk_users",
            constraint_type=ConstraintType.PRIMARY_KEY,
            column_names=["id"],
        )
        statements = generator.generate_alter_table_statements(table, add_constraints=[constraint])
        assert len(statements) == 1
        assert "--" in statements[0]
        assert "add constraint" in statements[0].lower()

    def test_generate_alter_table_add_constraint_no_name(self):
        """Test generating comment for ADD CONSTRAINT without name."""
        generator = CosmosDbAlterGenerator("cosmosdb")
        table = Table(name="users", columns=[SqlColumn("id", "INTEGER")], dialect="cosmosdb")
        constraint = SqlConstraint(
            name=None,
            constraint_type=ConstraintType.PRIMARY_KEY,
            column_names=["id"],
        )
        statements = generator.generate_alter_table_statements(table, add_constraints=[constraint])
        assert len(statements) == 1
        assert "constraint" in statements[0].lower()

    def test_generate_alter_table_drop_constraint(self):
        """Test generating comment for DROP CONSTRAINT."""
        generator = CosmosDbAlterGenerator("cosmosdb")
        table = Table(name="users", columns=[SqlColumn("id", "INTEGER")], dialect="cosmosdb")
        statements = generator.generate_alter_table_statements(table, drop_constraints=["pk_users"])
        assert len(statements) == 1
        assert "--" in statements[0]
        assert "drop constraint" in statements[0].lower()


@pytest.mark.unit
class TestCosmosDbAlterGeneratorAlterView:
    """Tests for generate_alter_view_statement method."""

    def test_generate_alter_view_statement(self):
        """Test generating comment for ALTER VIEW."""
        generator = CosmosDbAlterGenerator("cosmosdb")
        view = View(name="active_users", query="SELECT 1", dialect="cosmosdb")
        result = generator.generate_alter_view_statement(view, "SELECT id FROM users")
        assert result is not None
        assert "--" in result
        assert "CosmosDB does not support views" in result

    def test_generate_alter_view_statement_no_new_query(self):
        """Test generating ALTER VIEW without new query."""
        generator = CosmosDbAlterGenerator("cosmosdb")
        view = View(name="active_users", query="SELECT 1", dialect="cosmosdb")
        result = generator.generate_alter_view_statement(view, None)
        assert result is not None
        assert "--" in result
