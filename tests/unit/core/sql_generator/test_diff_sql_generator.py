"""Tests for DiffSqlGenerator class."""

from dataclasses import fields, is_dataclass
from unittest.mock import MagicMock, patch

import pytest

from core.comparison.diff_models import (
    ColumnDiff,
    SchemaDiff,
    SequenceDiff,
    TableDiff,
    ViewDiff,
)
from core.sql_generator.diff_sql_generator import DiffGenerationContext, DiffSqlGenerator
from core.sql_generator.sql_statement import GenerationOptions, SqlStatement
from core.sql_model.base import SqlColumn, SqlConstraint
from core.sql_model.index import Index
from core.sql_model.procedure import Procedure
from core.sql_model.sequence import Sequence
from core.sql_model.table import Table
from core.sql_model.table_options import SqlServerTableOptions, TableOptions
from core.sql_model.trigger import Trigger
from core.sql_model.view import View


@pytest.mark.unit
class TestDiffSqlGeneratorInit:
    """Tests for DiffSqlGenerator initialization."""

    def test_init_default(self):
        """Test initialization with explicit postgresql dialect.

        The default value (``""``) is no longer accepted by the
        downstream :class:`AlterGeneratorFactory`, so callers must
        supply a real dialect identifier.
        """
        generator = DiffSqlGenerator(dialect="postgresql")
        assert generator.dialect == "postgresql"
        assert generator.column_converter is not None
        assert generator.sql_generator is not None
        assert generator.alter_generator is not None
        assert not hasattr(generator, "table_converter")  # D2: dead code removed

    def test_init_postgresql(self):
        """Test initialization with PostgreSQL dialect."""
        generator = DiffSqlGenerator(dialect="postgresql")
        assert generator.dialect == "postgresql"

    def test_init_sqlserver(self):
        """Test initialization with SQL Server dialect."""
        generator = DiffSqlGenerator(dialect="sqlserver")
        assert generator.dialect == "sqlserver"

    def test_init_mysql(self):
        """Test initialization with MySQL dialect."""
        generator = DiffSqlGenerator(dialect="mysql")
        assert generator.dialect == "mysql"


@pytest.mark.unit
class TestDiffSqlGeneratorGenerateFromDiff:
    """Tests for generate_from_diff method."""

    def test_generate_from_diff_empty_diff(self):
        """Test generating SQL from empty diff."""
        generator = DiffSqlGenerator(dialect="postgresql")
        diff = SchemaDiff(object_name="public", schema_name="public")
        statements = generator.generate_from_diff(diff)
        assert statements == []

    def test_generate_from_diff_missing_table(self):
        """Test generating CREATE TABLE for missing table."""
        generator = DiffSqlGenerator(dialect="postgresql")
        diff = SchemaDiff(object_name="public", schema_name="public", missing_tables=["users"])
        expected_table = Table(
            name="users", columns=[SqlColumn("id", "INTEGER")], dialect="postgresql"
        )
        ctx = DiffGenerationContext(expected_tables={"users": expected_table})
        statements = generator.generate_from_diff(diff, context=ctx)
        assert len(statements) > 0
        assert any(s.statement_type == "CREATE" and s.object_type == "TABLE" for s in statements)

    def test_generate_from_diff_missing_table_no_expected(self):
        """Test generating SQL when missing table has no expected definition."""
        generator = DiffSqlGenerator(dialect="postgresql")
        diff = SchemaDiff(object_name="public", schema_name="public", missing_tables=["users"])
        statements = generator.generate_from_diff(diff)
        assert len(statements) == 0  # Should skip with warning

    def test_generate_from_diff_extra_table(self):
        """Test generating DROP TABLE for extra table."""
        generator = DiffSqlGenerator(dialect="postgresql")
        diff = SchemaDiff(object_name="public", schema_name="public", extra_tables=["old_table"])
        statements = generator.generate_from_diff(diff)
        assert len(statements) > 0
        assert any(s.statement_type == "DROP" and s.object_type == "TABLE" for s in statements)

    def test_generate_from_diff_modified_table(self):
        """Test generating SQL for modified table."""
        generator = DiffSqlGenerator(dialect="postgresql")
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
        diff = SchemaDiff(
            object_name="public",
            schema_name="public",
            modified_tables=[table_diff],
        )
        expected_table = Table(
            name="users",
            columns=[
                SqlColumn("id", "INTEGER"),
                SqlColumn("email", "VARCHAR(100)", is_nullable=False),
            ],
            dialect="postgresql",
        )
        ctx = DiffGenerationContext(expected_tables={"users": expected_table})
        statements = generator.generate_from_diff(diff, context=ctx)
        assert len(statements) > 0

    def test_generate_from_diff_with_options(self):
        """Test generating SQL with custom options."""
        generator = DiffSqlGenerator(dialect="postgresql")
        diff = SchemaDiff(object_name="public", schema_name="public")
        options = GenerationOptions(dialect="mysql")
        statements = generator.generate_from_diff(diff, options=options)
        assert isinstance(statements, list)


