"""Tests for PostgreSQLSqlGenerator class."""

from unittest.mock import MagicMock

import pytest

from core.sql_generator.options import OrganizationStrategy, ScriptOptions
from core.sql_model.base import ConstraintType, SqlColumn, SqlConstraint
from core.sql_model.extension import Extension
from core.sql_model.foreign_data_wrapper import ForeignDataWrapper
from core.sql_model.foreign_server import ForeignServer
from core.sql_model.index import Index
from core.sql_model.procedure import Procedure
from core.sql_model.sequence import Sequence
from core.sql_model.synonym import Synonym
from core.sql_model.table import Table
from core.sql_model.trigger import Trigger
from core.sql_model.user_defined_type import UserDefinedType
from core.sql_model.view import View
from db.plugins.postgresql.generator.ddl_generator import PostgreSQLSqlGenerator


@pytest.mark.unit
class TestPostgreSQLSqlGeneratorInit:
    """Tests for PostgreSQLSqlGenerator initialization."""

    def test_init(self):
        """Test initialization."""
        generator = PostgreSQLSqlGenerator()
        assert generator is not None


@pytest.mark.unit
class TestPostgreSQLSqlGeneratorFormatStatements:
    """Tests for _format_statements method."""

    def test_format_statements_empty(self):
        """Test formatting empty statements list."""
        generator = PostgreSQLSqlGenerator()
        result = generator._format_statements([], "postgresql")
        assert result == ""

    def test_format_statements_single(self):
        """Test formatting single statement."""
        generator = PostgreSQLSqlGenerator()
        statements = ["CREATE TABLE users (id INT)"]
        result = generator._format_statements(statements, "postgresql")
        assert result == "CREATE TABLE users (id INT)"

    def test_format_statements_multiple(self):
        """Test formatting multiple statements."""
        generator = PostgreSQLSqlGenerator()
        statements = ["CREATE TABLE users (id INT)", "CREATE TABLE orders (id INT)"]
        result = generator._format_statements(statements, "postgresql")
        assert "CREATE TABLE users" in result
        assert "CREATE TABLE orders" in result
        assert "\n\n" in result

    def test_format_statements_filters_empty(self):
        """Test filtering empty statements."""
        generator = PostgreSQLSqlGenerator()
        statements = ["CREATE TABLE users (id INT)", "", "   ", "CREATE TABLE orders (id INT)"]
        result = generator._format_statements(statements, "postgresql")
        assert "CREATE TABLE users" in result
        assert "CREATE TABLE orders" in result


@pytest.mark.unit
class TestPostgreSQLSqlGeneratorDropStatement:
    """Tests for _generate_drop_statement method."""

    def test_generate_drop_statement_table(self):
        """Test generating DROP TABLE IF EXISTS CASCADE statement."""
        generator = PostgreSQLSqlGenerator()
        table = Table(name="users", columns=[SqlColumn("id", "INTEGER")], dialect="postgresql")
        result = generator._generate_drop_statement(table, "postgresql")
        assert "DROP TABLE IF EXISTS" in result.upper()
        assert "CASCADE" in result.upper()
        assert "users" in result.lower() or '"users"' in result

    def test_generate_drop_statement_table_with_schema(self):
        """Test generating DROP TABLE with schema."""
        generator = PostgreSQLSqlGenerator()
        table = Table(
            name="users",
            schema="myschema",
            columns=[SqlColumn("id", "INTEGER")],
            dialect="postgresql",
        )
        result = generator._generate_drop_statement(table, "postgresql")
        assert "DROP TABLE IF EXISTS" in result.upper()
        assert "myschema" in result.lower() or '"myschema"' in result

    def test_generate_drop_statement_view(self):
        """Test generating DROP VIEW IF EXISTS statement."""
        generator = PostgreSQLSqlGenerator()
        view = View(name="active_users", query="SELECT 1", dialect="postgresql")
        result = generator._generate_drop_statement(view, "postgresql")
        assert "DROP VIEW IF EXISTS" in result.upper()
        assert "active_users" in result.lower() or '"active_users"' in result

    def test_generate_drop_statement_materialized_view(self):
        """Test generating DROP MATERIALIZED VIEW IF EXISTS statement."""
        generator = PostgreSQLSqlGenerator()
        view = View(name="mv_users", query="SELECT 1", materialized=True, dialect="postgresql")
        result = generator._generate_drop_statement(view, "postgresql")
        assert "DROP MATERIALIZED VIEW IF EXISTS" in result.upper()
        assert "MATERIALIZED_VIEW" not in result.upper()

    def test_generate_drop_statement_function_uses_cascade_for_trigger_dependencies(self):
        """Test PostgreSQL trigger function drops include CASCADE."""
        generator = PostgreSQLSqlGenerator()
        function = Procedure(
            name="trg_probe_note",
            body="RETURN NEW;",
            is_function=True,
            dialect="postgresql",
        )

        result = generator._generate_drop_statement(function, "postgresql")

        assert "DROP FUNCTION IF EXISTS" in result.upper()
        assert result.rstrip().upper().endswith("CASCADE")

    def test_generate_drop_statement_index(self):
        """Test generating DROP INDEX IF EXISTS statement."""
        generator = PostgreSQLSqlGenerator()
        index = Index(name="idx_email", table_name="users", columns=["email"], dialect="postgresql")
        result = generator._generate_drop_statement(index, "postgresql")
        assert "DROP INDEX IF EXISTS" in result.upper()
        assert "idx_email" in result.lower() or '"idx_email"' in result

    def test_generate_drop_statement_sequence(self):
        """Test generating DROP SEQUENCE IF EXISTS statement."""
        generator = PostgreSQLSqlGenerator()
        sequence = Sequence(name="seq_id", dialect="postgresql")
        result = generator._generate_drop_statement(sequence, "postgresql")
        assert "DROP SEQUENCE IF EXISTS" in result.upper()
        assert "seq_id" in result.lower() or '"seq_id"' in result

    def test_generate_drop_statement_procedure(self):
        """Test generating DROP PROCEDURE IF EXISTS statement."""
        generator = PostgreSQLSqlGenerator()
        procedure = Procedure(name="proc_test", body="BEGIN END", dialect="postgresql")
        result = generator._generate_drop_statement(procedure, "postgresql")
        assert "DROP PROCEDURE IF EXISTS" in result.upper()
        assert "proc_test" in result.lower() or '"proc_test"' in result

    def test_generate_drop_statement_function(self):
        """Test generating DROP FUNCTION IF EXISTS statement."""
        generator = PostgreSQLSqlGenerator()
        function = Procedure(
            name="func_test", body="RETURN 1", is_function=True, dialect="postgresql"
        )
        result = generator._generate_drop_statement(function, "postgresql")
        assert "DROP FUNCTION IF EXISTS" in result.upper()
        assert "func_test" in result.lower() or '"func_test"' in result

    def test_generate_drop_statement_trigger(self):
        """Test generating DROP TRIGGER IF EXISTS statement."""
        generator = PostgreSQLSqlGenerator()
        trigger = Trigger(
            name="trg_insert",
            schema="myschema",
            table_name="users",
            events=["INSERT"],
            dialect="postgresql",
        )
        result = generator._generate_drop_statement(trigger, "postgresql")
        assert "DROP TRIGGER IF EXISTS" in result.upper()
        assert "trg_insert" in result.lower() or '"trg_insert"' in result
        assert " ON " in result.upper()
        assert "users" in result.lower() or '"users"' in result

    def test_generate_drop_statement_extension(self):
        """Test generating DROP EXTENSION IF EXISTS statement."""
        generator = PostgreSQLSqlGenerator()
        extension = Extension(name="pg_trgm", dialect="postgresql")
        result = generator._generate_drop_statement(extension, "postgresql")
        assert "DROP EXTENSION IF EXISTS" in result.upper()
        assert "pg_trgm" in result.lower() or '"pg_trgm"' in result

    def test_generate_drop_statement_fallback(self):
        """Test generating DROP statement fallback."""
        generator = PostgreSQLSqlGenerator()
        obj = MagicMock()
        obj.schema = None
        obj.name = "test_obj"
        obj.format_identifier = lambda x: x
        obj.object_type = "UNKNOWN_TYPE"
        result = generator._generate_drop_statement(obj, "postgresql")
        assert "DROP UNKNOWN_TYPE IF EXISTS" in result.upper()


