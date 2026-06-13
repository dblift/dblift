"""Tests for MySQLSqlGenerator class."""

from unittest.mock import MagicMock

import pytest

from core.sql_model.base import SqlColumn, SqlObjectType
from core.sql_model.event import Event
from core.sql_model.index import Index
from core.sql_model.procedure import Procedure
from core.sql_model.sequence import Sequence
from core.sql_model.synonym import Synonym
from core.sql_model.table import Table
from core.sql_model.trigger import Trigger
from core.sql_model.user_defined_type import UserDefinedType
from core.sql_model.view import View
from db.plugins.mysql.generator.ddl_generator import MySQLSqlGenerator


@pytest.mark.unit
class TestMySQLSqlGeneratorInit:
    """Tests for MySQLSqlGenerator initialization."""

    def test_init(self):
        """Test initialization."""
        generator = MySQLSqlGenerator()
        assert generator is not None


@pytest.mark.unit
class TestMySQLSqlGeneratorDialectSpecific:
    """Tests for dialect-specific methods."""

    def test_requires_dialect_specific_wrapping_procedure(self):
        """Test _requires_dialect_specific_wrapping for PROCEDURE."""
        generator = MySQLSqlGenerator()
        procedure = Procedure(name="proc_test", body="BEGIN END", dialect="mysql")
        result = generator._requires_dialect_specific_wrapping(procedure, "mysql")
        assert result is True

    def test_requires_dialect_specific_wrapping_function(self):
        """Test _requires_dialect_specific_wrapping for FUNCTION."""
        generator = MySQLSqlGenerator()
        function = Procedure(name="func_test", body="RETURN 1", is_function=True, dialect="mysql")
        result = generator._requires_dialect_specific_wrapping(function, "mysql")
        assert result is True

    def test_requires_dialect_specific_wrapping_trigger(self):
        """Test _requires_dialect_specific_wrapping for TRIGGER."""
        generator = MySQLSqlGenerator()
        trigger = Trigger(name="trg_insert", table_name="users", events=["INSERT"], dialect="mysql")
        result = generator._requires_dialect_specific_wrapping(trigger, "mysql")
        assert result is True

    def test_requires_dialect_specific_wrapping_event(self):
        """Test _requires_dialect_specific_wrapping for EVENT."""
        generator = MySQLSqlGenerator()
        event = Event(name="evt_daily", schedule="EVERY 1 DAY", dialect="mysql")
        result = generator._requires_dialect_specific_wrapping(event, "mysql")
        assert result is True

    def test_requires_dialect_specific_wrapping_table(self):
        """Test _requires_dialect_specific_wrapping for TABLE."""
        generator = MySQLSqlGenerator()
        table = Table(name="users", columns=[SqlColumn("id", "INTEGER")], dialect="mysql")
        result = generator._requires_dialect_specific_wrapping(table, "mysql")
        assert result is False

    def test_requires_dialect_specific_wrapping_wrong_dialect(self):
        """Test _requires_dialect_specific_wrapping with wrong dialect."""
        generator = MySQLSqlGenerator()
        procedure = Procedure(name="proc_test", body="BEGIN END", dialect="postgresql")
        result = generator._requires_dialect_specific_wrapping(procedure, "postgresql")
        assert result is False

    def test_wrap_dialect_specific_block(self):
        """Test _wrap_dialect_specific_block wraps SQL with DELIMITER."""
        generator = MySQLSqlGenerator()
        sql = "CREATE PROCEDURE proc_test() BEGIN SELECT 1; END;"
        result = generator._wrap_dialect_specific_block(sql, "mysql")
        assert "DELIMITER $$" in result
        assert "$$" in result
        assert "DELIMITER ;" in result
        assert "SELECT 1" in result

    def test_wrap_dialect_specific_block_no_semicolon(self):
        """Test _wrap_dialect_specific_block without trailing semicolon."""
        generator = MySQLSqlGenerator()
        sql = "CREATE PROCEDURE proc_test() BEGIN SELECT 1 END"
        result = generator._wrap_dialect_specific_block(sql, "mysql")
        assert "DELIMITER $$" in result
        assert "SELECT 1 END" in result

    def test_should_skip_formatting_view(self):
        """Test _should_skip_formatting for VIEW."""
        generator = MySQLSqlGenerator()
        view = View(name="active_users", query="SELECT 1", dialect="mysql")
        result = generator._should_skip_formatting(view, "CREATE VIEW...")
        assert result is True

    def test_should_skip_formatting_procedure(self):
        """Test _should_skip_formatting for PROCEDURE."""
        generator = MySQLSqlGenerator()
        procedure = Procedure(name="proc_test", body="BEGIN END", dialect="mysql")
        result = generator._should_skip_formatting(procedure, "CREATE PROCEDURE...")
        assert result is True

    def test_should_skip_formatting_table(self):
        """Test _should_skip_formatting for TABLE."""
        generator = MySQLSqlGenerator()
        table = Table(name="users", columns=[SqlColumn("id", "INTEGER")], dialect="mysql")
        result = generator._should_skip_formatting(table, "CREATE TABLE...")
        assert result is False

    def test_should_skip_formatting_empty_sql(self):
        """Test _should_skip_formatting with empty SQL."""
        generator = MySQLSqlGenerator()
        view = View(name="active_users", query="SELECT 1", dialect="mysql")
        result = generator._should_skip_formatting(view, "")
        assert result is False