@pytest.mark.unit
class TestDiffSqlGeneratorTableChanges:
    """Tests for _generate_table_changes method."""

    def test_generate_table_changes_add_column(self):
        """Test generating ALTER TABLE ADD COLUMN."""
        generator = DiffSqlGenerator(dialect="postgresql")
        table_diff = TableDiff(
            object_name="users",
            table_name="users",
            missing_columns=["email"],
        )
        expected_table = Table(
            name="users",
            columns=[
                SqlColumn("id", "INTEGER"),
                SqlColumn("email", "VARCHAR(100)"),
            ],
            dialect="postgresql",
        )
        options = GenerationOptions(dialect="postgresql")
        statements = generator._generate_table_changes(
            table_diff, {"users": expected_table}, options
        )
        assert len(statements) > 0

    def test_generate_table_changes_drop_column(self):
        """Test generating ALTER TABLE DROP COLUMN."""
        generator = DiffSqlGenerator(dialect="postgresql")
        table_diff = TableDiff(
            object_name="users",
            table_name="users",
            extra_columns=["old_column"],
        )
        expected_table = Table(
            name="users", columns=[SqlColumn("id", "INTEGER")], dialect="postgresql"
        )
        options = GenerationOptions(dialect="postgresql")
        statements = generator._generate_table_changes(
            table_diff, {"users": expected_table}, options
        )
        assert len(statements) > 0

    def test_generate_table_changes_add_constraint(self):
        """Test generating ALTER TABLE ADD CONSTRAINT."""
        generator = DiffSqlGenerator(dialect="postgresql")
        constraint = SqlConstraint(
            name="pk_users",
            constraint_type="PRIMARY_KEY",
            column_names=["id"],
        )
        table_diff = TableDiff(
            object_name="users",
            table_name="users",
            missing_constraints=["pk_users"],
        )
        expected_table = Table(
            name="users",
            columns=[SqlColumn("id", "INTEGER")],
            constraints=[constraint],
            dialect="postgresql",
        )
        options = GenerationOptions(dialect="postgresql")
        statements = generator._generate_table_changes(
            table_diff, {"users": expected_table}, options
        )
        assert len(statements) > 0

    def test_generate_table_changes_no_expected_table(self):
        """Test generating table changes without expected table."""
        generator = DiffSqlGenerator(dialect="postgresql")
        table_diff = TableDiff(
            object_name="users",
            table_name="users",
            missing_columns=["email"],
        )
        options = GenerationOptions(dialect="postgresql")
        statements = generator._generate_table_changes(table_diff, None, options)
        # Should still process column diffs
        assert isinstance(statements, list)

    def test_generate_table_changes_modified_column_no_duplicate(self):
        """AC#1 — modified_columns + expected_tables → exactly 1 ALTER per column, not 2."""
        generator = DiffSqlGenerator(dialect="postgresql")
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
        expected_table = Table(
            name="users",
            columns=[
                SqlColumn("id", "INTEGER"),
                SqlColumn("email", "VARCHAR(100)", is_nullable=False),
            ],
            dialect="postgresql",
        )
        options = GenerationOptions(dialect="postgresql")
        statements = generator._generate_table_changes(
            table_diff, {"users": expected_table}, options
        )
        alter_stmts = [s for s in statements if "email" in s.sql and "ALTER" in s.sql.upper()]
        assert (
            len(alter_stmts) == 1
        ), f"Expected 1 ALTER for email column, got {len(alter_stmts)}: {[s.sql for s in alter_stmts]}"

    def test_generate_table_changes_modified_column_no_expected_table(self):
        """AC#2 — modified_columns without expected_tables → column_converter still works."""
        generator = DiffSqlGenerator(dialect="postgresql")
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
        options = GenerationOptions(dialect="postgresql")
        statements = generator._generate_table_changes(table_diff, None, options)
        assert (
            len(statements) == 1
        ), f"Expected exactly 1 statement for single nullable change, got {len(statements)}"
        assert any("email" in s.sql for s in statements)

    def test_generate_table_changes_modified_column_table_not_in_expected(self):
        """AC#3 — modified_columns + expected_tables without the table → column_converter runs."""
        generator = DiffSqlGenerator(dialect="postgresql")
        column_diff = ColumnDiff(
            object_name="email",
            column_name="email",
            data_type_diff=("TEXT", "VARCHAR(100)"),
        )
        table_diff = TableDiff(
            object_name="users",
            table_name="users",
            modified_columns=[column_diff],
        )
        other_table = Table(
            name="orders", columns=[SqlColumn("id", "INTEGER")], dialect="postgresql"
        )
        options = GenerationOptions(dialect="postgresql")
        statements = generator._generate_table_changes(table_diff, {"orders": other_table}, options)
        assert any("email" in s.sql for s in statements)

    def test_generate_table_changes_multiple_diffs_ac4(self):
        """AC#4 — colonne avec nullable_diff + data_type_diff → exactement 2 statements, pas de doublon."""
        generator = DiffSqlGenerator(dialect="postgresql")
        column_diff = ColumnDiff(
            object_name="email",
            column_name="email",
            nullable_diff=(False, True),
            data_type_diff=("TEXT", "VARCHAR(100)"),
        )
        table_diff = TableDiff(
            object_name="users",
            table_name="users",
            modified_columns=[column_diff],
        )
        expected_table = Table(
            name="users",
            columns=[
                SqlColumn("id", "INTEGER"),
                SqlColumn("email", "VARCHAR(100)", is_nullable=True),
            ],
            dialect="postgresql",
        )
        options = GenerationOptions(dialect="postgresql")
        statements = generator._generate_table_changes(
            table_diff, {"users": expected_table}, options
        )
        email_stmts = [s for s in statements if "email" in s.sql]
        assert len(email_stmts) == 2, (
            f"Expected exactly 2 statements for email column (nullable + type), got {len(email_stmts)}: "
            f"{[s.sql for s in email_stmts]}"
        )

    def test_generate_table_changes_modified_column_mysql_dialect(self):
        """AC#4 — dialect MySQL : modified_columns + expected_tables → exactement 1 ALTER par colonne, pas de doublon."""
        generator = DiffSqlGenerator(dialect="mysql")
        column_diff = ColumnDiff(
            object_name="email",
            column_name="email",
            data_type_diff=("TEXT", "VARCHAR(100)"),
        )
        table_diff = TableDiff(
            object_name="users",
            table_name="users",
            modified_columns=[column_diff],
        )
        expected_table = Table(
            name="users",
            columns=[
                SqlColumn("id", "INTEGER"),
                SqlColumn("email", "VARCHAR(100)"),
            ],
            dialect="mysql",
        )
        options = GenerationOptions(dialect="mysql")
        statements = generator._generate_table_changes(
            table_diff, {"users": expected_table}, options
        )
        email_stmts = [s for s in statements if "email" in s.sql]
        assert len(email_stmts) == 1, (
            f"Expected 1 ALTER for email column (mysql), got {len(email_stmts)}: "
            f"{[s.sql for s in email_stmts]}"
        )