@pytest.mark.unit
class TestPostgreSQLSqlGeneratorCreateStatement:
    """Tests for generate_create_statement method."""

    def test_generate_create_statement_view(self):
        """Test generating CREATE VIEW statement."""
        generator = PostgreSQLSqlGenerator()
        view = View(name="active_users", query="SELECT id FROM users", dialect="postgresql")
        result = generator.generate_create_statement(view)
        assert "CREATE OR REPLACE VIEW" in result.upper()
        assert "active_users" in result.lower() or '"active_users"' in result

    def test_generate_create_statement_index(self):
        """Test generating CREATE INDEX statement."""
        generator = PostgreSQLSqlGenerator()
        index = Index(name="idx_email", table_name="users", columns=["email"], dialect="postgresql")
        result = generator.generate_create_statement(index)
        assert "CREATE INDEX" in result.upper()
        assert "idx_email" in result.lower() or '"idx_email"' in result

    def test_generate_create_statement_procedure(self):
        """Test generating CREATE PROCEDURE statement."""
        generator = PostgreSQLSqlGenerator()
        procedure = Procedure(name="proc_test", body="BEGIN SELECT 1 END", dialect="postgresql")
        result = generator.generate_create_statement(procedure)
        assert "CREATE OR REPLACE PROCEDURE" in result.upper()
        assert "proc_test" in result.lower() or '"proc_test"' in result

    def test_generate_create_statement_table(self):
        """Test generating CREATE TABLE statement."""
        generator = PostgreSQLSqlGenerator()
        table = Table(
            name="users",
            columns=[SqlColumn("id", "INTEGER"), SqlColumn("name", "VARCHAR(100)")],
            dialect="postgresql",
        )
        result = generator.generate_create_statement(table)
        assert "CREATE TABLE" in result.upper()
        assert "users" in result.lower() or '"users"' in result

    def test_generate_create_statement_synonym(self):
        """Test generating CREATE VIEW for synonym."""
        generator = PostgreSQLSqlGenerator()
        synonym = Synonym(name="syn_test", target_object="users", dialect="postgresql")
        result = generator.generate_create_statement(synonym)
        assert "CREATE VIEW" in result.upper()
        assert "syn_test" in result.lower() or '"syn_test"' in result

    def test_generate_create_statement_sequence(self):
        """Test generating CREATE SEQUENCE statement."""
        generator = PostgreSQLSqlGenerator()
        sequence = Sequence(name="seq_id", dialect="postgresql")
        result = generator.generate_create_statement(sequence)
        assert "CREATE SEQUENCE" in result.upper()
        assert "seq_id" in result.lower() or '"seq_id"' in result

    def test_generate_create_statement_user_defined_type(self):
        """Test generating CREATE TYPE statement."""
        generator = PostgreSQLSqlGenerator()
        udt = UserDefinedType(
            name="status_type", type_category="ENUM", enum_values=["active"], dialect="postgresql"
        )
        result = generator.generate_create_statement(udt)
        assert "CREATE TYPE" in result.upper()
        assert "status_type" in result.lower() or '"status_type"' in result

    def test_generate_create_statement_trigger(self):
        """Test generating CREATE TRIGGER statement."""
        generator = PostgreSQLSqlGenerator()
        trigger = Trigger(
            name="trg_insert", table_name="users", events=["INSERT"], dialect="postgresql"
        )
        result = generator.generate_create_statement(trigger)
        assert "CREATE TRIGGER" in result.upper()
        assert "trg_insert" in result.lower() or '"trg_insert"' in result

    def test_generate_create_statement_foreign_server(self):
        """Test generating CREATE SERVER statement."""
        generator = PostgreSQLSqlGenerator()
        foreign_server = ForeignServer(
            name="srv_test", fdw_name="postgres_fdw", dialect="postgresql"
        )
        result = generator.generate_create_statement(foreign_server)
        # Foreign server generation delegates to _generate_basic_create_statement
        assert result is not None

    def test_generate_create_statement_foreign_data_wrapper(self):
        """Test generating CREATE FOREIGN DATA WRAPPER statement."""
        generator = PostgreSQLSqlGenerator()
        fdw = ForeignDataWrapper(name="fdw_test", handler="handler_func", dialect="postgresql")
        result = generator.generate_create_statement(fdw)
        # FDW generation delegates to _generate_basic_create_statement
        assert result is not None

    def test_generate_create_statement_extension(self):
        """Test generating CREATE EXTENSION statement."""
        generator = PostgreSQLSqlGenerator()
        extension = Extension(name="pg_trgm", dialect="postgresql")
        result = generator.generate_create_statement(extension)
        # Extension generation delegates to _generate_basic_create_statement
        assert result is not None

    def test_generate_create_statement_fallback(self):
        """Test generating CREATE statement fallback."""
        generator = PostgreSQLSqlGenerator()
        obj = MagicMock()
        obj.create_statement = "CREATE TEST_OBJ"
        result = generator.generate_create_statement(obj)
        assert result == "CREATE TEST_OBJ"