@pytest.mark.unit
class TestMySQLSqlGeneratorFormatStatements:
    """Tests for _format_statements method."""

    def test_format_statements_empty(self):
        """Test formatting empty statements list."""
        generator = MySQLSqlGenerator()
        result = generator._format_statements([], "mysql")
        assert result == ""

    def test_format_statements_single(self):
        """Test formatting single statement."""
        generator = MySQLSqlGenerator()
        statements = ["CREATE TABLE users (id INT)"]
        result = generator._format_statements(statements, "mysql")
        assert result == "CREATE TABLE users (id INT)"

    def test_format_statements_multiple(self):
        """Test formatting multiple statements."""
        generator = MySQLSqlGenerator()
        statements = ["CREATE TABLE users (id INT)", "CREATE TABLE orders (id INT)"]
        result = generator._format_statements(statements, "mysql")
        assert "CREATE TABLE users" in result
        assert "CREATE TABLE orders" in result
        assert "\n\n" in result

    def test_format_statements_filters_empty(self):
        """Test filtering empty statements."""
        generator = MySQLSqlGenerator()
        statements = ["CREATE TABLE users (id INT)", "", "   ", "CREATE TABLE orders (id INT)"]
        result = generator._format_statements(statements, "mysql")
        assert "CREATE TABLE users" in result
        assert "CREATE TABLE orders" in result


@pytest.mark.unit
class TestMySQLSqlGeneratorDropStatement:
    """Tests for _generate_drop_statement method."""

    def test_generate_drop_statement_table(self):
        """Test generating DROP TABLE IF EXISTS statement."""
        generator = MySQLSqlGenerator()
        table = Table(name="users", columns=[SqlColumn("id", "INTEGER")], dialect="mysql")
        result = generator._generate_drop_statement(table, "mysql")
        assert "DROP TABLE IF EXISTS" in result.upper()
        assert "users" in result.lower() or "`users`" in result

    def test_generate_drop_statement_table_with_schema(self):
        """Test generating DROP TABLE with schema."""
        generator = MySQLSqlGenerator()
        table = Table(
            name="users", schema="myschema", columns=[SqlColumn("id", "INTEGER")], dialect="mysql"
        )
        result = generator._generate_drop_statement(table, "mysql")
        assert "DROP TABLE IF EXISTS" in result.upper()
        assert "myschema" in result.lower() or "`myschema`" in result

    def test_generate_drop_statement_view(self):
        """Test generating DROP VIEW IF EXISTS statement."""
        generator = MySQLSqlGenerator()
        view = View(name="active_users", query="SELECT 1", dialect="mysql")
        result = generator._generate_drop_statement(view, "mysql")
        assert "DROP VIEW IF EXISTS" in result.upper()
        assert "active_users" in result.lower() or "`active_users`" in result

    def test_generate_drop_statement_index(self):
        """Test generating MySQL DROP INDEX with ON table clause."""
        generator = MySQLSqlGenerator()
        index = Index(name="idx_email", table_name="users", columns=["email"], dialect="mysql")
        result = generator._generate_drop_statement(index, "mysql")
        assert "DROP INDEX" in result.upper()
        assert "IF EXISTS" not in result.upper()
        assert "idx_email" in result.lower() or "`idx_email`" in result
        assert " ON " in result.upper()
        assert "users" in result.lower() or "`users`" in result

    def test_generate_drop_statement_index_uses_on_table_without_if_exists(self):
        """Test MySQL DROP INDEX grammar for schema-qualified tables."""
        generator = MySQLSqlGenerator()
        index = Index(
            name="idx_email",
            table_schema="app",
            table_name="users",
            columns=["email"],
            dialect="mysql",
        )

        result = generator._generate_drop_statement(index, "mysql")

        assert result == "DROP INDEX `idx_email` ON `app`.`users`"
        assert "IF EXISTS" not in result.upper()

    def test_generate_drop_statement_sequence(self):
        """Test generating DROP SEQUENCE IF EXISTS statement."""
        generator = MySQLSqlGenerator()
        sequence = Sequence(name="seq_id", dialect="mysql")
        result = generator._generate_drop_statement(sequence, "mysql")
        assert "DROP SEQUENCE IF EXISTS" in result.upper()

    def test_generate_drop_statement_procedure(self):
        """Test generating DROP PROCEDURE IF EXISTS statement."""
        generator = MySQLSqlGenerator()
        procedure = Procedure(name="proc_test", body="BEGIN END", dialect="mysql")
        result = generator._generate_drop_statement(procedure, "mysql")
        assert "DROP PROCEDURE IF EXISTS" in result.upper()
        assert "proc_test" in result.lower() or "`proc_test`" in result

    def test_generate_drop_statement_function(self):
        """Test generating DROP FUNCTION IF EXISTS statement."""
        generator = MySQLSqlGenerator()
        function = Procedure(name="func_test", body="RETURN 1", is_function=True, dialect="mysql")
        result = generator._generate_drop_statement(function, "mysql")
        assert "DROP FUNCTION IF EXISTS" in result.upper()
        assert "func_test" in result.lower() or "`func_test`" in result

    def test_generate_drop_statement_trigger(self):
        """Test generating DROP TRIGGER IF EXISTS statement."""
        generator = MySQLSqlGenerator()
        trigger = Trigger(name="trg_insert", table_name="users", events=["INSERT"], dialect="mysql")
        result = generator._generate_drop_statement(trigger, "mysql")
        assert "DROP TRIGGER IF EXISTS" in result.upper()
        assert "trg_insert" in result.lower() or "`trg_insert`" in result

    def test_generate_drop_statement_fallback(self):
        """Test generating DROP statement fallback."""
        generator = MySQLSqlGenerator()
        obj = MagicMock()
        obj.schema = None
        obj.name = "test_obj"
        obj.format_identifier = lambda x: x
        obj.object_type = "UNKNOWN_TYPE"
        result = generator._generate_drop_statement(obj, "mysql")
        assert "DROP UNKNOWN_TYPE IF EXISTS" in result.upper()


