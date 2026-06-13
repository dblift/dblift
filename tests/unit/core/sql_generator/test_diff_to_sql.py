"""Unit tests for diff-to-SQL generation."""

import pytest

from core.comparison.diff_models import (
    ColumnDiff,
    DiffSeverity,
    IndexDiff,
    ProcedureDiff,
    SchemaDiff,
    SequenceDiff,
    TableDiff,
    TriggerDiff,
    ViewDiff,
)
from core.sql_generator.diff_to_sql import generate_sql_script, generate_sql_statements
from core.sql_model.base import ConstraintType, SqlColumn, SqlConstraint
from core.sql_model.index import Index
from core.sql_model.procedure import Procedure
from core.sql_model.sequence import Sequence
from core.sql_model.table import Table
from core.sql_model.trigger import Trigger
from core.sql_model.view import View

pytestmark = [pytest.mark.unit]


class TestDiffToSql:
    """Test cases for diff-to-SQL generation."""

    def test_generate_sql_statements_from_column_diff(self):
        """Test generating SQL statements from column diff."""
        # Create a table diff with column changes
        column_diff = ColumnDiff(
            object_name="email",
            column_name="email",
            nullable_diff=(False, True),  # Setting NOT NULL
        )

        table_diff = TableDiff(
            object_name="users",
            table_name="users",
            modified_columns=[column_diff],
        )

        schema_diff = SchemaDiff(
            object_name="public",
            schema_name="public",
            modified_tables=[table_diff],
        )

        statements = generate_sql_statements(schema_diff, dialect="postgresql")

        assert len(statements) == 1
        assert statements[0].statement_type == "ALTER"
        assert "SET NOT NULL" in statements[0].sql

    def test_generate_sql_script_with_comments(self):
        """Test generating formatted SQL script with comments."""
        column_diff = ColumnDiff(
            object_name="email",
            column_name="email",
            nullable_diff=(False, True),
        )

        table_diff = TableDiff(
            object_name="users",
            table_name="users",
            modified_columns=[column_diff],
        )

        schema_diff = SchemaDiff(
            object_name="public",
            schema_name="public",
            modified_tables=[table_diff],
        )

        script = generate_sql_script(
            schema_diff,
            dialect="postgresql",
            title="Test Script",
            include_comments=True,
        )

        assert "Test Script" in script
        assert "ALTER" in script
        assert "SET NOT NULL" in script
        assert "--" in script  # Comments present

    def test_generate_add_column_with_expected_table(self):
        """Test generating ADD COLUMN statement with expected table."""
        # Create expected table with a column
        expected_column = SqlColumn(
            name="email",
            data_type="VARCHAR(255)",
            is_nullable=False,
            default_value="''",
        )
        expected_table = Table(
            name="users",
            schema="public",
            columns=[expected_column],
        )

        # Create diff with missing column
        table_diff = TableDiff(
            object_name="users",
            table_name="users",
            missing_columns=["email"],
        )

        schema_diff = SchemaDiff(
            object_name="public",
            schema_name="public",
            modified_tables=[table_diff],
        )

        expected_tables = {"users": expected_table}

        statements = generate_sql_statements(
            schema_diff, expected_tables=expected_tables, dialect="postgresql"
        )

        assert len(statements) == 1
        assert statements[0].statement_type == "ALTER"
        assert "ADD COLUMN" in statements[0].sql
        assert "email" in statements[0].sql

    def test_generate_create_table_with_expected_table(self):
        """Test generating CREATE TABLE statement."""
        # Create expected table
        expected_table = Table(
            name="users",
            schema="public",
            columns=[
                SqlColumn(name="id", data_type="SERIAL", is_nullable=False),
                SqlColumn(name="name", data_type="VARCHAR(100)", is_nullable=False),
            ],
        )

        schema_diff = SchemaDiff(
            object_name="public",
            schema_name="public",
            missing_tables=["users"],
        )

        expected_tables = {"users": expected_table}

        statements = generate_sql_statements(
            schema_diff, expected_tables=expected_tables, dialect="postgresql"
        )

        assert len(statements) == 1
        assert statements[0].statement_type == "CREATE"
        assert statements[0].object_type == "TABLE"
        assert "CREATE TABLE" in statements[0].sql

    def test_generate_drop_table(self):
        """Test generating DROP TABLE statement."""
        schema_diff = SchemaDiff(
            object_name="public",
            schema_name="public",
            extra_tables=["old_table"],
        )

        statements = generate_sql_statements(schema_diff, dialect="postgresql")

        assert len(statements) == 1
        assert statements[0].statement_type == "DROP"
        assert "DROP TABLE" in statements[0].sql
        assert "old_table" in statements[0].sql

    def test_generate_drop_column(self):
        """Test generating DROP COLUMN statement."""
        # Create expected table (required for ALTER generator)
        expected_table = Table(
            name="users",
            schema="public",
            columns=[SqlColumn(name="id", data_type="INTEGER", is_nullable=False)],
        )

        table_diff = TableDiff(
            object_name="users",
            table_name="users",
            extra_columns=["old_column"],
        )

        schema_diff = SchemaDiff(
            object_name="public",
            schema_name="public",
            modified_tables=[table_diff],
        )

        expected_tables = {"users": expected_table}

        statements = generate_sql_statements(
            schema_diff, expected_tables=expected_tables, dialect="postgresql"
        )

        assert len(statements) == 1
        assert statements[0].statement_type == "ALTER"
        assert "DROP COLUMN" in statements[0].sql
        assert "old_column" in statements[0].sql

    def test_generate_create_view(self):
        """Test generating CREATE VIEW statement."""
        expected_view = View(
            name="user_summary",
            schema="public",
            query="SELECT id, name FROM users",
        )

        schema_diff = SchemaDiff(
            object_name="public",
            schema_name="public",
            missing_views=["user_summary"],
        )

        expected_views = {"user_summary": expected_view}

        statements = generate_sql_statements(
            schema_diff, expected_views=expected_views, dialect="postgresql"
        )

        assert len(statements) == 1
        assert statements[0].statement_type == "CREATE"
        assert statements[0].object_type == "VIEW"
        assert "CREATE VIEW" in statements[0].sql

    def test_generate_drop_view(self):
        """Test generating DROP VIEW statement."""
        schema_diff = SchemaDiff(
            object_name="public",
            schema_name="public",
            extra_views=["old_view"],
        )

        statements = generate_sql_statements(schema_diff, dialect="postgresql")

        assert len(statements) == 1
        assert statements[0].statement_type == "DROP"
        assert "DROP VIEW" in statements[0].sql
        assert "old_view" in statements[0].sql

    def test_generate_create_index(self):
        """Test generating CREATE INDEX statement."""
        expected_index = Index(
            name="idx_users_email",
            table_name="users",
            columns=["email"],
            unique=False,
        )

        schema_diff = SchemaDiff(
            object_name="public",
            schema_name="public",
            missing_indexes=["idx_users_email"],
        )

        expected_indexes = {"idx_users_email": expected_index}

        statements = generate_sql_statements(
            schema_diff, expected_indexes=expected_indexes, dialect="postgresql"
        )

        assert len(statements) == 1
        assert statements[0].statement_type == "CREATE"
        assert statements[0].object_type == "INDEX"
        assert "CREATE INDEX" in statements[0].sql

    def test_generate_create_sequence(self):
        """Test generating CREATE SEQUENCE statement."""
        expected_sequence = Sequence(
            name="user_id_seq",
            schema="public",
            start_with=1,
            increment_by=1,
        )

        schema_diff = SchemaDiff(
            object_name="public",
            schema_name="public",
            missing_sequences=["user_id_seq"],
        )

        expected_sequences = {"user_id_seq": expected_sequence}

        statements = generate_sql_statements(
            schema_diff, expected_sequences=expected_sequences, dialect="postgresql"
        )

        assert len(statements) == 1
        assert statements[0].statement_type == "CREATE"
        assert statements[0].object_type == "SEQUENCE"
        assert "CREATE SEQUENCE" in statements[0].sql

    def test_generate_add_constraint(self):
        """Test generating ADD CONSTRAINT statement."""
        expected_constraint = SqlConstraint(
            constraint_type=ConstraintType.PRIMARY_KEY,
            name="pk_users",
            column_names=["id"],
        )
        expected_table = Table(
            name="users",
            schema="public",
            columns=[SqlColumn(name="id", data_type="INTEGER", is_nullable=False)],
            constraints=[expected_constraint],
        )

        table_diff = TableDiff(
            object_name="users",
            table_name="users",
            missing_constraints=["pk_users"],
        )

        schema_diff = SchemaDiff(
            object_name="public",
            schema_name="public",
            modified_tables=[table_diff],
        )

        expected_tables = {"users": expected_table}

        statements = generate_sql_statements(
            schema_diff, expected_tables=expected_tables, dialect="postgresql"
        )

        assert len(statements) == 1
        assert statements[0].statement_type == "ALTER"
        # ALTER generator produces "ADD PRIMARY KEY" directly, not "ADD CONSTRAINT"
        assert "ADD" in statements[0].sql
        assert "PRIMARY KEY" in statements[0].sql

    def test_generate_drop_constraint(self):
        """Test generating DROP CONSTRAINT statement."""
        # Create expected table (required for ALTER generator)
        expected_table = Table(
            name="users",
            schema="public",
            columns=[SqlColumn(name="id", data_type="INTEGER", is_nullable=False)],
        )

        table_diff = TableDiff(
            object_name="users",
            table_name="users",
            extra_constraints=["old_constraint"],
        )

        schema_diff = SchemaDiff(
            object_name="public",
            schema_name="public",
            modified_tables=[table_diff],
        )

        expected_tables = {"users": expected_table}

        statements = generate_sql_statements(
            schema_diff, expected_tables=expected_tables, dialect="postgresql"
        )

        assert len(statements) == 1
        assert statements[0].statement_type == "ALTER"
        assert "DROP CONSTRAINT" in statements[0].sql
        assert "old_constraint" in statements[0].sql

    def test_generate_sql_script_without_title(self):
        """Test generating SQL script without title (uses default)."""
        schema_diff = SchemaDiff(
            object_name="public",
            schema_name="public",
            missing_tables=["users"],
        )
        script = generate_sql_script(schema_diff, dialect="postgresql")
        assert "Schema Update Script" in script
        assert "postgresql" in script

    def test_generate_sql_script_without_description(self):
        """Test generating SQL script without description (uses default)."""
        schema_diff = SchemaDiff(
            object_name="public",
            schema_name="public",
            missing_tables=["users"],
        )
        script = generate_sql_script(schema_diff, dialect="postgresql", title="Custom Title")
        assert "Custom Title" in script
        assert "Generated SQL script to synchronize database schema" in script

    def test_generate_sql_script_without_comments(self):
        """Test generating SQL script without comments."""
        schema_diff = SchemaDiff(
            object_name="public",
            schema_name="public",
            missing_tables=["users"],
        )
        script = generate_sql_script(schema_diff, dialect="postgresql", include_comments=False)
        # Should still generate SQL but with fewer comments
        assert isinstance(script, str)
        assert len(script) > 0

    def test_generate_sql_script_without_checks(self):
        """Test generating SQL script without checks."""
        schema_diff = SchemaDiff(
            object_name="public",
            schema_name="public",
            missing_tables=["users"],
        )
        script = generate_sql_script(schema_diff, dialect="postgresql", include_checks=False)
        assert isinstance(script, str)
        assert len(script) > 0

    def test_generate_sql_script_cosmosdb_drop_container(self):
        """Test generating SQL script for CosmosDB DROP CONTAINER."""
        schema_diff = SchemaDiff(
            object_name="public",
            schema_name="public",
            extra_tables=["test_container"],
        )
        script = generate_sql_script(schema_diff, dialect="cosmosdb")
        # Should include CosmosDB SDK operations section
        assert "COSMOSDB SDK OPERATIONS" in script or "DROP CONTAINER" in script

    def test_generate_sql_statements_cosmosdb(self):
        """Test generating SQL statements for CosmosDB."""
        schema_diff = SchemaDiff(
            object_name="public",
            schema_name="public",
            extra_tables=["test_container"],
        )
        statements = generate_sql_statements(schema_diff, dialect="cosmosdb")
        assert len(statements) > 0
        # CosmosDB DROP statements should be marked as requiring SDK
        drop_statements = [s for s in statements if s.statement_type == "DROP"]
        if drop_statements:
            assert any(s.requires_sdk for s in drop_statements)

    def test_generate_sql_statements_with_all_expected_objects(self):
        """Test generating SQL statements with all expected object types."""
        schema_diff = SchemaDiff(
            object_name="public",
            schema_name="public",
            missing_tables=["users"],
            missing_views=["user_view"],
            missing_indexes=["idx_users"],
            missing_sequences=["user_seq"],
            missing_triggers=["user_trigger"],
            missing_procedures=["user_proc"],
            missing_functions=["user_func"],
        )
        expected_tables = {
            "users": Table(name="users", columns=[SqlColumn("id", "INTEGER")], dialect="postgresql")
        }
        expected_views = {
            "user_view": View(name="user_view", query="SELECT 1", dialect="postgresql")
        }
        expected_indexes = {
            "idx_users": Index(
                name="idx_users", table_name="users", columns=["id"], dialect="postgresql"
            )
        }
        expected_sequences = {"user_seq": Sequence(name="user_seq", dialect="postgresql")}
        expected_triggers = {
            "user_trigger": Trigger(
                name="user_trigger",
                table_name="users",
                timing="BEFORE",
                events=["INSERT"],
                dialect="postgresql",
            )
        }
        expected_procedures = {
            "user_proc": Procedure(name="user_proc", definition="BEGIN END", dialect="postgresql")
        }
        expected_functions = {
            "user_func": Procedure(
                name="user_func", definition="RETURN 1", is_function=True, dialect="postgresql"
            )
        }

        statements = generate_sql_statements(
            schema_diff,
            expected_tables=expected_tables,
            expected_views=expected_views,
            expected_indexes=expected_indexes,
            expected_sequences=expected_sequences,
            expected_triggers=expected_triggers,
            expected_procedures=expected_procedures,
            expected_functions=expected_functions,
            dialect="postgresql",
        )
        assert len(statements) > 0

    def test_generate_sql_script_cosmosdb_with_sdk_operation(self):
        """Test generating SQL script for CosmosDB with SDK operation extraction."""
        schema_diff = SchemaDiff(
            object_name="public",
            schema_name="public",
            extra_tables=["test_container"],
        )
        script = generate_sql_script(schema_diff, dialect="cosmosdb")
        # Should extract container name and create SDK operation
        assert "test_container" in script or "COSMOSDB SDK OPERATIONS" in script

    def test_generate_sql_script_cosmosdb_drop_container_extraction(self):
        """Test that CosmosDB DROP CONTAINER statements get SDK operation extracted."""
        from unittest.mock import MagicMock, patch

        from core.sql_generator.sql_statement import SqlStatement

        schema_diff = SchemaDiff(
            object_name="public",
            schema_name="public",
            extra_tables=["test_container"],
        )

        # Mock DiffSqlGenerator to return a statement with DROP CONTAINER SQL
        with patch("core.sql_generator.diff_to_sql.DiffSqlGenerator") as mock_generator_class:
            mock_generator = MagicMock()
            mock_generator_class.return_value = mock_generator

            # Create a statement that will trigger the SDK operation extraction
            drop_stmt = SqlStatement(
                sql="DROP CONTAINER test_container",
                statement_type="DROP",
                object_type="CONTAINER",
                object_name="test_container",
                dialect="cosmosdb",
                requires_sdk=False,  # Not yet set
                sdk_operation=None,  # Not yet set
            )
            mock_generator.generate_from_diff.return_value = [drop_stmt]

            script = generate_sql_script(schema_diff, dialect="cosmosdb")
            # Should have extracted SDK operation
            assert "test_container" in script