@pytest.mark.unit
class TestPostgreSQLSqlGeneratorViewCreate:
    """Tests for _generate_view_create_statement method."""

    def test_generate_view_create_statement_simple(self):
        """Test generating simple CREATE OR REPLACE VIEW statement."""
        generator = PostgreSQLSqlGenerator()
        view = View(name="active_users", query="SELECT id FROM users", dialect="postgresql")
        result = generator._generate_view_create_statement(view)
        assert "CREATE OR REPLACE VIEW" in result.upper()
        assert "active_users" in result.lower() or '"active_users"' in result
        assert "SELECT id FROM users" in result

    def test_generate_view_create_statement_with_schema(self):
        """Test generating CREATE VIEW with schema."""
        generator = PostgreSQLSqlGenerator()
        view = View(name="active_users", schema="myschema", query="SELECT 1", dialect="postgresql")
        result = generator._generate_view_create_statement(view)
        assert "myschema" in result.lower() or '"myschema"' in result

    def test_generate_view_create_statement_with_columns(self):
        """Test generating CREATE VIEW with column list."""
        generator = PostgreSQLSqlGenerator()
        view = View(
            name="active_users",
            columns=["id", "name"],
            query="SELECT id, name FROM users",
            dialect="postgresql",
        )
        result = generator._generate_view_create_statement(view)
        assert "active_users" in result.lower() or '"active_users"' in result
        assert "id" in result.lower() or '"id"' in result

    def test_generate_view_create_statement_materialized(self):
        """Test generating CREATE MATERIALIZED VIEW statement."""
        generator = PostgreSQLSqlGenerator()
        view = View(
            name="mv_users", query="SELECT id FROM users", materialized=True, dialect="postgresql"
        )
        result = generator._generate_view_create_statement(view)
        assert "CREATE MATERIALIZED VIEW" in result.upper()
        assert "OR REPLACE" not in result.upper()

    def test_generate_view_create_statement_materialized_unlogged(self):
        """Test generating CREATE UNLOGGED MATERIALIZED VIEW statement."""
        generator = PostgreSQLSqlGenerator()
        view = View(
            name="mv_users", query="SELECT id FROM users", materialized=True, dialect="postgresql"
        )
        view.unlogged = True
        result = generator._generate_view_create_statement(view)
        assert "CREATE UNLOGGED MATERIALIZED VIEW" in result.upper()

    def test_generate_view_create_statement_materialized_with_data(self):
        """Test generating MATERIALIZED VIEW with WITH DATA."""
        generator = PostgreSQLSqlGenerator()
        view = View(
            name="mv_users", query="SELECT id FROM users", materialized=True, dialect="postgresql"
        )
        result = generator._generate_view_create_statement(view)
        assert "WITH DATA" in result.upper()

    def test_generate_view_create_statement_security_definer(self):
        """Test generating CREATE VIEW with security_definer."""
        generator = PostgreSQLSqlGenerator()
        view = View(name="active_users", query="SELECT 1", dialect="postgresql")
        view.security_definer = True
        result = generator._generate_view_create_statement(view)
        assert (
            "WITH (security_definer=true)" in result.lower()
            or "WITH (security_definer=true)" in result
        )

    def test_generate_view_create_statement_security_invoker(self):
        """Test generating CREATE VIEW with security_invoker."""
        generator = PostgreSQLSqlGenerator()
        view = View(name="active_users", query="SELECT 1", dialect="postgresql")
        view.security_invoker = True
        result = generator._generate_view_create_statement(view)
        assert (
            "WITH (security_invoker=true)" in result.lower()
            or "WITH (security_invoker=true)" in result
        )