@pytest.mark.unit
class TestDiffSqlGeneratorDropTable:
    """Tests for _generate_drop_table method."""

    def test_generate_drop_table_simple(self):
        """Test generating DROP TABLE statement."""
        generator = DiffSqlGenerator(dialect="postgresql")
        options = GenerationOptions(dialect="postgresql")
        statement = generator._generate_drop_table("users", options)
        assert statement is not None
        assert statement.statement_type == "DROP"
        assert statement.object_type == "TABLE"
        assert "DROP TABLE" in statement.sql.upper()

    def test_generate_drop_table_with_schema(self):
        """Test generating DROP TABLE with schema."""
        generator = DiffSqlGenerator(dialect="postgresql")
        options = GenerationOptions(dialect="postgresql")
        statement = generator._generate_drop_table("public.users", options)
        assert statement is not None
        assert "public" in statement.sql.lower() or '"public"' in statement.sql

    def test_generate_drop_table_cosmosdb(self):
        """Test generating DROP CONTAINER for CosmosDB."""
        generator = DiffSqlGenerator(dialect="cosmosdb")
        options = GenerationOptions(dialect="cosmosdb")
        statement = generator._generate_drop_table("container1", options)
        assert statement is not None
        assert statement.requires_sdk is True
        assert statement.sdk_operation is not None

    def test_generate_drop_table_exception(self):
        """Test handling exception in DROP TABLE generation."""
        generator = DiffSqlGenerator(dialect="postgresql")
        generator.sql_generator._generate_drop_statement = MagicMock(side_effect=Exception("Error"))
        options = GenerationOptions(dialect="postgresql")
        statement = generator._generate_drop_table("users", options)
        assert statement is None


@pytest.mark.unit
class TestDiffSqlGeneratorCreateTable:
    """Tests for _generate_create_table method."""

    def test_generate_create_table_simple(self):
        """Test generating CREATE TABLE statement."""
        generator = DiffSqlGenerator(dialect="postgresql")
        table = Table(
            name="users",
            columns=[SqlColumn("id", "INTEGER"), SqlColumn("name", "VARCHAR(100)")],
            dialect="postgresql",
        )
        options = GenerationOptions(dialect="postgresql")
        statement = generator._generate_create_table(table, options)
        assert statement is not None
        assert statement.statement_type == "CREATE"
        assert statement.object_type == "TABLE"
        assert "CREATE TABLE" in statement.sql.upper()

    def test_generate_create_table_cosmosdb(self):
        """Test generating CREATE CONTAINER for CosmosDB."""
        generator = DiffSqlGenerator(dialect="cosmosdb")
        table = Table(name="container1", columns=[], dialect="cosmosdb")
        options = GenerationOptions(dialect="cosmosdb")
        statement = generator._generate_create_table(table, options)
        assert statement is not None
        assert "CREATE CONTAINER" in statement.sql.upper()


@pytest.mark.unit
class TestDiffSqlGeneratorHelperMethods:
    """Tests for helper methods."""

    def test_parse_table_name_simple(self):
        """Test parsing simple table name."""
        generator = DiffSqlGenerator(dialect="postgresql")
        schema, name = generator._parse_table_name("users")
        assert schema is None
        assert name == "users"

    def test_parse_table_name_with_schema(self):
        """Test parsing table name with schema."""
        generator = DiffSqlGenerator(dialect="postgresql")
        schema, name = generator._parse_table_name("public.users")
        assert schema == "public"
        assert name == "users"

    def test_format_identifier(self):
        """Test formatting identifier."""
        generator = DiffSqlGenerator(dialect="postgresql")
        result = generator._format_identifier("public", "users")
        assert "users" in result
        assert "public" in result or '"public"' in result

    def test_format_identifier_no_schema(self):
        """Test formatting identifier without schema."""
        generator = DiffSqlGenerator(dialect="postgresql")
        result = generator._format_identifier(None, "users")
        assert "users" in result

    def test_quote_identifier_postgresql(self):
        """Test quoting identifier for PostgreSQL."""
        generator = DiffSqlGenerator(dialect="postgresql")
        result = generator._quote_identifier("users")
        assert result == '"users"'

    def test_quote_identifier_mysql(self):
        """Test quoting identifier for MySQL."""
        generator = DiffSqlGenerator(dialect="mysql")
        result = generator._quote_identifier("users")
        assert result == "`users`"

    def test_find_constraint(self):
        """Test finding constraint in table."""
        generator = DiffSqlGenerator(dialect="postgresql")
        constraint = SqlConstraint(
            name="pk_users", constraint_type="PRIMARY_KEY", column_names=["id"]
        )
        table = Table(
            name="users",
            columns=[SqlColumn("id", "INTEGER")],
            constraints=[constraint],
            dialect="postgresql",
        )
        found = generator._find_constraint(table, "pk_users")
        assert found == constraint

    def test_find_constraint_case_insensitive(self):
        """Test finding constraint case-insensitively."""
        generator = DiffSqlGenerator(dialect="postgresql")
        constraint = SqlConstraint(
            name="PK_USERS", constraint_type="PRIMARY_KEY", column_names=["id"]
        )
        table = Table(
            name="users",
            columns=[SqlColumn("id", "INTEGER")],
            constraints=[constraint],
            dialect="postgresql",
        )
        found = generator._find_constraint(table, "pk_users")
        assert found == constraint

    def test_find_table_index(self):
        """Test finding index in table."""
        generator = DiffSqlGenerator(dialect="postgresql")
        index = Index(name="idx_email", table_name="users", columns=["email"], dialect="postgresql")
        table = Table(name="users", columns=[SqlColumn("id", "INTEGER")], dialect="postgresql")
        table.indexes = [index]
        found = generator._find_table_index(table, "idx_email")
        assert found == index

    def test_find_table_index_not_found(self):
        """Test finding index that doesn't exist."""
        generator = DiffSqlGenerator(dialect="postgresql")
        table = Table(name="users", columns=[SqlColumn("id", "INTEGER")], dialect="postgresql")
        table.indexes = []
        found = generator._find_table_index(table, "nonexistent")
        assert found is None

    def test_find_table_index_no_indexes_attr(self):
        """Test finding index when table has no indexes attribute."""
        generator = DiffSqlGenerator(dialect="postgresql")
        table = Table(name="users", columns=[SqlColumn("id", "INTEGER")], dialect="postgresql")
        found = generator._find_table_index(table, "idx_email")
        assert found is None