@pytest.mark.unit
class TestMySQLSqlGeneratorCreateStatement:
    """Tests for generate_create_statement method."""

    def test_generate_create_statement_view(self):
        """Test generating CREATE VIEW statement."""
        generator = MySQLSqlGenerator()
        view = View(name="active_users", query="SELECT id FROM users", dialect="mysql")
        result = generator.generate_create_statement(view)
        assert "CREATE VIEW" in result.upper()
        assert "active_users" in result.lower() or "`active_users`" in result

    def test_generate_create_statement_index(self):
        """Test generating CREATE INDEX statement."""
        generator = MySQLSqlGenerator()
        index = Index(name="idx_email", table_name="users", columns=["email"], dialect="mysql")
        result = generator.generate_create_statement(index)
        assert "CREATE INDEX" in result.upper()
        assert "idx_email" in result.lower() or "`idx_email`" in result

    def test_generate_create_statement_procedure(self):
        """Test generating CREATE PROCEDURE statement."""
        generator = MySQLSqlGenerator()
        procedure = Procedure(name="proc_test", body="BEGIN SELECT 1 END", dialect="mysql")
        result = generator.generate_create_statement(procedure)
        assert "CREATE PROCEDURE" in result.upper()
        assert "proc_test" in result.lower() or "`proc_test`" in result

    def test_generate_create_statement_table(self):
        """Test generating CREATE TABLE statement."""
        generator = MySQLSqlGenerator()
        table = Table(
            name="users",
            columns=[SqlColumn("id", "INTEGER"), SqlColumn("name", "VARCHAR(100)")],
            dialect="mysql",
        )
        result = generator.generate_create_statement(table)
        assert "CREATE TABLE" in result.upper()
        assert "users" in result.lower() or "`users`" in result

    def test_generate_create_statement_synonym(self):
        """Test generating CREATE VIEW for synonym."""
        generator = MySQLSqlGenerator()
        synonym = Synonym(name="syn_test", target_object="users", dialect="mysql")
        result = generator.generate_create_statement(synonym)
        assert "CREATE VIEW" in result.upper()
        assert "syn_test" in result.lower() or "`syn_test`" in result

    def test_generate_create_statement_sequence(self):
        """Test generating CREATE TABLE for sequence."""
        generator = MySQLSqlGenerator()
        sequence = Sequence(name="seq_id", dialect="mysql")
        result = generator.generate_create_statement(sequence)
        assert "CREATE TABLE" in result.upper()
        assert "seq_id" in result.lower() or "`seq_id`" in result

    def test_generate_create_statement_user_defined_type(self):
        """Test generating CREATE TABLE for user-defined type."""
        generator = MySQLSqlGenerator()
        udt = UserDefinedType(
            name="status_type", type_category="DISTINCT", base_type="VARCHAR(50)", dialect="mysql"
        )
        result = generator.generate_create_statement(udt)
        # MySQL doesn't support UDTs, so should return a comment
        assert result is not None

    def test_generate_create_statement_trigger(self):
        """Test generating CREATE TRIGGER statement."""
        generator = MySQLSqlGenerator()
        trigger = Trigger(name="trg_insert", table_name="users", events=["INSERT"], dialect="mysql")
        result = generator.generate_create_statement(trigger)
        assert "CREATE TRIGGER" in result.upper()
        assert "trg_insert" in result.lower() or "`trg_insert`" in result

    def test_generate_create_statement_event(self):
        """Test generating CREATE EVENT statement."""
        generator = MySQLSqlGenerator()
        event = Event(name="evt_daily", schedule="EVERY 1 DAY", dialect="mysql")
        result = generator.generate_create_statement(event)
        # Event generation delegates to event._generate_basic_create_statement
        assert result is not None

    def test_generate_create_statement_fallback(self):
        """Test generating CREATE statement fallback."""
        generator = MySQLSqlGenerator()
        obj = MagicMock()
        result = generator.generate_create_statement(obj)
        assert result == ""


