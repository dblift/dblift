"""Tests for SQLiteSqlGenerator class."""

from unittest.mock import MagicMock

import pytest

from core.sql_model.base import SqlColumn, SqlConstraint, SqlObjectType
from core.sql_model.index import Index
from core.sql_model.table import Table
from core.sql_model.table_options import TableOptions
from core.sql_model.trigger import Trigger
from core.sql_model.view import View
from db.plugins.sqlite.generator.ddl_generator import SQLiteSqlGenerator


@pytest.mark.unit
class TestSQLiteSqlGeneratorInit:
    """Tests for SQLiteSqlGenerator initialization."""

    def test_init(self):
        """Test initialization."""
        generator = SQLiteSqlGenerator()
        assert generator is not None


@pytest.mark.unit
class TestSQLiteSqlGeneratorDialectSpecific:
    """Tests for dialect-specific methods."""

    def test_requires_dialect_specific_wrapping(self):
        """Test _requires_dialect_specific_wrapping always returns False."""
        generator = SQLiteSqlGenerator()
        obj = MagicMock()
        result = generator._requires_dialect_specific_wrapping(obj, "sqlite")
        assert result is False

    def test_wrap_dialect_specific_block(self):
        """Test _wrap_dialect_specific_block returns SQL unchanged."""
        generator = SQLiteSqlGenerator()
        sql = "CREATE TABLE users (id INT)"
        result = generator._wrap_dialect_specific_block(sql, "sqlite")
        assert result == sql

    def test_should_skip_formatting_trigger(self):
        """Test _should_skip_formatting for trigger."""
        generator = SQLiteSqlGenerator()
        trigger = Trigger(
            name="trg_insert", table_name="users", events=["INSERT"], dialect="sqlite"
        )
        result = generator._should_skip_formatting(trigger, "CREATE TRIGGER trg_insert...")
        assert result is True

    def test_should_skip_formatting_non_trigger(self):
        """Test _should_skip_formatting for non-trigger."""
        generator = SQLiteSqlGenerator()
        table = Table(name="users", columns=[SqlColumn("id", "INTEGER")], dialect="sqlite")
        result = generator._should_skip_formatting(table, "CREATE TABLE users...")
        assert result is False

    def test_should_skip_formatting_empty_sql(self):
        """Test _should_skip_formatting with empty SQL."""
        generator = SQLiteSqlGenerator()
        table = Table(name="users", columns=[SqlColumn("id", "INTEGER")], dialect="sqlite")
        result = generator._should_skip_formatting(table, "")
        assert result is False


@pytest.mark.unit
class TestSQLiteSqlGeneratorFormatStatements:
    """Tests for _format_statements method."""

    def test_format_statements_empty(self):
        """Test formatting empty statements list."""
        generator = SQLiteSqlGenerator()
        result = generator._format_statements([], "sqlite")
        assert result == ""

    def test_format_statements_single(self):
        """Test formatting single statement."""
        generator = SQLiteSqlGenerator()
        statements = ["CREATE TABLE users (id INT)"]
        result = generator._format_statements(statements, "sqlite")
        assert result == "CREATE TABLE users (id INT)"

    def test_format_statements_multiple(self):
        """Test formatting multiple statements."""
        generator = SQLiteSqlGenerator()
        statements = ["CREATE TABLE users (id INT)", "CREATE TABLE orders (id INT)"]
        result = generator._format_statements(statements, "sqlite")
        assert "CREATE TABLE users" in result
        assert "CREATE TABLE orders" in result
        assert "\n\n" in result

    def test_format_statements_filters_empty(self):
        """Test filtering empty statements."""
        generator = SQLiteSqlGenerator()
        statements = ["CREATE TABLE users (id INT)", "", "   ", "CREATE TABLE orders (id INT)"]
        result = generator._format_statements(statements, "sqlite")
        assert "CREATE TABLE users" in result
        assert "CREATE TABLE orders" in result