@pytest.mark.unit
class TestDiffSqlGeneratorTablePropertyChanges:
    """Tests for table property changes."""

    def test_generate_table_property_changes_inherits_add(self):
        """Test generating ALTER TABLE INHERIT."""
        generator = DiffSqlGenerator(dialect="postgresql")
        table_diff = TableDiff(
            object_name="users",
            table_name="users",
            inherits_changed=(["parent"], []),
        )
        expected_table = Table(
            name="users", columns=[SqlColumn("id", "INTEGER")], dialect="postgresql"
        )
        options = GenerationOptions(dialect="postgresql")
        statements = generator._generate_table_property_changes(table_diff, expected_table, options)
        assert len(statements) > 0
        assert any("INHERIT" in s.sql.upper() for s in statements)

    def test_generate_table_property_changes_inherits_remove(self):
        """Test generating ALTER TABLE NO INHERIT."""
        generator = DiffSqlGenerator(dialect="postgresql")
        table_diff = TableDiff(
            object_name="users",
            table_name="users",
            inherits_changed=([], ["parent"]),
        )
        expected_table = Table(
            name="users", columns=[SqlColumn("id", "INTEGER")], dialect="postgresql"
        )
        options = GenerationOptions(dialect="postgresql")
        statements = generator._generate_table_property_changes(table_diff, expected_table, options)
        assert len(statements) > 0
        assert any("NO INHERIT" in s.sql.upper() for s in statements)

    def test_generate_table_property_changes_system_versioning_enable(self):
        """Test generating ALTER TABLE for enabling system versioning."""
        generator = DiffSqlGenerator(dialect="sqlserver")
        expected_table = Table.from_options(
            name="users",
            columns=[SqlColumn("id", "INTEGER")],
            dialect="sqlserver",
            options=TableOptions(
                sqlserver=SqlServerTableOptions(
                    system_versioned=True,
                    history_table="users_history",
                    period_start_column="SysStartTime",
                    period_end_column="SysEndTime",
                )
            ),
        )
        table_diff = TableDiff(
            object_name="users",
            table_name="users",
            system_versioned_changed=True,
        )
        options = GenerationOptions(dialect="sqlserver")
        statements = generator._generate_table_property_changes(table_diff, expected_table, options)
        assert len(statements) > 0
        assert any("SYSTEM_VERSIONING" in s.sql.upper() for s in statements)

    def test_generate_table_property_changes_system_versioning_disable(self):
        """Test generating ALTER TABLE for disabling system versioning."""
        generator = DiffSqlGenerator(dialect="sqlserver")
        expected_table = Table.from_options(
            name="users",
            columns=[SqlColumn("id", "INTEGER")],
            dialect="sqlserver",
            options=TableOptions(sqlserver=SqlServerTableOptions(system_versioned=False)),
        )
        table_diff = TableDiff(
            object_name="users",
            table_name="users",
            system_versioned_changed=True,
        )
        options = GenerationOptions(dialect="sqlserver")
        statements = generator._generate_table_property_changes(table_diff, expected_table, options)
        assert len(statements) > 0
        assert any("SYSTEM_VERSIONING = OFF" in s.sql.upper() for s in statements)

    def test_generate_table_property_changes_recreation_warning(self):
        """Test generating warning for properties requiring recreation."""
        generator = DiffSqlGenerator(dialect="postgresql")
        table_diff = TableDiff(
            object_name="users",
            table_name="users",
            temporary_changed=True,
            filegroup_changed=True,
            partition_method_changed=True,
        )
        expected_table = Table(
            name="users", columns=[SqlColumn("id", "INTEGER")], dialect="postgresql"
        )
        options = GenerationOptions(dialect="postgresql")
        statements = generator._generate_table_property_changes(table_diff, expected_table, options)
        assert len(statements) > 0
        assert any(s.statement_type == "COMMENT" for s in statements)
        assert any("WARNING" in s.sql.upper() for s in statements)


@pytest.mark.unit
class TestDiffSqlGeneratorColumnFormatting:
    """Tests for column definition formatting."""

    def test_format_column_definition_basic(self):
        """Test formatting basic column definition."""
        generator = DiffSqlGenerator(dialect="postgresql")
        column = SqlColumn("id", "INTEGER")
        result = generator._format_column_definition(column)
        assert "INTEGER" in result

    def test_format_column_definition_not_null(self):
        """Test formatting column with NOT NULL."""
        generator = DiffSqlGenerator(dialect="postgresql")
        column = SqlColumn("id", "INTEGER", is_nullable=False)
        result = generator._format_column_definition(column)
        assert "NOT NULL" in result

    def test_format_column_definition_default(self):
        """Test formatting column with DEFAULT."""
        generator = DiffSqlGenerator(dialect="postgresql")
        column = SqlColumn("id", "INTEGER", default_value="0")
        result = generator._format_column_definition(column)
        assert "DEFAULT" in result
        assert "0" in result

    def test_format_column_definition_collation_postgresql(self):
        """Test formatting column with collation for PostgreSQL."""
        generator = DiffSqlGenerator(dialect="postgresql")
        column = SqlColumn("name", "VARCHAR(100)", collation="en_US.utf8")
        result = generator._format_column_definition(column)
        assert "COLLATE" in result.upper()

    def test_format_column_definition_identity_postgresql(self):
        """Test formatting identity column for PostgreSQL."""
        generator = DiffSqlGenerator(dialect="postgresql")
        column = SqlColumn("id", "INTEGER", is_identity=True, identity_generation="ALWAYS")
        result = generator._format_column_definition(column)
        assert "GENERATED" in result.upper()
        assert "IDENTITY" in result.upper()

    def test_format_column_definition_identity_mysql(self):
        """Test formatting identity column for MySQL."""
        generator = DiffSqlGenerator(dialect="mysql")
        column = SqlColumn("id", "INTEGER", is_identity=True)
        result = generator._format_column_definition(column)
        assert "AUTO_INCREMENT" in result.upper()

    def test_format_column_definition_computed_postgresql(self):
        """Test formatting computed column for PostgreSQL."""
        generator = DiffSqlGenerator(dialect="postgresql")
        column = SqlColumn(
            "full_name",
            "VARCHAR",
            is_computed=True,
            computed_expression="first_name || ' ' || last_name",
            computed_stored=True,
        )
        result = generator._format_column_definition(column)
        assert "GENERATED ALWAYS AS" in result.upper()
        assert "STORED" in result.upper()

    def test_format_column_definition_oracle_timestamp_default(self):
        """Test formatting Oracle timestamp default without parentheses."""
        generator = DiffSqlGenerator(dialect="oracle")
        column = SqlColumn("created_at", "TIMESTAMP", default_value="CURRENT_TIMESTAMP()")
        result = generator._format_column_definition(column)
        assert "CURRENT_TIMESTAMP" in result
        assert "()" not in result  # Should remove parentheses

    def test_format_column_definition_oracle_timestamp_precision(self):
        """Test formatting Oracle timestamp default with precision."""
        generator = DiffSqlGenerator(dialect="oracle")
        column = SqlColumn("created_at", "TIMESTAMP", default_value="CURRENT_TIMESTAMP(6)")
        result = generator._format_column_definition(column)
        assert "CURRENT_TIMESTAMP" in result
        # Should remove precision in DEFAULT clause