@pytest.mark.unit
class TestMySQLSqlGeneratorViewCreate:
    """Tests for _generate_view_create_statement method."""

    def test_generate_view_create_statement_simple(self):
        """Test generating simple CREATE VIEW statement."""
        generator = MySQLSqlGenerator()
        view = View(name="active_users", query="SELECT id FROM users", dialect="mysql")
        result = generator._generate_view_create_statement(view)
        assert "CREATE VIEW" in result.upper()
        assert "active_users" in result.lower() or "`active_users`" in result
        assert "SELECT id FROM users" in result

    def test_generate_view_create_statement_with_schema(self):
        """Test generating CREATE VIEW with schema."""
        generator = MySQLSqlGenerator()
        view = View(name="active_users", schema="myschema", query="SELECT 1", dialect="mysql")
        result = generator._generate_view_create_statement(view)
        assert "myschema" in result.lower() or "`myschema`" in result

    def test_generate_view_create_statement_with_columns(self):
        """Test generating CREATE VIEW with column list."""
        generator = MySQLSqlGenerator()
        view = View(
            name="active_users",
            columns=["id", "name"],
            query="SELECT id, name FROM users",
            dialect="mysql",
        )
        result = generator._generate_view_create_statement(view)
        assert "active_users" in result.lower() or "`active_users`" in result
        assert "id" in result.lower() or "`id`" in result

    def test_generate_view_create_statement_with_algorithm(self):
        """Test generating CREATE VIEW with ALGORITHM."""
        generator = MySQLSqlGenerator()
        view = View(name="active_users", query="SELECT 1", dialect="mysql")
        view.algorithm = "MERGE"
        result = generator._generate_view_create_statement(view)
        assert "ALGORITHM = MERGE" in result.upper()

    def test_generate_view_create_statement_with_definer(self):
        """Test generating CREATE VIEW with DEFINER."""
        generator = MySQLSqlGenerator()
        view = View(name="active_users", query="SELECT 1", dialect="mysql")
        view.definer = "user@host"
        result = generator._generate_view_create_statement(view)
        assert "DEFINER" in result.upper()
        assert "user" in result.lower()
        assert "host" in result.lower()

    def test_generate_view_create_statement_with_sql_security(self):
        """Test generating CREATE VIEW with SQL SECURITY."""
        generator = MySQLSqlGenerator()
        view = View(name="active_users", query="SELECT 1", dialect="mysql")
        view.sql_security = "DEFINER"
        result = generator._generate_view_create_statement(view)
        assert "SQL SECURITY DEFINER" in result.upper()