@pytest.mark.unit
class TestSQLiteSqlGeneratorDropStatement:
    """Tests for _generate_drop_statement method."""

    def test_generate_drop_statement_table(self):
        """Test generating DROP TABLE statement."""
        generator = SQLiteSqlGenerator()
        table = Table(name="users", columns=[SqlColumn("id", "INTEGER")], dialect="sqlite")
        result = generator._generate_drop_statement(table, "sqlite")
        assert "DROP TABLE IF EXISTS" in result.upper()
        assert "users" in result.lower() or '"users"' in result

    def test_generate_drop_statement_virtual_table(self):
        """SQLite drops virtual tables with DROP TABLE."""
        generator = SQLiteSqlGenerator()
        table = Table.from_options(
            name="users_fts",
            dialect="sqlite",
            object_type=SqlObjectType.VIRTUAL_TABLE,
            options=TableOptions(raw_ddl="CREATE VIRTUAL TABLE users_fts USING fts5(name)"),
        )
        result = generator._generate_drop_statement(table, "sqlite")
        assert result == 'DROP TABLE IF EXISTS "users_fts"'

    def test_generate_drop_statement_view(self):
        """Test generating DROP VIEW statement."""
        generator = SQLiteSqlGenerator()
        view = View(name="active_users", query="SELECT 1", dialect="sqlite")
        result = generator._generate_drop_statement(view, "sqlite")
        assert "DROP VIEW IF EXISTS" in result.upper()
        assert "active_users" in result.lower() or '"active_users"' in result

    def test_generate_drop_statement_index(self):
        """Test generating DROP INDEX statement."""
        generator = SQLiteSqlGenerator()
        index = Index(name="idx_email", table_name="users", columns=["email"], dialect="sqlite")
        result = generator._generate_drop_statement(index, "sqlite")
        assert "DROP INDEX IF EXISTS" in result.upper()
        assert "idx_email" in result.lower() or '"idx_email"' in result

    def test_generate_drop_statement_trigger(self):
        """Test generating DROP TRIGGER statement."""
        generator = SQLiteSqlGenerator()
        trigger = Trigger(
            name="trg_insert", table_name="users", events=["INSERT"], dialect="sqlite"
        )
        result = generator._generate_drop_statement(trigger, "sqlite")
        assert "DROP TRIGGER IF EXISTS" in result.upper()
        assert "trg_insert" in result.lower() or '"trg_insert"' in result

    def test_generate_drop_statement_fallback(self):
        """Test generating DROP statement fallback."""
        generator = SQLiteSqlGenerator()
        obj = MagicMock()
        obj.name = "test_obj"
        obj.format_identifier = lambda x: x
        obj.object_type = "UNKNOWN_TYPE"
        result = generator._generate_drop_statement(obj, "sqlite")
        assert "DROP UNKNOWN_TYPE IF EXISTS" in result.upper()


@pytest.mark.unit
class TestSQLiteSqlGeneratorCreateStatement:
    """Tests for generate_create_statement method."""

    def test_generate_create_statement_view(self):
        """Test generating CREATE VIEW statement."""
        generator = SQLiteSqlGenerator()
        view = View(name="active_users", query="SELECT id FROM users", dialect="sqlite")
        result = generator.generate_create_statement(view)
        assert "CREATE VIEW" in result.upper()
        assert "active_users" in result.lower() or '"active_users"' in result

    def test_generate_create_statement_index(self):
        """Test generating CREATE INDEX statement."""
        generator = SQLiteSqlGenerator()
        index = Index(name="idx_email", table_name="users", columns=["email"], dialect="sqlite")
        result = generator.generate_create_statement(index)
        assert "CREATE INDEX" in result.upper()
        assert "idx_email" in result.lower() or '"idx_email"' in result

    def test_generate_create_statement_table(self):
        """Test generating CREATE TABLE statement."""
        generator = SQLiteSqlGenerator()
        table = Table(
            name="users",
            columns=[SqlColumn("id", "INTEGER"), SqlColumn("name", "TEXT")],
            dialect="sqlite",
        )
        result = generator.generate_create_statement(table)
        assert "CREATE TABLE" in result.upper()
        assert "users" in result.lower() or '"users"' in result

    def test_generate_create_statement_trigger(self):
        """Test generating CREATE TRIGGER statement."""
        generator = SQLiteSqlGenerator()
        trigger = Trigger(
            name="trg_insert", table_name="users", events=["INSERT"], dialect="sqlite"
        )
        result = generator.generate_create_statement(trigger)
        assert "CREATE TRIGGER" in result.upper()
        assert "trg_insert" in result.lower() or '"trg_insert"' in result

    def test_generate_create_statement_fallback_with_create_statement(self):
        """Test fallback to object's create_statement method."""
        generator = SQLiteSqlGenerator()
        obj = MagicMock()
        obj.create_statement = MagicMock(return_value="CREATE TEST_OBJ")
        result = generator.generate_create_statement(obj)
        assert result == "CREATE TEST_OBJ"

    def test_generate_create_statement_fallback_no_create_statement(self):
        """Test fallback when object has no create_statement."""
        generator = SQLiteSqlGenerator()
        obj = MagicMock()
        del obj.create_statement
        result = generator.generate_create_statement(obj)
        assert result == ""