@pytest.mark.unit
class TestDiffSqlGeneratorQuoteIdentifier:
    """Tests for identifier quoting."""

    def test_quote_identifier_oracle(self):
        """Test quoting identifier for Oracle."""
        generator = DiffSqlGenerator(dialect="oracle")
        result = generator._quote_identifier("users")
        assert result == '"users"'

    def test_quote_identifier_sqlserver(self):
        """Test quoting identifier for SQL Server uses brackets."""
        generator = DiffSqlGenerator(dialect="sqlserver")
        result = generator._quote_identifier("users")
        assert result == "[users]"

    def test_quote_identifier_cosmosdb(self):
        """Test quoting identifier for CosmosDB.

        Story 26-5: CosmosDB is NoSQL — identifiers map to JSON property
        names, not SQL identifiers, so the plugin Quirks set
        ``quote_open=""``/``quote_close=""``. The earlier behaviour
        (fall through to default ``"`` quoting) was inconsistent with
        the SQL DDL emitter (``BasicTableDdlGenerator``), which already
        produced unquoted CosmosDB output.
        """
        generator = DiffSqlGenerator(dialect="cosmosdb")
        result = generator._quote_identifier("users")
        assert result == "users"

    def test_quote_identifier_unknown(self):
        """Test quoting identifier for unknown dialect.

        Story 21-14: the fallback is now ANSI double-quote (not bare identifier),
        which is safer and consistent with postgresql/oracle/db2/sqlite. CosmosDB
        is the exception (NoSQL — see ``test_quote_identifier_cosmosdb``).
        """
        # Use a dialect that's not explicitly handled but won't fail initialization
        generator = DiffSqlGenerator(dialect="postgresql")
        # Temporarily change dialect to test fallback
        generator.dialect = "unknown_dialect"
        result = generator._quote_identifier("users")
        assert result == '"users"'