@pytest.mark.unit
class TestMySQLSqlGeneratorIndexCreate:
    """Tests for _generate_index_create_statement method."""

    def test_generate_index_create_statement_simple(self):
        """Test generating simple CREATE INDEX statement."""
        generator = MySQLSqlGenerator()
        index = Index(name="idx_email", table_name="users", columns=["email"], dialect="mysql")
        result = generator._generate_index_create_statement(index)
        assert "CREATE INDEX" in result.upper()
        assert "idx_email" in result.lower() or "`idx_email`" in result
        assert "ON" in result.upper()
        assert "users" in result.lower() or "`users`" in result

    def test_generate_index_create_statement_unique(self):
        """Test generating CREATE UNIQUE INDEX statement."""
        generator = MySQLSqlGenerator()
        index = Index(
            name="idx_email", table_name="users", columns=["email"], unique=True, dialect="mysql"
        )
        result = generator._generate_index_create_statement(index)
        assert "CREATE UNIQUE INDEX" in result.upper()

    def test_generate_index_create_statement_online(self):
        """Test generating CREATE INDEX with ONLINE."""
        generator = MySQLSqlGenerator()
        index = Index(name="idx_email", table_name="users", columns=["email"], dialect="mysql")
        index.online = True
        result = generator._generate_index_create_statement(index)
        assert "ONLINE" in result.upper()

    def test_generate_index_create_statement_offline(self):
        """Test generating CREATE INDEX with OFFLINE."""
        generator = MySQLSqlGenerator()
        index = Index(name="idx_email", table_name="users", columns=["email"], dialect="mysql")
        index.online = False
        result = generator._generate_index_create_statement(index)
        assert "OFFLINE" in result.upper()

    def test_generate_index_create_statement_fulltext(self):
        """Test generating CREATE FULLTEXT INDEX statement."""
        generator = MySQLSqlGenerator()
        index = Index(
            name="idx_content",
            table_name="posts",
            columns=["content"],
            type="FULLTEXT",
            dialect="mysql",
        )
        result = generator._generate_index_create_statement(index)
        assert "CREATE FULLTEXT INDEX" in result.upper()

    def test_generate_fulltext_index_omits_sort_direction(self):
        """Test MySQL FULLTEXT indexes do not render explicit sort direction."""
        generator = MySQLSqlGenerator()
        index = Index(
            name="ft_child_probe_note",
            table_schema="app",
            table_name="child_probe",
            columns=["note"],
            sort_directions=["ASC"],
            type="FULLTEXT",
            dialect="mysql",
        )

        result = generator.generate_create_statement(index)

        assert (
            result == "CREATE FULLTEXT INDEX `ft_child_probe_note` ON `app`.`child_probe` (`note`)"
        )
        assert "NOTE` ASC" not in result.upper()

    def test_generate_index_create_statement_spatial(self):
        """Test generating CREATE SPATIAL INDEX statement."""
        generator = MySQLSqlGenerator()
        index = Index(
            name="idx_location",
            table_name="places",
            columns=["location"],
            type="SPATIAL",
            dialect="mysql",
        )
        result = generator._generate_index_create_statement(index)
        assert "CREATE SPATIAL INDEX" in result.upper()

    def test_generate_index_create_statement_with_using(self):
        """Test generating CREATE INDEX with USING clause."""
        generator = MySQLSqlGenerator()
        index = Index(
            name="idx_email", table_name="users", columns=["email"], type="HASH", dialect="mysql"
        )
        result = generator._generate_index_create_statement(index)
        assert "USING HASH" in result.upper()

    def test_generate_index_create_statement_with_expression(self):
        """Test generating CREATE INDEX with expression."""
        generator = MySQLSqlGenerator()
        index = Index(
            name="idx_expr",
            table_name="users",
            columns=["UPPER(email)"],
            expression_flags=[True],
            dialect="mysql",
        )
        result = generator._generate_index_create_statement(index)
        assert "UPPER(email)" in result

    def test_generate_index_create_statement_with_sort_direction(self):
        """Test generating CREATE INDEX with sort direction."""
        generator = MySQLSqlGenerator()
        index = Index(
            name="idx_email",
            table_name="users",
            columns=["email"],
            sort_directions=["DESC"],
            dialect="mysql",
        )
        result = generator._generate_index_create_statement(index)
        assert "DESC" in result.upper()