@pytest.mark.unit
class TestSQLiteSqlGeneratorViewCreate:
    """Tests for _generate_view_create_statement method."""

    def test_generate_view_create_statement_simple(self):
        """Test generating simple CREATE VIEW statement."""
        generator = SQLiteSqlGenerator()
        view = View(name="active_users", query="SELECT id FROM users", dialect="sqlite")
        result = generator._generate_view_create_statement(view)
        assert "CREATE VIEW" in result.upper()
        assert "active_users" in result.lower() or '"active_users"' in result
        assert "SELECT id FROM users" in result

    def test_generate_view_create_statement_temp(self):
        """Test generating CREATE TEMP VIEW statement."""
        generator = SQLiteSqlGenerator()
        view = View(name="active_users", query="SELECT 1", dialect="sqlite")
        view.is_temporary = True
        result = generator._generate_view_create_statement(view)
        assert "CREATE TEMP VIEW" in result.upper()

    def test_generate_view_create_statement_if_not_exists(self):
        """Test generating CREATE VIEW IF NOT EXISTS."""
        generator = SQLiteSqlGenerator()
        view = View(name="active_users", query="SELECT 1", dialect="sqlite")
        view.if_not_exists = True
        result = generator._generate_view_create_statement(view)
        assert "IF NOT EXISTS" in result.upper()

    def test_generate_view_create_statement_with_column_names(self):
        """Test generating CREATE VIEW with column names."""
        generator = SQLiteSqlGenerator()
        view = View(name="active_users", query="SELECT id, name FROM users", dialect="sqlite")
        view.column_names = ["id", "name"]
        result = generator._generate_view_create_statement(view)
        assert "active_users" in result.lower() or '"active_users"' in result
        assert "id" in result.lower() or '"id"' in result
        assert "name" in result.lower() or '"name"' in result

    def test_generate_view_create_statement_with_definition(self):
        """Test generating CREATE VIEW from definition."""
        generator = SQLiteSqlGenerator()
        view = View(name="active_users", query=None, dialect="sqlite")
        view.definition = "SELECT id FROM users"
        result = generator._generate_view_create_statement(view)
        assert "SELECT id FROM users" in result


@pytest.mark.unit
class TestSQLiteSqlGeneratorIndexCreate:
    """Tests for _generate_index_create_statement method."""

    def test_generate_index_create_statement_simple(self):
        """Test generating simple CREATE INDEX statement."""
        generator = SQLiteSqlGenerator()
        index = Index(name="idx_email", table_name="users", columns=["email"], dialect="sqlite")
        result = generator._generate_index_create_statement(index)
        assert "CREATE INDEX" in result.upper()
        assert "idx_email" in result.lower() or '"idx_email"' in result
        assert "ON" in result.upper()
        assert "users" in result.lower() or '"users"' in result

    def test_generate_index_create_statement_unique(self):
        """Test generating CREATE UNIQUE INDEX statement."""
        generator = SQLiteSqlGenerator()
        index = Index(
            name="idx_email", table_name="users", columns=["email"], unique=True, dialect="sqlite"
        )
        result = generator._generate_index_create_statement(index)
        assert "CREATE UNIQUE INDEX" in result.upper()

    def test_generate_index_create_statement_if_not_exists(self):
        """Test generating CREATE INDEX IF NOT EXISTS."""
        generator = SQLiteSqlGenerator()
        index = Index(name="idx_email", table_name="users", columns=["email"], dialect="sqlite")
        index.if_not_exists = True
        result = generator._generate_index_create_statement(index)
        assert "IF NOT EXISTS" in result.upper()

    def test_generate_index_create_statement_with_expression(self):
        """Test generating CREATE INDEX with expression."""
        generator = SQLiteSqlGenerator()
        index = Index(
            name="idx_expr",
            table_name="users",
            columns=["UPPER(email)"],
            expression_flags=[True],
            dialect="sqlite",
        )
        result = generator._generate_index_create_statement(index)
        assert "UPPER(email)" in result

    def test_generate_index_create_statement_with_dict_columns(self):
        """Test generating CREATE INDEX with dict columns."""
        generator = SQLiteSqlGenerator()
        index = Index(
            name="idx_email",
            table_name="users",
            columns=[{"name": "email", "order": "DESC"}],
            dialect="sqlite",
        )
        result = generator._generate_index_create_statement(index)
        assert "DESC" in result.upper()

    def test_generate_index_create_statement_with_where_clause(self):
        """Test generating CREATE INDEX with WHERE clause."""
        generator = SQLiteSqlGenerator()
        index = Index(name="idx_email", table_name="users", columns=["email"], dialect="sqlite")
        index.where_clause = "email IS NOT NULL"
        result = generator._generate_index_create_statement(index)
        assert "WHERE" in result.upper()
        assert "email IS NOT NULL" in result