@pytest.mark.unit
class TestPostgreSQLSqlGeneratorIndexCreate:
    """Tests for _generate_index_create_statement method."""

    def test_generate_index_create_statement_simple(self):
        """Test generating simple CREATE INDEX statement."""
        generator = PostgreSQLSqlGenerator()
        index = Index(name="idx_email", table_name="users", columns=["email"], dialect="postgresql")
        result = generator._generate_index_create_statement(index)
        assert "CREATE INDEX" in result.upper()
        assert "idx_email" in result.lower() or '"idx_email"' in result
        assert "ON" in result.upper()
        assert "users" in result.lower() or '"users"' in result

    def test_generate_index_create_statement_unique(self):
        """Test generating CREATE UNIQUE INDEX statement."""
        generator = PostgreSQLSqlGenerator()
        index = Index(
            name="idx_email",
            table_name="users",
            columns=["email"],
            unique=True,
            dialect="postgresql",
        )
        result = generator._generate_index_create_statement(index)
        assert "CREATE UNIQUE INDEX" in result.upper()

    def test_generate_index_create_statement_concurrently(self):
        """Test generating CREATE INDEX CONCURRENTLY statement."""
        generator = PostgreSQLSqlGenerator()
        index = Index(name="idx_email", table_name="users", columns=["email"], dialect="postgresql")
        index.concurrently = True
        result = generator._generate_index_create_statement(index)
        assert "CONCURRENTLY" in result.upper()
        assert "CREATE" in result.upper()
        assert "INDEX" in result.upper()

    def test_generate_index_create_statement_with_using(self):
        """Test generating CREATE INDEX with USING clause."""
        generator = PostgreSQLSqlGenerator()
        index = Index(
            name="idx_content",
            table_name="posts",
            columns=["content"],
            type="GIN",
            dialect="postgresql",
        )
        result = generator._generate_index_create_statement(index)
        assert "USING GIN" in result.upper()

    def test_generate_index_create_statement_with_expression(self):
        """Test generating CREATE INDEX with expression."""
        generator = PostgreSQLSqlGenerator()
        index = Index(
            name="idx_expr",
            table_name="users",
            columns=["UPPER(email)"],
            expression_flags=[True],
            dialect="postgresql",
        )
        result = generator._generate_index_create_statement(index)
        assert "UPPER(email)" in result

    def test_generate_index_create_statement_with_sort_direction(self):
        """Test generating CREATE INDEX with sort direction."""
        generator = PostgreSQLSqlGenerator()
        index = Index(
            name="idx_email",
            table_name="users",
            columns=["email"],
            sort_directions=["DESC"],
            dialect="postgresql",
        )
        result = generator._generate_index_create_statement(index)
        assert "DESC" in result.upper()

    def test_generate_index_create_statement_with_fillfactor(self):
        """Test generating CREATE INDEX with fillfactor."""
        generator = PostgreSQLSqlGenerator()
        index = Index(name="idx_email", table_name="users", columns=["email"], dialect="postgresql")
        index.fillfactor = 80
        result = generator._generate_index_create_statement(index)
        assert "WITH" in result.upper()
        assert "fillfactor = 80" in result.lower()

    def test_generate_index_create_statement_with_compression(self):
        """Test generating CREATE INDEX with compression."""
        generator = PostgreSQLSqlGenerator()
        index = Index(name="idx_email", table_name="users", columns=["email"], dialect="postgresql")
        index.compression = "pglz"
        result = generator._generate_index_create_statement(index)
        assert "WITH" in result.upper()
        assert "compression" in result.lower()

    def test_generate_index_create_statement_with_where(self):
        """Test generating CREATE INDEX with WHERE clause."""
        generator = PostgreSQLSqlGenerator()
        index = Index(name="idx_email", table_name="users", columns=["email"], dialect="postgresql")
        index.condition = "email IS NOT NULL"
        result = generator._generate_index_create_statement(index)
        assert "WHERE" in result.upper()
        assert "email IS NOT NULL" in result