@pytest.mark.unit
class TestMySQLSqlGeneratorProcedureCreate:
    """Tests for _generate_procedure_create_statement method."""

    def test_generate_procedure_create_statement_with_definition(self):
        """Test generating CREATE PROCEDURE from definition."""
        generator = MySQLSqlGenerator()
        procedure = Procedure(
            name="proc_test",
            body="BEGIN SELECT 1 END",
            definition="CREATE PROCEDURE proc_test() BEGIN SELECT 1 END",
            dialect="mysql",
        )
        result = generator._generate_procedure_create_statement(procedure)
        # When definition is provided, it's returned as-is
        assert "CREATE PROCEDURE" in result.upper()
        assert "proc_test" in result.lower()

    def test_generate_procedure_create_statement_simple(self):
        """Test generating simple CREATE PROCEDURE statement."""
        generator = MySQLSqlGenerator()
        procedure = Procedure(name="proc_test", body="BEGIN SELECT 1 END", dialect="mysql")
        result = generator._generate_procedure_create_statement(procedure)
        assert "CREATE PROCEDURE" in result.upper()
        assert "proc_test" in result.lower() or "`proc_test`" in result
        assert "BEGIN" in result.upper()
        assert "SELECT 1" in result

    def test_generate_procedure_create_statement_with_schema(self):
        """Test generating CREATE PROCEDURE with schema."""
        generator = MySQLSqlGenerator()
        procedure = Procedure(
            name="proc_test", schema="myschema", body="BEGIN SELECT 1 END", dialect="mysql"
        )
        result = generator._generate_procedure_create_statement(procedure)
        assert "myschema" in result.lower() or "`myschema`" in result

    def test_generate_procedure_create_statement_with_parameters(self):
        """Test generating CREATE PROCEDURE with parameters."""
        generator = MySQLSqlGenerator()
        from core.sql_model.procedure import Parameter

        param = Parameter(name="id", data_type="INT")
        procedure = Procedure(
            name="proc_test", parameters=[param], body="BEGIN SELECT id END", dialect="mysql"
        )
        result = generator._generate_procedure_create_statement(procedure)
        assert "id" in result.lower() or "`id`" in result
        assert "INT" in result.upper()

    def test_generate_procedure_create_statement_with_output_parameter(self):
        """Test generating CREATE PROCEDURE with OUT parameter."""
        generator = MySQLSqlGenerator()
        from core.sql_model.procedure import Parameter

        param = Parameter(name="result", data_type="INT", direction="OUT")
        procedure = Procedure(
            name="proc_test", parameters=[param], body="BEGIN SET result = 1 END", dialect="mysql"
        )
        result = generator._generate_procedure_create_statement(procedure)
        assert "OUT" in result.upper()

    def test_generate_procedure_create_statement_with_default_parameter(self):
        """Test generating CREATE PROCEDURE with DEFAULT parameter."""
        generator = MySQLSqlGenerator()
        from core.sql_model.procedure import Parameter

        param = Parameter(name="id", data_type="INT", default_value="1")
        procedure = Procedure(
            name="proc_test", parameters=[param], body="BEGIN SELECT id END", dialect="mysql"
        )
        result = generator._generate_procedure_create_statement(procedure)
        assert "= 1" in result

    def test_generate_procedure_create_statement_empty_parameters(self):
        """Test generating CREATE PROCEDURE with empty parameter list."""
        generator = MySQLSqlGenerator()
        procedure = Procedure(
            name="proc_test", parameters=[], body="BEGIN SELECT 1 END", dialect="mysql"
        )
        result = generator._generate_procedure_create_statement(procedure)
        assert "proc_test()" in result.lower() or "`proc_test`()" in result

    def test_generate_procedure_create_statement_function(self):
        """Test generating CREATE FUNCTION statement."""
        generator = MySQLSqlGenerator()
        function = Procedure(
            name="func_test", body="RETURN 1", is_function=True, return_type="INT", dialect="mysql"
        )
        result = generator._generate_procedure_create_statement(function)
        assert "CREATE FUNCTION" in result.upper()
        assert "RETURNS INT" in result.upper()

    def test_generate_procedure_create_statement_deterministic(self):
        """Test generating CREATE FUNCTION with DETERMINISTIC."""
        generator = MySQLSqlGenerator()
        function = Procedure(
            name="func_test",
            body="RETURN 1",
            is_function=True,
            return_type="INT",
            volatility="IMMUTABLE",
            dialect="mysql",
        )
        result = generator._generate_procedure_create_statement(function)
        assert "DETERMINISTIC" in result.upper()

    def test_generate_procedure_create_statement_not_deterministic(self):
        """Test generating CREATE FUNCTION with NOT DETERMINISTIC."""
        generator = MySQLSqlGenerator()
        function = Procedure(
            name="func_test",
            body="RETURN 1",
            is_function=True,
            return_type="INT",
            volatility="VOLATILE",
            dialect="mysql",
        )
        result = generator._generate_procedure_create_statement(function)
        assert "NOT DETERMINISTIC" in result.upper()

    def test_generate_procedure_create_statement_sql_security_definer(self):
        """Test generating CREATE PROCEDURE with SQL SECURITY DEFINER."""
        generator = MySQLSqlGenerator()
        procedure = Procedure(
            name="proc_test", body="BEGIN SELECT 1 END", security_definer=True, dialect="mysql"
        )
        result = generator._generate_procedure_create_statement(procedure)
        assert "SQL SECURITY DEFINER" in result.upper()

    def test_generate_procedure_create_statement_sql_security_invoker(self):
        """Test generating CREATE PROCEDURE with SQL SECURITY INVOKER."""
        generator = MySQLSqlGenerator()
        procedure = Procedure(
            name="proc_test", body="BEGIN SELECT 1 END", security_definer=False, dialect="mysql"
        )
        result = generator._generate_procedure_create_statement(procedure)
        assert "SQL SECURITY INVOKER" in result.upper()

    def test_generate_procedure_create_statement_data_access(self):
        """Test generating CREATE PROCEDURE with data access clause."""
        generator = MySQLSqlGenerator()
        procedure = Procedure(
            name="proc_test",
            body="BEGIN SELECT 1 END",
            data_access="READS SQL DATA",
            dialect="mysql",
        )
        result = generator._generate_procedure_create_statement(procedure)
        assert "READS SQL DATA" in result.upper()

    def test_generate_procedure_create_statement_comment(self):
        """Test generating CREATE PROCEDURE with COMMENT."""
        generator = MySQLSqlGenerator()
        procedure = Procedure(
            name="proc_test", body="BEGIN SELECT 1 END", comment="Test procedure", dialect="mysql"
        )
        result = generator._generate_procedure_create_statement(procedure)
        assert "COMMENT" in result.upper()
        assert "Test procedure" in result

    def test_generate_procedure_create_statement_system_function(self):
        """Test skipping system functions."""
        generator = MySQLSqlGenerator()
        function = Procedure(name="<", is_function=True, dialect="mysql")
        result = generator._generate_procedure_create_statement(function)
        assert result == ""