@pytest.mark.unit
class TestSQLiteSqlGeneratorTableCreate:
    """Tests for _generate_table_create_statement method."""

    def test_generate_table_create_statement_simple(self):
        """Test generating simple CREATE TABLE statement."""
        generator = SQLiteSqlGenerator()
        table = Table(
            name="users",
            columns=[SqlColumn("id", "INTEGER"), SqlColumn("name", "TEXT")],
            dialect="sqlite",
        )
        result = generator._generate_table_create_statement(table)
        assert "CREATE TABLE" in result.upper()
        assert "users" in result.lower() or '"users"' in result
        assert "id" in result.lower() or '"id"' in result
        assert "name" in result.lower() or '"name"' in result

    def test_generate_table_create_statement_virtual_table_uses_raw_ddl(self):
        """FTS virtual tables must preserve their original CREATE VIRTUAL TABLE DDL."""
        generator = SQLiteSqlGenerator()
        ddl = "CREATE VIRTUAL TABLE users_fts USING fts5(name, email);"
        table = Table.from_options(
            name="users_fts",
            columns=[SqlColumn("name", "TEXT"), SqlColumn("email", "TEXT")],
            dialect="sqlite",
            object_type=SqlObjectType.VIRTUAL_TABLE,
            options=TableOptions(raw_ddl=ddl),
        )

        result = generator._generate_table_create_statement(table)

        assert result == "CREATE VIRTUAL TABLE users_fts USING fts5(name, email)"
        assert "CREATE TABLE" not in result.upper()

    def test_generate_table_create_statement_temp(self):
        """Test generating CREATE TEMP TABLE statement."""
        generator = SQLiteSqlGenerator()
        table = Table(name="users", columns=[SqlColumn("id", "INTEGER")], dialect="sqlite")
        table.is_temporary = True
        result = generator._generate_table_create_statement(table)
        assert "CREATE TEMP TABLE" in result.upper()

    def test_generate_table_create_statement_if_not_exists(self):
        """Test generating CREATE TABLE IF NOT EXISTS."""
        generator = SQLiteSqlGenerator()
        table = Table(name="users", columns=[SqlColumn("id", "INTEGER")], dialect="sqlite")
        table.if_not_exists = True
        result = generator._generate_table_create_statement(table)
        assert "IF NOT EXISTS" in result.upper()

    def test_generate_table_create_statement_without_rowid(self):
        """Test generating CREATE TABLE WITHOUT ROWID."""
        generator = SQLiteSqlGenerator()
        table = Table(name="users", columns=[SqlColumn("id", "INTEGER")], dialect="sqlite")
        table.without_rowid = True
        result = generator._generate_table_create_statement(table)
        assert "WITHOUT ROWID" in result.upper()

    def test_generate_table_create_statement_strict(self):
        """Test generating CREATE TABLE STRICT."""
        generator = SQLiteSqlGenerator()
        table = Table(name="users", columns=[SqlColumn("id", "INTEGER")], dialect="sqlite")
        table.strict = True
        result = generator._generate_table_create_statement(table)
        assert "STRICT" in result.upper()

    def test_generate_table_create_statement_with_constraints(self):
        """Test generating CREATE TABLE with constraints."""
        generator = SQLiteSqlGenerator()
        constraint = SqlConstraint(
            name="pk_users", constraint_type="PRIMARY_KEY", column_names=["id"]
        )
        table = Table(
            name="users",
            columns=[SqlColumn("id", "INTEGER")],
            constraints=[constraint],
            dialect="sqlite",
        )
        result = generator._generate_table_create_statement(table)
        assert "PRIMARY KEY" in result.upper()