@pytest.mark.unit
class TestPostgreSQLSqlGeneratorProcedureCreate:
    """Tests for _generate_procedure_create_statement method."""

    def test_generate_procedure_create_statement_with_definition(self):
        """Test generating CREATE PROCEDURE from definition."""
        generator = PostgreSQLSqlGenerator()
        procedure = Procedure(
            name="proc_test",
            body="BEGIN SELECT 1 END",
            definition="CREATE OR REPLACE PROCEDURE proc_test() AS $$ BEGIN SELECT 1 END $$",
            dialect="postgresql",
        )
        result = generator._generate_procedure_create_statement(procedure)
        # When definition is provided, it's returned as-is
        assert "CREATE OR REPLACE PROCEDURE" in result.upper()
        assert "proc_test" in result.lower()

    def test_generate_procedure_create_statement_simple(self):
        """Test generating simple CREATE OR REPLACE PROCEDURE statement."""
        generator = PostgreSQLSqlGenerator()
        procedure = Procedure(name="proc_test", body="BEGIN SELECT 1 END", dialect="postgresql")
        result = generator._generate_procedure_create_statement(procedure)
        assert "CREATE OR REPLACE PROCEDURE" in result.upper()
        assert "proc_test" in result.lower() or '"proc_test"' in result
        assert "AS $$" in result.upper()
        assert "SELECT 1" in result

    def test_generate_procedure_create_statement_with_schema(self):
        """Test generating CREATE PROCEDURE with schema."""
        generator = PostgreSQLSqlGenerator()
        procedure = Procedure(
            name="proc_test", schema="myschema", body="BEGIN SELECT 1 END", dialect="postgresql"
        )
        result = generator._generate_procedure_create_statement(procedure)
        assert "myschema" in result.lower() or '"myschema"' in result

    def test_generate_procedure_create_statement_with_parameters(self):
        """Test generating CREATE PROCEDURE with parameters."""
        generator = PostgreSQLSqlGenerator()
        from core.sql_model.procedure import Parameter

        param = Parameter(name="id", data_type="INTEGER")
        procedure = Procedure(
            name="proc_test", parameters=[param], body="BEGIN SELECT id END", dialect="postgresql"
        )
        result = generator._generate_procedure_create_statement(procedure)
        assert "id" in result.lower() or '"id"' in result
        assert "INTEGER" in result.upper()

    def test_generate_procedure_create_statement_with_output_parameter(self):
        """Test generating CREATE PROCEDURE with OUT parameter."""
        generator = PostgreSQLSqlGenerator()
        from core.sql_model.procedure import Parameter

        param = Parameter(name="result", data_type="INTEGER", direction="OUT")
        procedure = Procedure(
            name="proc_test",
            parameters=[param],
            body="BEGIN SET result = 1 END",
            dialect="postgresql",
        )
        result = generator._generate_procedure_create_statement(procedure)
        assert "OUT" in result.upper()

    def test_generate_procedure_create_statement_with_default_parameter(self):
        """Test generating CREATE PROCEDURE with DEFAULT parameter."""
        generator = PostgreSQLSqlGenerator()
        from core.sql_model.procedure import Parameter

        param = Parameter(name="id", data_type="INTEGER", default_value="1")
        procedure = Procedure(
            name="proc_test", parameters=[param], body="BEGIN SELECT id END", dialect="postgresql"
        )
        result = generator._generate_procedure_create_statement(procedure)
        assert "DEFAULT 1" in result.upper()

    def test_generate_procedure_create_statement_empty_parameters(self):
        """Test generating CREATE PROCEDURE with empty parameter list."""
        generator = PostgreSQLSqlGenerator()
        procedure = Procedure(
            name="proc_test", parameters=[], body="BEGIN SELECT 1 END", dialect="postgresql"
        )
        result = generator._generate_procedure_create_statement(procedure)
        assert "proc_test()" in result.lower() or '"proc_test"()' in result

    def test_generate_procedure_create_statement_function(self):
        """Test generating CREATE OR REPLACE FUNCTION statement."""
        generator = PostgreSQLSqlGenerator()
        function = Procedure(
            name="func_test",
            body="RETURN 1",
            is_function=True,
            return_type="INTEGER",
            dialect="postgresql",
        )
        result = generator._generate_procedure_create_statement(function)
        assert "CREATE OR REPLACE FUNCTION" in result.upper()
        assert "RETURNS INTEGER" in result.upper()

    def test_generate_procedure_create_statement_with_language(self):
        """Test generating CREATE FUNCTION with LANGUAGE."""
        generator = PostgreSQLSqlGenerator()
        function = Procedure(
            name="func_test",
            body="RETURN 1",
            is_function=True,
            return_type="INTEGER",
            language="plpgsql",
            dialect="postgresql",
        )
        result = generator._generate_procedure_create_statement(function)
        # LANGUAGE is only added if it's not SQL
        assert "LANGUAGE" in result.upper()
        assert "plpgsql" in result.lower()

    def test_generate_procedure_create_statement_with_volatility(self):
        """Test generating CREATE FUNCTION with volatility."""
        generator = PostgreSQLSqlGenerator()
        function = Procedure(
            name="func_test",
            body="RETURN 1",
            is_function=True,
            return_type="INTEGER",
            volatility="IMMUTABLE",
            dialect="postgresql",
        )
        result = generator._generate_procedure_create_statement(function)
        assert "IMMUTABLE" in result.upper()

    def test_generate_procedure_create_statement_security_definer(self):
        """Test generating CREATE PROCEDURE with SECURITY DEFINER."""
        generator = PostgreSQLSqlGenerator()
        procedure = Procedure(
            name="proc_test", body="BEGIN SELECT 1 END", security_definer=True, dialect="postgresql"
        )
        result = generator._generate_procedure_create_statement(procedure)
        assert "SECURITY DEFINER" in result.upper()

    def test_generate_procedure_create_statement_system_function(self):
        """Test skipping system functions."""
        generator = PostgreSQLSqlGenerator()
        function = Procedure(name="<", is_function=True, dialect="postgresql")
        result = generator._generate_procedure_create_statement(function)
        assert result == ""