@pytest.mark.unit
class TestMySQLSqlGeneratorSynonymCreate:
    """Tests for _generate_synonym_create_statement method."""

    def test_generate_synonym_create_statement_simple(self):
        """Test generating CREATE VIEW for synonym."""
        generator = MySQLSqlGenerator()
        synonym = Synonym(name="syn_test", target_object="users", dialect="mysql")
        result = generator._generate_synonym_create_statement(synonym)
        assert "CREATE VIEW" in result.upper()
        assert "syn_test" in result.lower() or "`syn_test`" in result
        assert "SELECT * FROM" in result.upper()

    def test_generate_synonym_create_statement_with_schema(self):
        """Test generating CREATE VIEW for synonym with schema."""
        generator = MySQLSqlGenerator()
        synonym = Synonym(
            name="syn_test", schema="myschema", target_object="users", dialect="mysql"
        )
        result = generator._generate_synonym_create_statement(synonym)
        assert "myschema" in result.lower() or "`myschema`" in result


@pytest.mark.unit
class TestMySQLSqlGeneratorSequenceCreate:
    """Tests for _generate_sequence_create_statement method."""

    def test_generate_sequence_create_statement_simple(self):
        """Test generating CREATE TABLE for sequence."""
        generator = MySQLSqlGenerator()
        sequence = Sequence(name="seq_id", dialect="mysql")
        result = generator._generate_sequence_create_statement(sequence)
        assert "CREATE TABLE" in result.upper()
        assert "seq_id" in result.lower() or "`seq_id`" in result
        assert "AUTO_INCREMENT" in result.upper()

    def test_generate_sequence_create_statement_with_start(self):
        """Test generating CREATE TABLE for sequence with AUTO_INCREMENT start."""
        generator = MySQLSqlGenerator()
        sequence = Sequence(name="seq_id", start_with=100, dialect="mysql")
        result = generator._generate_sequence_create_statement(sequence)
        assert "AUTO_INCREMENT = 100" in result.upper()


@pytest.mark.unit
class TestMySQLSqlGeneratorUserDefinedTypeCreate:
    """Tests for _generate_user_defined_type_create_statement method."""

    def test_generate_user_defined_type_create_statement_composite(self):
        """Test generating CREATE TABLE for composite type."""
        generator = MySQLSqlGenerator()
        udt = UserDefinedType(
            name="address_type",
            type_category="COMPOSITE",
            attributes=[
                {"name": "street", "type": "VARCHAR(100)"},
                {"name": "city", "type": "VARCHAR(50)"},
            ],
            dialect="mysql",
        )
        result = generator._generate_user_defined_type_create_statement(udt)
        assert "CREATE TABLE" in result.upper()
        assert "address_type" in result.lower() or "`address_type`" in result
        assert "street" in result.lower()
        assert "city" in result.lower()

    def test_generate_user_defined_type_create_statement_enum(self):
        """Test generating CREATE TABLE for ENUM type."""
        generator = MySQLSqlGenerator()
        udt = UserDefinedType(
            name="status_enum",
            type_category="ENUM",
            enum_values=["active", "inactive"],
            dialect="mysql",
        )
        result = generator._generate_user_defined_type_create_statement(udt)
        assert "CREATE TABLE" in result.upper()
        assert "status_enum" in result.lower() or "`status_enum`" in result
        assert "CHECK" in result.upper()
        assert "active" in result.lower()
        assert "inactive" in result.lower()

    def test_generate_user_defined_type_create_statement_fallback(self):
        """Test generating comment fallback for unsupported UDT."""
        generator = MySQLSqlGenerator()
        udt = UserDefinedType(name="custom_type", type_category="UNKNOWN", dialect="mysql")
        result = generator._generate_user_defined_type_create_statement(udt)
        assert "MySQL does not support" in result
        assert "custom_type" in result.lower()