@pytest.mark.unit
class TestSQLiteSqlGeneratorColumnDefinition:
    """Tests for _generate_column_definition method."""

    def test_generate_column_definition_simple(self):
        """Test generating simple column definition."""
        generator = SQLiteSqlGenerator()
        table = Table(name="users", columns=[], dialect="sqlite")
        column = SqlColumn("id", "INTEGER")
        result = generator._generate_column_definition(column, table)
        assert "id" in result.lower() or '"id"' in result
        assert "INTEGER" in result.upper()

    def test_generate_column_definition_primary_key(self):
        """Test generating column with PRIMARY KEY."""
        generator = SQLiteSqlGenerator()
        table = Table(name="users", columns=[], dialect="sqlite")
        column = SqlColumn("id", "INTEGER")
        column.is_primary_key = True
        result = generator._generate_column_definition(column, table)
        assert "PRIMARY KEY" in result.upper()

    def test_generate_column_definition_autoincrement(self):
        """Test generating column with AUTOINCREMENT."""
        generator = SQLiteSqlGenerator()
        table = Table(name="users", columns=[], dialect="sqlite")
        column = SqlColumn("id", "INTEGER")
        column.is_primary_key = True
        column.auto_increment = True
        result = generator._generate_column_definition(column, table)
        assert "AUTOINCREMENT" in result.upper()

    def test_generate_column_definition_not_null(self):
        """Test generating column with NOT NULL."""
        generator = SQLiteSqlGenerator()
        table = Table(name="users", columns=[], dialect="sqlite")
        column = SqlColumn("id", "INTEGER", is_nullable=False)
        result = generator._generate_column_definition(column, table)
        assert "NOT NULL" in result.upper()

    def test_generate_column_definition_nullable_true_no_not_null(self):
        """Test that nullable=True does NOT produce NOT NULL."""
        generator = SQLiteSqlGenerator()
        table = Table(name="users", columns=[], dialect="sqlite")
        column = SqlColumn("id", "INTEGER", is_nullable=True)
        result = generator._generate_column_definition(column, table)
        assert "NOT NULL" not in result.upper()

    def test_generate_column_definition_computed_stored(self):
        """Test generating computed column STORED."""
        generator = SQLiteSqlGenerator()
        table = Table(name="users", columns=[], dialect="sqlite")
        column = SqlColumn(
            "full_name",
            "TEXT",
            is_computed=True,
            computed_expression="first_name || ' ' || last_name",
            computed_stored=True,
        )
        result = generator._generate_column_definition(column, table)
        assert "GENERATED ALWAYS AS" in result.upper()
        assert "STORED" in result.upper()

    def test_generate_column_definition_computed_virtual(self):
        """Test generating computed column VIRTUAL."""
        generator = SQLiteSqlGenerator()
        table = Table(name="users", columns=[], dialect="sqlite")
        column = SqlColumn(
            "full_name",
            "TEXT",
            is_computed=True,
            computed_expression="first_name || ' ' || last_name",
            computed_stored=False,
        )
        result = generator._generate_column_definition(column, table)
        assert "GENERATED ALWAYS AS" in result.upper()
        assert "VIRTUAL" in result.upper()

    def test_generate_column_definition_default_string(self):
        """Test generating column with string DEFAULT."""
        generator = SQLiteSqlGenerator()
        table = Table(name="users", columns=[], dialect="sqlite")
        column = SqlColumn("name", "TEXT", default_value="unknown")
        result = generator._generate_column_definition(column, table)
        assert "DEFAULT" in result.upper()
        assert "unknown" in result.lower()

    def test_generate_column_definition_default_function(self):
        """Test generating column with function DEFAULT."""
        generator = SQLiteSqlGenerator()
        table = Table(name="users", columns=[], dialect="sqlite")
        column = SqlColumn("created_at", "TEXT", default_value="datetime('now')")
        result = generator._generate_column_definition(column, table)
        assert "DEFAULT" in result.upper()
        assert "datetime" in result.lower()

    def test_generate_column_definition_default_quoted_string(self):
        """Test generating column with quoted string DEFAULT."""
        generator = SQLiteSqlGenerator()
        table = Table(name="users", columns=[], dialect="sqlite")
        column = SqlColumn("name", "TEXT", default_value="'default'")
        result = generator._generate_column_definition(column, table)
        assert "DEFAULT" in result.upper()

    def test_generate_column_definition_check_constraint(self):
        """Test generating column with CHECK constraint."""
        generator = SQLiteSqlGenerator()
        table = Table(name="users", columns=[], dialect="sqlite")
        column = SqlColumn("age", "INTEGER")
        column.check_constraint = "age >= 0"
        result = generator._generate_column_definition(column, table)
        assert "CHECK" in result.upper()
        assert "age >= 0" in result

    def test_generate_column_definition_unique(self):
        """Test generating column with UNIQUE."""
        generator = SQLiteSqlGenerator()
        table = Table(name="users", columns=[], dialect="sqlite")
        column = SqlColumn("email", "TEXT")
        column.is_unique = True
        result = generator._generate_column_definition(column, table)
        assert "UNIQUE" in result.upper()

    def test_generate_column_definition_unique_legacy(self):
        """Test generating column with UNIQUE using unique attribute."""
        generator = SQLiteSqlGenerator()
        table = Table(name="users", columns=[], dialect="sqlite")
        column = SqlColumn("email", "TEXT")
        # Set unique attribute directly since is_unique is None
        column.unique = True
        column.is_unique = None  # Ensure is_unique is None to test legacy path
        result = generator._generate_column_definition(column, table)
        assert "UNIQUE" in result.upper()

    def test_generate_column_definition_composite_primary_key(self):
        """Test skipping PRIMARY KEY when composite PK exists."""
        generator = SQLiteSqlGenerator()
        constraint = SqlConstraint(
            name="pk_users", constraint_type="PRIMARY_KEY", column_names=["id", "name"]
        )
        table = Table(
            name="users",
            columns=[SqlColumn("id", "INTEGER"), SqlColumn("name", "TEXT")],
            constraints=[constraint],
            dialect="sqlite",
        )
        column = table.columns[0]
        column.is_primary_key = True
        result = generator._generate_column_definition(column, table)
        assert "PRIMARY KEY" not in result.upper()