@pytest.mark.unit
class TestDiffSqlGeneratorTableChangesAdvanced:
    """Tests for advanced table change scenarios."""

    def test_generate_table_changes_modify_constraints(self):
        """Test generating ALTER TABLE for modified constraints."""
        generator = DiffSqlGenerator(dialect="postgresql")
        from core.comparison.diff_models import ConstraintDiff

        constraint_diff = ConstraintDiff(
            object_name="pk_users", constraint_name="pk_users", constraint_type="PRIMARY_KEY"
        )
        table_diff = TableDiff(
            object_name="users",
            table_name="users",
            modified_constraints=[constraint_diff],
        )
        constraint = SqlConstraint(
            name="pk_users", constraint_type="PRIMARY_KEY", column_names=["id"]
        )
        expected_table = Table(
            name="users",
            columns=[SqlColumn("id", "INTEGER")],
            constraints=[constraint],
            dialect="postgresql",
        )
        options = GenerationOptions(dialect="postgresql")
        statements = generator._generate_table_changes(
            table_diff, {"users": expected_table}, options
        )
        assert len(statements) > 0

    def test_generate_table_changes_missing_indexes(self):
        """Test generating CREATE INDEX for missing table-level indexes."""
        generator = DiffSqlGenerator(dialect="postgresql")
        table_diff = TableDiff(
            object_name="users",
            table_name="users",
            missing_indexes=["idx_email"],
        )
        index = Index(name="idx_email", table_name="users", columns=["email"], dialect="postgresql")
        expected_table = Table(
            name="users", columns=[SqlColumn("id", "INTEGER")], dialect="postgresql"
        )
        expected_table.indexes = [index]
        options = GenerationOptions(dialect="postgresql")
        statements = generator._generate_table_changes(
            table_diff, {"users": expected_table}, options
        )
        assert len(statements) > 0
        assert any(s.statement_type == "CREATE" and s.object_type == "INDEX" for s in statements)

    def test_generate_table_changes_extra_indexes(self):
        """Test generating DROP INDEX for extra table-level indexes."""
        generator = DiffSqlGenerator(dialect="postgresql")
        table_diff = TableDiff(
            object_name="users",
            table_name="users",
            extra_indexes=["idx_old"],
        )
        expected_table = Table(
            name="users", columns=[SqlColumn("id", "INTEGER")], dialect="postgresql"
        )
        options = GenerationOptions(dialect="postgresql")
        statements = generator._generate_table_changes(
            table_diff, {"users": expected_table}, options
        )
        assert len(statements) > 0
        assert any(s.statement_type == "DROP" and s.object_type == "INDEX" for s in statements)

    def test_generate_table_changes_column_not_found(self):
        """Test handling when column not found in expected table."""
        generator = DiffSqlGenerator(dialect="postgresql")
        table_diff = TableDiff(
            object_name="users",
            table_name="users",
            missing_columns=["nonexistent"],
        )
        expected_table = Table(
            name="users", columns=[SqlColumn("id", "INTEGER")], dialect="postgresql"
        )
        options = GenerationOptions(dialect="postgresql")
        statements = generator._generate_table_changes(
            table_diff, {"users": expected_table}, options
        )
        # Column not found → warning logged, nothing generated
        assert isinstance(statements, list)
        assert len(statements) == 0

    def test_generate_table_changes_constraint_not_found(self):
        """Test handling when constraint not found in expected table."""
        generator = DiffSqlGenerator(dialect="postgresql")
        table_diff = TableDiff(
            object_name="users",
            table_name="users",
            missing_constraints=["nonexistent"],
        )
        expected_table = Table(
            name="users", columns=[SqlColumn("id", "INTEGER")], dialect="postgresql"
        )
        options = GenerationOptions(dialect="postgresql")
        statements = generator._generate_table_changes(
            table_diff, {"users": expected_table}, options
        )
        # Constraint not found → warning logged, nothing generated
        assert isinstance(statements, list)
        assert len(statements) == 0

    def test_generate_table_changes_index_not_found(self):
        """Test handling when table-level index not found."""
        generator = DiffSqlGenerator(dialect="postgresql")
        table_diff = TableDiff(
            object_name="users",
            table_name="users",
            missing_indexes=["nonexistent_index"],
        )
        expected_table = Table(
            name="users", columns=[SqlColumn("id", "INTEGER")], dialect="postgresql"
        )
        options = GenerationOptions(dialect="postgresql")
        statements = generator._generate_table_changes(
            table_diff, {"users": expected_table}, options
        )
        # Should still generate statements, just skip the missing index
        assert isinstance(statements, list)

    def test_generate_create_table_with_metadata(self):
        """Test generating CREATE CONTAINER with metadata partition key."""
        generator = DiffSqlGenerator(dialect="cosmosdb")
        table = Table(name="container1", columns=[], dialect="cosmosdb")
        table.metadata = {"partition_key": "/user_id"}
        options = GenerationOptions(dialect="cosmosdb")
        statement = generator._generate_create_table(table, options)
        assert statement is not None
        assert "/user_id" in statement.sql

    def test_generate_create_table_fallback(self):
        """Test generating CREATE TABLE with fallback generation."""
        generator = DiffSqlGenerator(dialect="postgresql")
        table = Table(
            name="users",
            columns=[SqlColumn("id", "INTEGER"), SqlColumn("name", "VARCHAR(100)")],
            dialect="postgresql",
        )
        # create_statement is a read-only property, so we test the fallback path
        # by ensuring it doesn't have a create_statement set (which is the default)
        options = GenerationOptions(dialect="postgresql")
        statement = generator._generate_create_table(table, options)
        assert statement is not None
        assert "CREATE TABLE" in statement.sql.upper()
        # Check that columns are included (either quoted or unquoted)
        sql_lower = statement.sql.lower()
        assert ("id" in sql_lower or '"id"' in statement.sql) and (
            "name" in sql_lower or '"name"' in statement.sql
        )

    def test_format_column_definition_collation_mysql(self):
        """Test formatting column with collation for MySQL."""
        generator = DiffSqlGenerator(dialect="mysql")
        column = SqlColumn("name", "VARCHAR(100)", collation="utf8mb4_general_ci")
        result = generator._format_column_definition(column)
        assert "COLLATE" in result.upper()
        assert "utf8mb4_general_ci" in result

    def test_format_column_definition_oracle_systimestamp(self):
        """Test formatting Oracle column with SYSTIMESTAMP default."""
        generator = DiffSqlGenerator(dialect="oracle")
        column = SqlColumn("created_at", "TIMESTAMP", default_value="SYSTIMESTAMP()")
        result = generator._format_column_definition(column)
        assert "SYSTIMESTAMP" in result
        assert "()" not in result  # Should remove parentheses

    def test_format_column_definition_oracle_systimestamp_precision(self):
        """Test formatting Oracle column with SYSTIMESTAMP precision."""
        generator = DiffSqlGenerator(dialect="oracle")
        column = SqlColumn("created_at", "TIMESTAMP", default_value="SYSTIMESTAMP(6)")
        result = generator._format_column_definition(column)
        assert "SYSTIMESTAMP" in result
        # Should remove precision in DEFAULT clause

    def test_format_column_definition_identity_by_default(self):
        """Test formatting identity column with BY DEFAULT generation."""
        generator = DiffSqlGenerator(dialect="postgresql")
        column = SqlColumn("id", "INTEGER", is_identity=True, identity_generation="BY DEFAULT")
        result = generator._format_column_definition(column)
        assert "GENERATED BY DEFAULT AS IDENTITY" in result

    def test_format_column_definition_identity_sqlserver(self):
        """Test formatting identity column for SQL Server."""
        generator = DiffSqlGenerator(dialect="sqlserver")
        column = SqlColumn("id", "INTEGER", is_identity=True)
        result = generator._format_column_definition(column)
        assert "IDENTITY(1,1)" in result

    def test_format_column_definition_computed_sqlserver(self):
        """Test formatting computed column for SQL Server."""
        generator = DiffSqlGenerator(dialect="sqlserver")
        column = SqlColumn(
            "full_name",
            "VARCHAR",
            is_computed=True,
            computed_expression="first_name + ' ' + last_name",
            computed_stored=True,
        )
        result = generator._format_column_definition(column)
        assert "AS (" in result
        assert "PERSISTED" in result.upper()

    def test_format_column_definition_computed_sqlserver_virtual(self):
        """Test formatting virtual computed column for SQL Server."""
        generator = DiffSqlGenerator(dialect="sqlserver")
        column = SqlColumn(
            "full_name",
            "VARCHAR",
            is_computed=True,
            computed_expression="first_name + ' ' + last_name",
            computed_stored=False,
        )
        result = generator._format_column_definition(column)
        assert "AS (" in result
        assert "PERSISTED" not in result.upper()

    def test_generate_table_property_changes_all_recreation_properties(self):
        """Test generating warnings for all recreation properties."""
        generator = DiffSqlGenerator(dialect="postgresql")
        table_diff = TableDiff(
            object_name="users",
            table_name="users",
            temporary_changed=True,
            filegroup_changed=True,
            memory_optimized_changed=True,
            history_table_changed=True,
            partition_method_changed=True,
            compress_changed=True,
            logged_changed=True,
            organize_by_changed=True,
        )
        expected_table = Table(
            name="users", columns=[SqlColumn("id", "INTEGER")], dialect="postgresql"
        )
        options = GenerationOptions(dialect="postgresql")
        statements = generator._generate_table_property_changes(table_diff, expected_table, options)
        assert len(statements) > 0
        assert any(s.statement_type == "COMMENT" for s in statements)
        warning_stmt = next(s for s in statements if s.statement_type == "COMMENT")
        assert "temporary property" in warning_stmt.sql.lower()
        assert "filegroup" in warning_stmt.sql.lower()
        assert "memory-optimized" in warning_stmt.sql.lower()
        assert "history table" in warning_stmt.sql.lower()
        assert "partitioning" in warning_stmt.sql.lower()
        assert "compression" in warning_stmt.sql.lower()
        assert "logged property" in warning_stmt.sql.lower()
        assert "organize_by property" in warning_stmt.sql.lower()

    def test_generate_table_property_changes_inherits_single_string(self):
        """Test generating INHERIT for single string parent."""
        generator = DiffSqlGenerator(dialect="postgresql")
        table_diff = TableDiff(
            object_name="users",
            table_name="users",
            inherits_changed=("parent", []),
        )
        expected_table = Table(
            name="users", columns=[SqlColumn("id", "INTEGER")], dialect="postgresql"
        )
        options = GenerationOptions(dialect="postgresql")
        statements = generator._generate_table_property_changes(table_diff, expected_table, options)
        assert len(statements) > 0
        assert any("INHERIT" in s.sql.upper() for s in statements)

    def test_generate_table_property_changes_inherits_list(self):
        """Test generating INHERIT for list of parents."""
        generator = DiffSqlGenerator(dialect="postgresql")
        table_diff = TableDiff(
            object_name="users",
            table_name="users",
            inherits_changed=(["parent1", "parent2"], []),
        )
        expected_table = Table(
            name="users", columns=[SqlColumn("id", "INTEGER")], dialect="postgresql"
        )
        options = GenerationOptions(dialect="postgresql")
        statements = generator._generate_table_property_changes(table_diff, expected_table, options)
        assert len(statements) >= 2  # One INHERIT per parent

    def test_generate_table_property_changes_system_versioning_defaults(self):
        """Test generating system versioning with default history table."""
        generator = DiffSqlGenerator(dialect="sqlserver")
        expected_table = Table.from_options(
            name="users",
            columns=[SqlColumn("id", "INTEGER")],
            dialect="sqlserver",
            options=TableOptions(sqlserver=SqlServerTableOptions(system_versioned=True)),
        )
        table_diff = TableDiff(
            object_name="users",
            table_name="users",
            system_versioned_changed=True,
        )
        options = GenerationOptions(dialect="sqlserver")
        statements = generator._generate_table_property_changes(table_diff, expected_table, options)
        assert len(statements) > 0
        assert any("users_History" in s.sql or "HISTORY_TABLE" in s.sql.upper() for s in statements)