@pytest.mark.unit
class TestMySQLSqlGeneratorTriggerCreate:
    """Tests for _generate_trigger_create_statement method."""

    def test_generate_trigger_create_statement_with_definition(self):
        """Test generating CREATE TRIGGER from definition."""
        generator = MySQLSqlGenerator()
        trigger = Trigger(
            name="trg_insert",
            table_name="users",
            events=["INSERT"],
            definition="CREATE TRIGGER trg_insert BEFORE INSERT ON users FOR EACH ROW BEGIN SELECT 1; END",
            dialect="mysql",
        )
        result = generator._generate_trigger_create_statement(trigger)
        assert "CREATE TRIGGER" in result.upper()

    def test_generate_trigger_create_statement_simple(self):
        """Test generating simple CREATE TRIGGER statement."""
        generator = MySQLSqlGenerator()
        trigger = Trigger(name="trg_insert", table_name="users", events=["INSERT"], dialect="mysql")
        trigger.definition = "SELECT 1;"
        result = generator._generate_trigger_create_statement(trigger)
        assert "CREATE TRIGGER" in result.upper()
        assert "trg_insert" in result.lower() or "`trg_insert`" in result
        assert "ON" in result.upper()
        assert "users" in result.lower() or "`users`" in result

    def test_generate_trigger_create_statement_with_timing(self):
        """Test generating CREATE TRIGGER with timing."""
        generator = MySQLSqlGenerator()
        trigger = Trigger(
            name="trg_insert",
            table_name="users",
            events=["INSERT"],
            timing="AFTER",
            dialect="mysql",
        )
        trigger.definition = "SELECT 1;"
        result = generator._generate_trigger_create_statement(trigger)
        assert "AFTER" in result.upper()

    def test_generate_trigger_create_statement_with_orientation(self):
        """Test generating CREATE TRIGGER with FOR EACH ROW."""
        generator = MySQLSqlGenerator()
        trigger = Trigger(name="trg_insert", table_name="users", events=["INSERT"], dialect="mysql")
        trigger.orientation = "ROW"
        trigger.definition = "SELECT 1;"
        result = generator._generate_trigger_create_statement(trigger)
        assert "FOR EACH ROW" in result.upper()

    def test_generate_trigger_create_statement_with_follows(self):
        """Test generating CREATE TRIGGER with FOLLOWS clause."""
        generator = MySQLSqlGenerator()
        trigger = Trigger(name="trg_insert", table_name="users", events=["INSERT"], dialect="mysql")
        trigger.follows_trigger = "trg_before"
        trigger.definition = "SELECT 1;"
        result = generator._generate_trigger_create_statement(trigger)
        assert "FOLLOWS" in result.upper()
        assert "trg_before" in result.lower() or "`trg_before`" in result

    def test_generate_trigger_create_statement_with_precedes(self):
        """Test generating CREATE TRIGGER with PRECEDES clause."""
        generator = MySQLSqlGenerator()
        trigger = Trigger(name="trg_insert", table_name="users", events=["INSERT"], dialect="mysql")
        trigger.precedes_trigger = "trg_after"
        trigger.definition = "SELECT 1;"
        result = generator._generate_trigger_create_statement(trigger)
        assert "PRECEDES" in result.upper()
        assert "trg_after" in result.lower() or "`trg_after`" in result


@pytest.mark.unit
class TestMySQLCreateDispatch:
    """Test _get_create_dispatch registry for MySQL."""

    def test_get_create_dispatch_contains_expected_types(self):
        """Verify dispatch contains all 9 MySQL types (including Event)."""
        from core.sql_model.event import Event
        from core.sql_model.index import Index
        from core.sql_model.procedure import Procedure
        from core.sql_model.sequence import Sequence
        from core.sql_model.synonym import Synonym
        from core.sql_model.table import Table
        from core.sql_model.trigger import Trigger
        from core.sql_model.user_defined_type import UserDefinedType
        from core.sql_model.view import View

        generator = MySQLSqlGenerator()
        dispatch = generator._get_create_dispatch()
        assert View in dispatch
        assert Index in dispatch
        assert Procedure in dispatch
        assert Table in dispatch
        assert Synonym in dispatch
        assert Sequence in dispatch
        assert UserDefinedType in dispatch
        assert Trigger in dispatch
        assert Event in dispatch
        assert len(dispatch) == 9

    def test_generate_create_statement_dispatches_view(self):
        """generate_create_statement routes View to _generate_view_create_statement."""
        from unittest.mock import patch

        from core.sql_model.view import View

        gen = MySQLSqlGenerator()
        view = View(name="test_view", dialect="mysql")
        with patch.object(
            gen, "_generate_view_create_statement", return_value="MYSQL_VIEW_SQL"
        ) as mock:
            result = gen.generate_create_statement(view)
        mock.assert_called_once_with(view)
        assert result == "MYSQL_VIEW_SQL"

    def test_generate_create_fallback_returns_empty_string(self):
        """Verify MySQL fallback returns empty string."""
        generator = MySQLSqlGenerator()
        result = generator._generate_create_fallback(object())
        assert result == ""