@pytest.mark.unit
class TestSQLiteSqlGeneratorConstraintDefinition:
    """Tests for _generate_constraint_definition method."""

    def test_generate_constraint_definition_primary_key(self):
        """Test generating PRIMARY KEY constraint."""
        generator = SQLiteSqlGenerator()
        constraint = SqlConstraint(
            name="pk_users", constraint_type="PRIMARY_KEY", column_names=["id"]
        )
        table = Table(name="users", columns=[SqlColumn("id", "INTEGER")], dialect="sqlite")
        result = generator._generate_constraint_definition(constraint, table)
        assert result is not None
        assert "PRIMARY KEY" in result.upper()
        assert "id" in result.lower() or '"id"' in result

    def test_generate_constraint_definition_primary_key_skip_column_level(self):
        """Test skipping PRIMARY KEY if already at column level."""
        generator = SQLiteSqlGenerator()
        constraint = SqlConstraint(
            name="pk_users", constraint_type="PRIMARY_KEY", column_names=["id"]
        )
        column = SqlColumn("id", "INTEGER")
        column.is_primary_key = True
        table = Table(name="users", columns=[column], dialect="sqlite")
        result = generator._generate_constraint_definition(constraint, table)
        assert result is None

    def test_generate_constraint_definition_unique(self):
        """Test generating UNIQUE constraint."""
        generator = SQLiteSqlGenerator()
        constraint = SqlConstraint(
            name="uk_email", constraint_type="UNIQUE", column_names=["email"]
        )
        table = Table(name="users", columns=[SqlColumn("email", "TEXT")], dialect="sqlite")
        result = generator._generate_constraint_definition(constraint, table)
        assert result is not None
        assert "UNIQUE" in result.upper()
        assert "email" in result.lower() or '"email"' in result

    def test_generate_constraint_definition_unique_with_name(self):
        """Test generating UNIQUE constraint with name."""
        generator = SQLiteSqlGenerator()
        constraint = SqlConstraint(
            name="uk_email", constraint_type="UNIQUE", column_names=["email"]
        )
        table = Table(name="users", columns=[SqlColumn("email", "TEXT")], dialect="sqlite")
        result = generator._generate_constraint_definition(constraint, table)
        assert "CONSTRAINT" in result.upper()
        assert "uk_email" in result.lower() or '"uk_email"' in result

    def test_generate_constraint_definition_foreign_key(self):
        """Test generating FOREIGN KEY constraint."""
        generator = SQLiteSqlGenerator()
        constraint = SqlConstraint(
            name="fk_orders_user",
            constraint_type="FOREIGN_KEY",
            column_names=["user_id"],
        )
        constraint.reference_table = "users"
        constraint.reference_columns = ["id"]
        table = Table(name="orders", columns=[SqlColumn("user_id", "INTEGER")], dialect="sqlite")
        result = generator._generate_constraint_definition(constraint, table)
        assert result is not None
        assert "FOREIGN KEY" in result.upper()
        assert "REFERENCES" in result.upper()
        assert "users" in result.lower() or '"users"' in result

    def test_generate_constraint_definition_foreign_key_on_delete(self):
        """Test generating FOREIGN KEY with ON DELETE."""
        generator = SQLiteSqlGenerator()
        constraint = SqlConstraint(
            name="fk_orders_user",
            constraint_type="FOREIGN_KEY",
            column_names=["user_id"],
        )
        constraint.reference_table = "users"
        constraint.reference_columns = ["id"]
        constraint.on_delete = "CASCADE"
        table = Table(name="orders", columns=[SqlColumn("user_id", "INTEGER")], dialect="sqlite")
        result = generator._generate_constraint_definition(constraint, table)
        assert "ON DELETE CASCADE" in result.upper()

    def test_generate_constraint_definition_foreign_key_on_update(self):
        """Test generating FOREIGN KEY with ON UPDATE."""
        generator = SQLiteSqlGenerator()
        constraint = SqlConstraint(
            name="fk_orders_user",
            constraint_type="FOREIGN_KEY",
            column_names=["user_id"],
        )
        constraint.reference_table = "users"
        constraint.reference_columns = ["id"]
        constraint.on_update = "CASCADE"
        table = Table(name="orders", columns=[SqlColumn("user_id", "INTEGER")], dialect="sqlite")
        result = generator._generate_constraint_definition(constraint, table)
        assert "ON UPDATE CASCADE" in result.upper()

    def test_generate_constraint_definition_check(self):
        """Test generating CHECK constraint."""
        generator = SQLiteSqlGenerator()
        constraint = SqlConstraint(name="ck_age", constraint_type="CHECK", column_names=["age"])
        constraint.check_expression = "age >= 0"
        table = Table(name="users", columns=[SqlColumn("age", "INTEGER")], dialect="sqlite")
        result = generator._generate_constraint_definition(constraint, table)
        assert result is not None
        assert "CHECK" in result.upper()
        assert "age >= 0" in result

    def test_generate_constraint_definition_check_with_name(self):
        """Test generating CHECK constraint with name."""
        generator = SQLiteSqlGenerator()
        constraint = SqlConstraint(name="ck_age", constraint_type="CHECK", column_names=["age"])
        constraint.check_expression = "age >= 0"
        table = Table(name="users", columns=[SqlColumn("age", "INTEGER")], dialect="sqlite")
        result = generator._generate_constraint_definition(constraint, table)
        assert "CONSTRAINT" in result.upper()
        assert "ck_age" in result.lower() or '"ck_age"' in result

    def test_generate_constraint_definition_check_with_expression_attr(self):
        """Test generating CHECK constraint using expression attribute."""
        generator = SQLiteSqlGenerator()
        constraint = SqlConstraint(name="ck_age", constraint_type="CHECK", column_names=["age"])
        constraint.expression = "age >= 0"
        table = Table(name="users", columns=[SqlColumn("age", "INTEGER")], dialect="sqlite")
        result = generator._generate_constraint_definition(constraint, table)
        assert "CHECK" in result.upper()
        assert "age >= 0" in result