@pytest.mark.unit
class TestPostgreSQLSqlGeneratorSynonymCreate:
    """Tests for _generate_synonym_create_statement method."""

    def test_generate_synonym_create_statement_simple(self):
        """Test generating CREATE VIEW for synonym."""
        generator = PostgreSQLSqlGenerator()
        synonym = Synonym(name="syn_test", target_object="users", dialect="postgresql")
        result = generator._generate_synonym_create_statement(synonym)
        assert "CREATE VIEW" in result.upper()
        assert "syn_test" in result.lower() or '"syn_test"' in result
        assert "SELECT * FROM" in result.upper()

    def test_generate_synonym_create_statement_with_schema(self):
        """Test generating CREATE VIEW for synonym with schema."""
        generator = PostgreSQLSqlGenerator()
        synonym = Synonym(
            name="syn_test", schema="myschema", target_object="users", dialect="postgresql"
        )
        result = generator._generate_synonym_create_statement(synonym)
        assert "myschema" in result.lower() or '"myschema"' in result


@pytest.mark.unit
class TestPostgreSQLSqlGeneratorSequenceCreate:
    """Tests for _generate_sequence_create_statement method."""

    def test_generate_sequence_create_statement_simple(self):
        """Test generating simple CREATE SEQUENCE statement."""
        generator = PostgreSQLSqlGenerator()
        sequence = Sequence(name="seq_id", dialect="postgresql")
        result = generator._generate_sequence_create_statement(sequence)
        assert "CREATE SEQUENCE" in result.upper()
        assert "seq_id" in result.lower() or '"seq_id"' in result

    def test_generate_sequence_create_statement_temporary(self):
        """Test generating CREATE TEMPORARY SEQUENCE statement."""
        generator = PostgreSQLSqlGenerator()
        sequence = Sequence(name="seq_id", temp=True, dialect="postgresql")
        result = generator._generate_sequence_create_statement(sequence)
        assert "CREATE TEMPORARY SEQUENCE" in result.upper()

    def test_generate_sequence_create_statement_with_start(self):
        """Test generating CREATE SEQUENCE with START WITH."""
        generator = PostgreSQLSqlGenerator()
        sequence = Sequence(name="seq_id", start_with=100, dialect="postgresql")
        result = generator._generate_sequence_create_statement(sequence)
        assert "START WITH 100" in result.upper()

    def test_generate_sequence_create_statement_with_increment(self):
        """Test generating CREATE SEQUENCE with INCREMENT BY."""
        generator = PostgreSQLSqlGenerator()
        sequence = Sequence(name="seq_id", increment_by=2, dialect="postgresql")
        result = generator._generate_sequence_create_statement(sequence)
        assert "INCREMENT BY 2" in result.upper()

    def test_generate_sequence_create_statement_with_min_max(self):
        """Test generating CREATE SEQUENCE with MINVALUE and MAXVALUE."""
        generator = PostgreSQLSqlGenerator()
        sequence = Sequence(name="seq_id", min_value=1, max_value=1000, dialect="postgresql")
        result = generator._generate_sequence_create_statement(sequence)
        assert "MINVALUE 1" in result.upper()
        assert "MAXVALUE 1000" in result.upper()

    def test_generate_sequence_create_statement_with_cycle(self):
        """Test generating CREATE SEQUENCE with CYCLE."""
        generator = PostgreSQLSqlGenerator()
        sequence = Sequence(name="seq_id", cycle=True, dialect="postgresql")
        result = generator._generate_sequence_create_statement(sequence)
        assert "CYCLE" in result.upper()

    def test_generate_sequence_create_statement_with_cache(self):
        """Test generating CREATE SEQUENCE with CACHE."""
        generator = PostgreSQLSqlGenerator()
        sequence = Sequence(name="seq_id", cache=10, dialect="postgresql")
        result = generator._generate_sequence_create_statement(sequence)
        assert "CACHE 10" in result.upper()