@pytest.mark.unit
class TestQuoteIdentifierSqlServer:
    """Tests for NEW-BUG-15: SQL Server _quote_identifier should use brackets."""

    def test_quote_identifier_sqlserver_uses_brackets(self):
        """_quote_identifier('my_table') should return [my_table] for sqlserver."""
        generator = DiffSqlGenerator(dialect="sqlserver")
        result = generator._quote_identifier("my_table")
        assert result == "[my_table]"


@pytest.mark.unit
class TestDiffGenerationContext:
    """Tests for DiffGenerationContext dataclass (story 14-6)."""

    def test_diff_generation_context_is_dataclass(self):
        """AC#6.1: DiffGenerationContext is a dataclass."""
        assert is_dataclass(DiffGenerationContext)

    def test_diff_generation_context_default_all_none(self):
        """AC#6.2: All fields default to None."""
        ctx = DiffGenerationContext()
        for f in fields(ctx):
            assert getattr(ctx, f.name) is None, f"Field {f.name} should default to None"

    def test_diff_generation_context_fields_count(self):
        """AC#6.3: 17 expected_* fields (modules re-added as active pipeline)."""
        assert len(fields(DiffGenerationContext)) == 17

    def test_generate_from_diff_accepts_context(self):
        """AC#6.4: generate_from_diff accepts context parameter without error."""
        generator = DiffSqlGenerator(dialect="postgresql")
        diff = SchemaDiff(object_name="public", schema_name="public")
        table = Table(name="users", columns=[SqlColumn(name="id", data_type="INTEGER")])
        ctx = DiffGenerationContext(expected_tables={"users": table})
        result = generator.generate_from_diff(diff, context=ctx)
        assert result == []  # empty diff → no statements generated

    def test_generate_from_diff_context_none_default(self):
        """AC#7: Calling without context or options does not raise."""
        generator = DiffSqlGenerator(dialect="postgresql")
        diff = SchemaDiff(object_name="public", schema_name="public")
        result = generator.generate_from_diff(diff)
        assert isinstance(result, list)
        assert len(result) == 0

    def test_generate_from_diff_expected_tables_via_context(self):
        """AC#8: expected_tables via context generates CREATE TABLE for missing tables."""
        generator = DiffSqlGenerator(dialect="postgresql")
        diff = SchemaDiff(object_name="public", schema_name="public", missing_tables=["users"])
        table = Table(
            name="users",
            columns=[SqlColumn(name="id", data_type="INTEGER")],
        )
        ctx = DiffGenerationContext(expected_tables={"users": table})
        result = generator.generate_from_diff(diff, context=ctx)
        assert len(result) >= 1
        create_stmts = [
            s for s in result if s.statement_type == "CREATE" and s.object_type == "TABLE"
        ]
        assert len(create_stmts) == 1


@pytest.mark.unit
class TestDiffSqlGeneratorSimp10Regression:
    """Regression test for SIMP-10: module-level logger must not exist in diff_sql_generator."""

    def test_no_module_level_logger_in_diff_sql_generator(self):
        """SIMP-10 regression: module-level `logger` variable must not exist in diff_sql_generator.

        Only self.logger (instance attribute) should be used. The module-level variable
        was dead code (never referenced), removed in story 14-10.
        """
        import core.sql_generator.diff_sql_generator as mod

        assert "logger" not in vars(mod), (
            "Module-level 'logger' must not exist in diff_sql_generator — "
            "use self.logger (instance attribute) instead"
        )