@pytest.mark.unit
class TestSQLiteSqlGeneratorTriggerCreate:
    """Tests for _generate_trigger_create_statement method."""

    def test_generate_trigger_create_statement_with_definition(self):
        """Test generating CREATE TRIGGER from definition."""
        generator = SQLiteSqlGenerator()
        trigger = Trigger(
            name="trg_insert",
            table_name="users",
            events=["INSERT"],
            definition="CREATE TRIGGER trg_insert BEFORE INSERT ON users FOR EACH ROW BEGIN SELECT 1; END",
            dialect="sqlite",
        )
        result = generator._generate_trigger_create_statement(trigger)
        assert "CREATE TRIGGER" in result.upper()

    def test_generate_trigger_create_statement_with_definition_if_not_exists(self):
        """Test adding IF NOT EXISTS to definition."""
        generator = SQLiteSqlGenerator()
        trigger = Trigger(
            name="trg_insert",
            table_name="users",
            events=["INSERT"],
            definition="CREATE TRIGGER trg_insert BEFORE INSERT ON users",
            dialect="sqlite",
        )
        trigger.if_not_exists = True
        result = generator._generate_trigger_create_statement(trigger)
        assert "IF NOT EXISTS" in result.upper()

    def test_generate_trigger_create_statement_simple(self):
        """Test generating simple CREATE TRIGGER statement."""
        generator = SQLiteSqlGenerator()
        trigger = Trigger(
            name="trg_insert", table_name="users", events=["INSERT"], dialect="sqlite"
        )
        trigger.definition = "SELECT 1;"
        result = generator._generate_trigger_create_statement(trigger)
        assert "CREATE TRIGGER" in result.upper()
        assert "trg_insert" in result.lower() or '"trg_insert"' in result
        assert "ON" in result.upper()
        assert "users" in result.lower() or '"users"' in result

    def test_generate_trigger_create_statement_temp(self):
        """Test generating CREATE TEMP TRIGGER statement."""
        generator = SQLiteSqlGenerator()
        trigger = Trigger(
            name="trg_insert", table_name="users", events=["INSERT"], dialect="sqlite"
        )
        trigger.is_temporary = True
        trigger.definition = "SELECT 1;"
        result = generator._generate_trigger_create_statement(trigger)
        assert "CREATE TEMP TRIGGER" in result.upper()

    def test_generate_trigger_create_statement_if_not_exists(self):
        """Test generating CREATE TRIGGER IF NOT EXISTS."""
        generator = SQLiteSqlGenerator()
        trigger = Trigger(
            name="trg_insert", table_name="users", events=["INSERT"], dialect="sqlite"
        )
        trigger.if_not_exists = True
        trigger.definition = "SELECT 1;"
        result = generator._generate_trigger_create_statement(trigger)
        assert "IF NOT EXISTS" in result.upper()

    def test_generate_trigger_create_statement_with_timing(self):
        """Test generating CREATE TRIGGER with timing."""
        generator = SQLiteSqlGenerator()
        trigger = Trigger(
            name="trg_insert",
            table_name="users",
            events=["INSERT"],
            timing="AFTER",
            dialect="sqlite",
        )
        trigger.definition = "SELECT 1;"
        result = generator._generate_trigger_create_statement(trigger)
        assert "AFTER" in result.upper()

    def test_generate_trigger_create_statement_with_events_list(self):
        """Test generating CREATE TRIGGER with events list."""
        generator = SQLiteSqlGenerator()
        trigger = Trigger(
            name="trg_insert", table_name="users", events=["INSERT", "UPDATE"], dialect="sqlite"
        )
        trigger.definition = "SELECT 1;"
        result = generator._generate_trigger_create_statement(trigger)
        assert "INSERT" in result.upper()
        assert "UPDATE" in result.upper()

    def test_generate_trigger_create_statement_for_each_row(self):
        """Test generating CREATE TRIGGER FOR EACH ROW."""
        generator = SQLiteSqlGenerator()
        trigger = Trigger(
            name="trg_insert", table_name="users", events=["INSERT"], dialect="sqlite"
        )
        trigger.for_each_row = True
        trigger.definition = "SELECT 1;"
        result = generator._generate_trigger_create_statement(trigger)
        assert "FOR EACH ROW" in result.upper()

    def test_generate_trigger_create_statement_with_when_clause(self):
        """Test generating CREATE TRIGGER with WHEN clause."""
        generator = SQLiteSqlGenerator()
        trigger = Trigger(
            name="trg_insert", table_name="users", events=["INSERT"], dialect="sqlite"
        )
        trigger.when_clause = "NEW.id > 0"
        trigger.definition = "SELECT 1;"
        result = generator._generate_trigger_create_statement(trigger)
        assert "WHEN" in result.upper()
        assert "NEW.id > 0" in result

    def test_generate_trigger_create_statement_with_begin_end(self):
        """Test generating CREATE TRIGGER with BEGIN/END in definition."""
        generator = SQLiteSqlGenerator()
        trigger = Trigger(
            name="trg_insert", table_name="users", events=["INSERT"], dialect="sqlite"
        )
        trigger.definition = "BEGIN SELECT 1; END"
        result = generator._generate_trigger_create_statement(trigger)
        assert "BEGIN" in result.upper()
        assert "END" in result.upper()

    def test_generate_trigger_create_statement_without_begin_end(self):
        """Test generating CREATE TRIGGER without BEGIN/END in definition."""
        generator = SQLiteSqlGenerator()
        trigger = Trigger(
            name="trg_insert", table_name="users", events=["INSERT"], dialect="sqlite"
        )
        trigger.definition = "SELECT 1;"
        result = generator._generate_trigger_create_statement(trigger)
        assert "BEGIN" in result.upper()
        assert "END" in result.upper()