@pytest.mark.unit
class TestPostgreSQLSqlGeneratorExportRegressions:
    def test_materialized_view_query_semicolon_stays_inside_create_statement(self):
        generator = PostgreSQLSqlGenerator()
        view = View(
            name="mv_order_totals",
            query="SELECT order_id, sum(total) FROM orders GROUP BY order_id;",
            materialized=True,
            dialect="postgresql",
        )

        result = generator._generate_view_create_statement(view)

        assert ";\nWITH DATA" not in result
        assert result.rstrip().endswith("WITH DATA")

    def test_schema_script_orders_types_sequences_before_dependent_table(self):
        generator = PostgreSQLSqlGenerator()
        status_domain = UserDefinedType(
            name="status_domain",
            type_category="DOMAIN",
            base_type="text",
            dialect="postgresql",
        )
        order_seq = Sequence(name="order_seq", schema="public", dialect="postgresql")
        orders = Table(
            name="orders",
            schema="public",
            columns=[
                SqlColumn(
                    "id",
                    "INTEGER",
                    default_value="nextval('public.order_seq'::regclass)",
                    dialect="postgresql",
                ),
                SqlColumn("status", "status_domain", dialect="postgresql"),
            ],
            dialect="postgresql",
        )

        files = generator.generate_schema_script(
            {"tables": [orders], "sequences": [order_seq], "user_defined_types": [status_domain]},
            target_dialect="postgresql",
            options=ScriptOptions(organization=OrganizationStrategy.SINGLE_FILE),
        )
        sql = files["schema.sql"]

        assert sql.index("CREATE DOMAIN") < sql.index("CREATE TABLE")
        assert sql.index("CREATE SEQUENCE") < sql.index("CREATE TABLE")

    def test_schema_script_does_not_emit_sqlglot_warnings_for_enum_and_materialized_view(
        self, caplog
    ):
        generator = PostgreSQLSqlGenerator(default_dialect="postgresql")
        order_state = UserDefinedType(
            name="order_state",
            schema="dblift_test",
            type_category="ENUM",
            enum_values=["pending", "paid"],
            dialect="postgresql",
        )
        mview = View(
            name="mv_user_totals",
            schema="dblift_test",
            query="SELECT id FROM users",
            materialized=True,
            dialect="postgresql",
        )

        with caplog.at_level("WARNING", logger="sqlglot"):
            files = generator.generate_schema_script(
                {"user_defined_types": [order_state], "materialized_views": [mview]},
                target_dialect="postgresql",
                options=ScriptOptions(organization=OrganizationStrategy.SINGLE_FILE),
            )

        assert "CREATE TYPE" in files["schema.sql"]
        assert "CREATE MATERIALIZED VIEW" in files["schema.sql"]
        assert not [record for record in caplog.records if record.name.startswith("sqlglot")]

    def test_table_definition_does_not_bypass_postgresql_table_generator(self):
        generator = PostgreSQLSqlGenerator(default_dialect="postgresql")
        users = Table(
            "users",
            schema="dblift_test",
            columns=[SqlColumn("id", "INTEGER", dialect="postgresql")],
            dialect="postgresql",
        )
        orders = Table(
            "orders",
            schema="dblift_test",
            columns=[SqlColumn("id", "int4", dialect="postgresql")],
            constraints=[
                SqlConstraint(
                    ConstraintType.CHECK,
                    name="orders_amount_check",
                    check_expression="amount > 0::numeric",
                    dialect="postgresql",
                    is_deferrable=False,
                )
            ],
            dialect="postgresql",
        )
        orders.definition = 'CREATE TABLE "dblift_test"."orders" (\n    "id" int4 NOT NULL\n)'

        sql = generator.generate_ddl([users, orders], target_dialect="postgresql")

        assert '"id" INT' in sql
        assert '"id" int4' not in sql
        assert '    "id"' not in sql


@pytest.mark.unit
class TestPostgreSQLSqlGeneratorUserDefinedTypeCreate:
    """Tests for _generate_user_defined_type_create_statement method."""

    def test_generate_user_defined_type_create_statement_composite(self):
        """Test generating CREATE TYPE AS for composite type."""
        generator = PostgreSQLSqlGenerator()
        udt = UserDefinedType(
            name="address_type",
            type_category="COMPOSITE",
            attributes=[
                {"name": "street", "type": "VARCHAR(100)"},
                {"name": "city", "type": "VARCHAR(50)"},
            ],
            dialect="postgresql",
        )
        result = generator._generate_user_defined_type_create_statement(udt)
        assert "CREATE TYPE" in result.upper()
        assert "AS (" in result.upper()
        assert "street" in result.lower()
        assert "city" in result.lower()

    def test_generate_user_defined_type_create_statement_enum(self):
        """Test generating CREATE TYPE AS ENUM for enum type."""
        generator = PostgreSQLSqlGenerator()
        udt = UserDefinedType(
            name="status_enum",
            type_category="ENUM",
            enum_values=["active", "inactive"],
            dialect="postgresql",
        )
        result = generator._generate_user_defined_type_create_statement(udt)
        assert "CREATE TYPE" in result.upper()
        assert "AS ENUM" in result.upper()
        assert "active" in result.lower()
        assert "inactive" in result.lower()

    def test_generate_user_defined_type_create_statement_domain(self):
        """Test generating CREATE DOMAIN for domain type."""
        generator = PostgreSQLSqlGenerator()
        udt = UserDefinedType(
            name="status_domain",
            type_category="DOMAIN",
            base_type="VARCHAR(50)",
            dialect="postgresql",
        )
        result = generator._generate_user_defined_type_create_statement(udt)
        assert "CREATE DOMAIN" in result.upper()
        assert "AS VARCHAR(50)" in result.upper()

    def test_generate_user_defined_type_create_statement_domain_with_definition(self):
        """Test generating CREATE DOMAIN with definition."""
        generator = PostgreSQLSqlGenerator()
        udt = UserDefinedType(
            name="status_domain",
            type_category="DOMAIN",
            base_type="VARCHAR(50)",
            definition="CHECK (value IN ('active', 'inactive'))",
            dialect="postgresql",
        )
        result = generator._generate_user_defined_type_create_statement(udt)
        assert "CREATE DOMAIN" in result.upper()
        assert "CHECK" in result.upper()

    def test_generate_user_defined_type_create_statement_with_definition(self):
        """Test generating CREATE TYPE with definition."""
        generator = PostgreSQLSqlGenerator()
        udt = UserDefinedType(
            name="custom_type",
            type_category="DISTINCT",
            definition="VARCHAR(100)",
            dialect="postgresql",
        )
        result = generator._generate_user_defined_type_create_statement(udt)
        assert "CREATE TYPE" in result.upper()
        assert "AS VARCHAR(100)" in result.upper()

    def test_generate_user_defined_type_create_statement_fallback(self):
        """Test generating CREATE TYPE fallback."""
        generator = PostgreSQLSqlGenerator()
        udt = UserDefinedType(name="custom_type", type_category="UNKNOWN", dialect="postgresql")
        result = generator._generate_user_defined_type_create_statement(udt)
        assert "CREATE TYPE" in result.upper()
        assert "custom_type" in result.lower() or '"custom_type"' in result