@pytest.mark.unit
class TestObjectTypeSpecsByType:
    """Tests story 15-5 : remplacement de l'accès par indice codé en dur par lookup par nom."""

    def test_dict_exists_and_contains_index(self):
        """AC#2 — _OBJECT_TYPE_SPECS_BY_TYPE est accessible et contient 'INDEX'."""
        from core.sql_generator.diff_sql_generator import _OBJECT_TYPE_SPECS_BY_TYPE

        assert (
            "INDEX" in _OBJECT_TYPE_SPECS_BY_TYPE
        ), "'INDEX' must be a key in _OBJECT_TYPE_SPECS_BY_TYPE"
        assert _OBJECT_TYPE_SPECS_BY_TYPE["INDEX"].object_type == "INDEX"

    def test_dict_covers_all_types(self):
        """AC#2 — le dict couvre toutes les entrées de _OBJECT_TYPE_SPECS."""
        from core.sql_generator.diff_sql_generator import (
            _OBJECT_TYPE_SPECS,
            _OBJECT_TYPE_SPECS_BY_TYPE,
        )

        expected_types = {spec.object_type for spec in _OBJECT_TYPE_SPECS}
        assert (
            set(_OBJECT_TYPE_SPECS_BY_TYPE.keys()) == expected_types
        ), "_OBJECT_TYPE_SPECS_BY_TYPE must cover all object types in _OBJECT_TYPE_SPECS"
        assert len(_OBJECT_TYPE_SPECS_BY_TYPE) == len(_OBJECT_TYPE_SPECS), (
            "_OBJECT_TYPE_SPECS_BY_TYPE must have one entry per spec "
            "(duplicate object_type in _OBJECT_TYPE_SPECS would silently collapse entries)"
        )

    def test_hardcoded_index_access_removed(self):
        """AC#1 — _OBJECT_TYPE_SPECS[1] n'apparaît plus dans le source."""
        import inspect

        import core.sql_generator.diff_sql_generator as mod

        source = inspect.getsource(mod)
        assert (
            "_OBJECT_TYPE_SPECS[1]" not in source
        ), "Hardcoded _OBJECT_TYPE_SPECS[1] must be replaced by name-based lookup"

    def test_generate_table_changes_missing_index_uses_index_spec(self):
        """AC#3 — missing_indexes génère un CREATE INDEX avec object_type='INDEX'."""
        generator = DiffSqlGenerator(dialect="postgresql")
        index = Index(
            name="idx_email",
            table_name="users",
            columns=["email"],
            dialect="postgresql",
        )
        expected_table = Table(
            name="users",
            columns=[SqlColumn("id", "INTEGER")],
            dialect="postgresql",
        )
        expected_table.indexes = [index]
        table_diff = TableDiff(
            object_name="users",
            table_name="users",
            missing_indexes=["idx_email"],
        )
        options = GenerationOptions(dialect="postgresql")

        statements = generator._generate_table_changes(
            table_diff, {"users": expected_table}, options
        )

        create_index_stmts = [
            s for s in statements if s.object_type == "INDEX" and s.statement_type == "CREATE"
        ]
        assert len(create_index_stmts) == 1, (
            f"Expected 1 CREATE INDEX statement, got {len(create_index_stmts)}: "
            f"{[s.sql for s in statements]}"
        )
        assert create_index_stmts[0].object_name == "idx_email"

    def test_generate_table_changes_extra_index_generates_drop(self):
        """L1 — extra_indexes génère un DROP INDEX (chemin symétrique à AC#3)."""
        generator = DiffSqlGenerator(dialect="postgresql")
        expected_table = Table(
            name="users",
            columns=[SqlColumn("id", "INTEGER")],
            dialect="postgresql",
        )
        expected_table.indexes = []
        table_diff = TableDiff(
            object_name="users",
            table_name="users",
            extra_indexes=["idx_obsolete"],
        )
        options = GenerationOptions(dialect="postgresql")

        statements = generator._generate_table_changes(
            table_diff, {"users": expected_table}, options
        )

        drop_index_stmts = [
            s for s in statements if s.object_type == "INDEX" and s.statement_type == "DROP"
        ]
        assert len(drop_index_stmts) == 1, (
            f"Expected 1 DROP INDEX statement, got {len(drop_index_stmts)}: "
            f"{[s.sql for s in statements]}"
        )
        assert drop_index_stmts[0].object_name == "idx_obsolete"


@pytest.mark.unit
class TestDeadCodeRemoved:
    """Verify dead methods were removed from DiffSqlGenerator."""

    def test_generate_drop_column_method_removed(self):
        """AC#6.1: _generate_drop_column must not exist on DiffSqlGenerator."""
        assert not hasattr(DiffSqlGenerator, "_generate_drop_column")

    def test_generate_add_column_method_removed(self):
        """AC#6.2: _generate_add_column must not exist on DiffSqlGenerator."""
        assert not hasattr(DiffSqlGenerator, "_generate_add_column")


@pytest.mark.unit
class TestDialectCaseNormalization:
    """Tests for dialect case normalization in __init__ (Story 15-15, AC#4)."""

    @pytest.mark.parametrize(
        "input_dialect,expected",
        [
            ("PostgreSQL", "postgresql"),
            ("ORACLE", "oracle"),
            ("MySQL", "mysql"),
            ("SqlServer", "sqlserver"),
            ("COSMOSDB", "cosmosdb"),
            ("DB2", "db2"),
        ],
    )
    def test_dialect_normalized_to_lowercase_in_init(self, input_dialect, expected):
        """AC#4.1: dialect is stored lowercase regardless of input casing."""
        generator = DiffSqlGenerator(input_dialect)
        assert generator.dialect == expected

    def test_uppercase_dialect_format_column_definition(self):
        """AC#4.2: _format_column_definition behaves identically with uppercase dialect.

        Uses a column with Oracle-specific default_value so the Oracle code path
        (L826-838 of diff_sql_generator.py) is actually exercised.
        """
        col = SqlColumn(
            name="created_at",
            data_type="TIMESTAMP",
            is_nullable=False,
            default_value="CURRENT_TIMESTAMP()",
        )

        gen_upper = DiffSqlGenerator("ORACLE")
        gen_lower = DiffSqlGenerator("oracle")

        result_upper = gen_upper._format_column_definition(col)
        result_lower = gen_lower._format_column_definition(col)

        assert result_upper == result_lower
        # Oracle normalizes CURRENT_TIMESTAMP() → CURRENT_TIMESTAMP (strips parens)
        assert "DEFAULT CURRENT_TIMESTAMP" in result_upper
        assert "DEFAULT CURRENT_TIMESTAMP()" not in result_upper

    def test_column_converter_dialect_normalized(self):
        """L1: ColumnConverter receives the lowercased dialect from __init__."""
        generator = DiffSqlGenerator("MySQL")
        assert generator.column_converter.dialect == "mysql"

    def test_mixed_case_dialect_quote_identifier(self):
        """AC#4.3: _quote_identifier behaves identically with mixed-case dialect."""
        gen_upper = DiffSqlGenerator("MySQL")
        gen_lower = DiffSqlGenerator("mysql")

        result_upper = gen_upper._quote_identifier("table_name")
        result_lower = gen_lower._quote_identifier("table_name")

        assert result_upper == result_lower
        assert result_upper == "`table_name`"