@pytest.mark.unit
class TestSQLiteSqlGeneratorAlterStatement:
    """Tests for generate_alter_statement method."""

    def test_generate_alter_statement(self):
        """Test generating ALTER statement (SQLite has limited support)."""
        generator = SQLiteSqlGenerator()
        table = Table(name="users", columns=[SqlColumn("id", "INTEGER")], dialect="sqlite")
        result = generator.generate_alter_statement(table, "sqlite")
        # SQLite has very limited ALTER support, so this returns empty
        assert result == ""


@pytest.mark.unit
class TestSQLiteSqlGeneratorFormatIdentifier:
    """Tests for format_identifier method."""

    def test_format_identifier_simple(self):
        """Test formatting simple identifier."""
        generator = SQLiteSqlGenerator()
        result = generator.format_identifier("users")
        assert result == '"users"'

    def test_format_identifier_with_quotes(self):
        """Test formatting identifier with quotes."""
        generator = SQLiteSqlGenerator()
        result = generator.format_identifier('user"name')
        assert result == '"user""name"'

    def test_format_identifier_empty(self):
        """Test formatting empty identifier."""
        generator = SQLiteSqlGenerator()
        result = generator.format_identifier("")
        assert result == ""

    def test_format_identifier_special_chars(self):
        """Test formatting identifier with special characters."""
        generator = SQLiteSqlGenerator()
        result = generator.format_identifier("user-name")
        assert result == '"user-name"'


@pytest.mark.unit
class TestSQLiteCreateDispatch:
    """Test _get_create_dispatch registry for SQLite."""

    def test_get_create_dispatch_contains_expected_types(self):
        """Verify dispatch contains all 4 SQLite types."""
        from core.sql_model.index import Index
        from core.sql_model.table import Table
        from core.sql_model.trigger import Trigger
        from core.sql_model.view import View

        generator = SQLiteSqlGenerator()
        dispatch = generator._get_create_dispatch()
        assert View in dispatch
        assert Index in dispatch
        assert Table in dispatch
        assert Trigger in dispatch
        assert len(dispatch) == 4

    def test_generate_create_statement_dispatches_view(self):
        """generate_create_statement routes View to _generate_view_create_statement."""
        from unittest.mock import patch

        from core.sql_model.view import View

        gen = SQLiteSqlGenerator()
        view = View(name="test_view", dialect="sqlite")
        with patch.object(
            gen, "_generate_view_create_statement", return_value="SQLITE_VIEW_SQL"
        ) as mock:
            result = gen.generate_create_statement(view)
        mock.assert_called_once_with(view)
        assert result == "SQLITE_VIEW_SQL"

    def test_generate_create_fallback_calls_create_statement_method(self):
        """Verify SQLite fallback calls obj.create_statement() method."""
        generator = SQLiteSqlGenerator()
        obj = MagicMock()
        obj.create_statement.return_value = "CREATE CUSTOM obj"
        result = generator._generate_create_fallback(obj)
        assert result == "CREATE CUSTOM obj"
        obj.create_statement.assert_called_once()

    def test_generate_create_fallback_no_create_statement(self):
        """Verify SQLite fallback returns empty string when no create_statement method."""
        generator = SQLiteSqlGenerator()
        obj = object()
        result = generator._generate_create_fallback(obj)
        assert result == ""


@pytest.mark.unit
class TestSQLiteGeneratorFactory:
    """Tests for SQLite generator factory registration (migrated from tests/unit/sqlite/)."""

    def test_factory_creates_sqlite_generator(self):
        """Test that factory creates SQLite generator."""
        from core.sql_generator.generator_factory import SqlGeneratorFactory

        generator = SqlGeneratorFactory.create("sqlite")
        assert isinstance(generator, SQLiteSqlGenerator)

    def test_factory_creates_sqlite3_generator(self):
        """Test that factory creates generator for 'sqlite3' alias."""
        from core.sql_generator.generator_factory import SqlGeneratorFactory

        generator = SqlGeneratorFactory.create("sqlite3")
        assert isinstance(generator, SQLiteSqlGenerator)

    def test_factory_supports_sqlite(self):
        """Test that factory reports SQLite as supported."""
        from core.sql_generator.generator_factory import SqlGeneratorFactory

        SqlGeneratorFactory._DIALECT_MAP.clear()
        SqlGeneratorFactory._register_defaults()

        assert SqlGeneratorFactory.is_supported("sqlite")
        assert SqlGeneratorFactory.is_supported("sqlite3")