@pytest.mark.unit
class TestPostgreSQLSqlGeneratorTriggerCreate:
    """Tests for _generate_trigger_create_statement method."""

    def test_generate_trigger_create_statement_with_definition(self):
        """Test generating CREATE TRIGGER from definition."""
        generator = PostgreSQLSqlGenerator()
        trigger = Trigger(
            name="trg_insert",
            table_name="users",
            events=["INSERT"],
            definition="CREATE TRIGGER trg_insert BEFORE INSERT ON users FOR EACH ROW BEGIN SELECT 1; END",
            dialect="postgresql",
        )
        result = generator._generate_trigger_create_statement(trigger)
        assert "CREATE TRIGGER" in result.upper()

    def test_generate_trigger_create_statement_simple(self):
        """Test generating simple CREATE TRIGGER statement."""
        generator = PostgreSQLSqlGenerator()
        trigger = Trigger(
            name="trg_insert", table_name="users", events=["INSERT"], dialect="postgresql"
        )
        trigger.definition = "SELECT 1;"
        result = generator._generate_trigger_create_statement(trigger)
        assert "CREATE TRIGGER" in result.upper()
        assert "trg_insert" in result.lower() or '"trg_insert"' in result
        assert "ON" in result.upper()
        assert "users" in result.lower() or '"users"' in result

    def test_generate_trigger_create_statement_with_timing(self):
        """Test generating CREATE TRIGGER with timing."""
        generator = PostgreSQLSqlGenerator()
        trigger = Trigger(
            name="trg_insert",
            table_name="users",
            events=["INSERT"],
            timing="AFTER",
            dialect="postgresql",
        )
        trigger.definition = "SELECT 1;"
        result = generator._generate_trigger_create_statement(trigger)
        assert "AFTER" in result.upper()

    def test_generate_trigger_create_statement_with_orientation(self):
        """Test generating CREATE TRIGGER with FOR EACH ROW."""
        generator = PostgreSQLSqlGenerator()
        trigger = Trigger(
            name="trg_insert", table_name="users", events=["INSERT"], dialect="postgresql"
        )
        trigger.orientation = "ROW"
        trigger.definition = "SELECT 1;"
        result = generator._generate_trigger_create_statement(trigger)
        assert "FOR EACH ROW" in result.upper()


@pytest.mark.unit
class TestPostgreSQLSqlGeneratorForeignObjects:
    """Tests for foreign object create statements."""

    def test_generate_foreign_server_create_statement(self):
        """Test generating CREATE SERVER statement."""
        generator = PostgreSQLSqlGenerator()
        foreign_server = ForeignServer(
            name="srv_test", fdw_name="postgres_fdw", dialect="postgresql"
        )
        result = generator._generate_foreign_server_create_statement(foreign_server)
        # Foreign server generation delegates to _generate_basic_create_statement
        assert result is not None

    def test_generate_foreign_data_wrapper_create_statement(self):
        """Test generating CREATE FOREIGN DATA WRAPPER statement."""
        generator = PostgreSQLSqlGenerator()
        fdw = ForeignDataWrapper(name="fdw_test", handler="handler_func", dialect="postgresql")
        result = generator._generate_foreign_data_wrapper_create_statement(fdw)
        # FDW generation delegates to _generate_basic_create_statement
        assert result is not None

    def test_generate_extension_create_statement(self):
        """Test generating CREATE EXTENSION statement."""
        generator = PostgreSQLSqlGenerator()
        extension = Extension(name="pg_trgm", dialect="postgresql")
        result = generator._generate_extension_create_statement(extension)
        # Extension generation delegates to _generate_basic_create_statement
        assert result is not None


@pytest.mark.unit
class TestPostgreSQLCreateDispatch:
    """Test _get_create_dispatch registry for PostgreSQL."""

    def test_get_create_dispatch_contains_expected_types(self):
        """Verify dispatch contains all 11 PostgreSQL types."""
        from core.sql_model.extension import Extension
        from core.sql_model.foreign_data_wrapper import ForeignDataWrapper
        from core.sql_model.foreign_server import ForeignServer
        from core.sql_model.index import Index
        from core.sql_model.procedure import Procedure
        from core.sql_model.sequence import Sequence
        from core.sql_model.synonym import Synonym
        from core.sql_model.table import Table
        from core.sql_model.trigger import Trigger
        from core.sql_model.user_defined_type import UserDefinedType
        from core.sql_model.view import View

        generator = PostgreSQLSqlGenerator()
        dispatch = generator._get_create_dispatch()
        assert View in dispatch
        assert Index in dispatch
        assert Procedure in dispatch
        assert Table in dispatch
        assert Synonym in dispatch
        assert Sequence in dispatch
        assert UserDefinedType in dispatch
        assert Trigger in dispatch
        assert ForeignServer in dispatch
        assert ForeignDataWrapper in dispatch
        assert Extension in dispatch
        assert len(dispatch) == 11

    def test_generate_create_statement_dispatches_view(self):
        """generate_create_statement routes View to _generate_view_create_statement."""
        from unittest.mock import patch

        from core.sql_model.view import View

        gen = PostgreSQLSqlGenerator()
        view = View(name="test_view", dialect="postgresql")
        with patch.object(
            gen, "_generate_view_create_statement", return_value="PG_VIEW_SQL"
        ) as mock:
            result = gen.generate_create_statement(view)
        mock.assert_called_once_with(view)
        assert result == "PG_VIEW_SQL"
