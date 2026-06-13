"""Tests for OracleSqlGenerator class."""

from unittest.mock import MagicMock

import pytest

from core.sql_model.base import SqlColumn
from core.sql_model.index import Index
from core.sql_model.package import Package
from core.sql_model.procedure import Procedure
from core.sql_model.sequence import Sequence
from core.sql_model.synonym import Synonym
from core.sql_model.table import Table
from core.sql_model.trigger import Trigger
from core.sql_model.user_defined_type import UserDefinedType
from core.sql_model.view import View
from db.plugins.oracle.generator.ddl_generator import OracleSqlGenerator


@pytest.mark.unit
class TestOracleSqlGeneratorInit:
    """Tests for OracleSqlGenerator initialization."""

    def test_init(self):
        """Test initialization."""
        generator = OracleSqlGenerator()
        assert generator is not None


@pytest.mark.unit
class TestOracleSqlGeneratorFormatStatements:
    """Tests for _format_statements method."""

    def test_format_statements_empty(self):
        """Test formatting empty statements list."""
        generator = OracleSqlGenerator()
        result = generator._format_statements([], "oracle")
        assert result == ""

    def test_format_statements_single(self):
        """Test formatting single statement."""
        generator = OracleSqlGenerator()
        statements = ["CREATE TABLE users (id INT)"]
        result = generator._format_statements(statements, "oracle")
        assert result == "CREATE TABLE users (id INT)"

    def test_format_statements_multiple(self):
        """Test formatting multiple statements."""
        generator = OracleSqlGenerator()
        statements = ["CREATE TABLE users (id INT)", "CREATE TABLE orders (id INT)"]
        result = generator._format_statements(statements, "oracle")
        assert "CREATE TABLE users" in result
        assert "CREATE TABLE orders" in result


@pytest.mark.unit
class TestOracleSqlGeneratorTerminators:
    """Regression tests for Oracle PL/SQL export terminators."""

    def test_preserved_procedure_definition_gets_slash_not_slash_semicolon(self):
        generator = OracleSqlGenerator()
        procedure = Procedure(
            name="p_export",
            definition="CREATE OR REPLACE PROCEDURE p_export AS\nBEGIN\n  NULL;\nEND;",
            dialect="oracle",
        )

        result = generator.generate_ddl([procedure], target_dialect="oracle", format_sql=False)

        assert result.endswith("END;\n/")
        assert "/;" not in result

    def test_existing_slash_terminator_is_not_followed_by_semicolon(self):
        generator = OracleSqlGenerator()
        trigger = Trigger(
            name="trg_export",
            table_name="users",
            definition=(
                "CREATE OR REPLACE TRIGGER trg_export\n"
                "BEFORE INSERT ON users\n"
                "BEGIN\n"
                "  NULL;\n"
                "END;\n"
                "/"
            ),
            dialect="oracle",
        )

        result = generator.generate_ddl([trigger], target_dialect="oracle", format_sql=False)

        assert result.endswith("/")
        assert "/;" not in result

    def test_regular_ddl_still_gets_semicolon(self):
        generator = OracleSqlGenerator()
        table = Table(name="users", columns=[SqlColumn("id", "NUMBER")], dialect="oracle")

        result = generator.generate_ddl([table], target_dialect="oracle", format_sql=False)

        assert result.rstrip().endswith(";")

    def test_preserved_domain_index_definition_is_used(self):
        generator = OracleSqlGenerator()
        index = Index(
            name="idx_docs_text",
            table_name="docs",
            columns=["content"],
            dialect="oracle",
            type="DOMAIN",
            definition=(
                "CREATE INDEX idx_docs_text ON docs(content) "
                "INDEXTYPE IS CTXSYS.CONTEXT PARAMETERS ('lexer my_lexer')"
            ),
        )

        result = generator.generate_ddl([index], target_dialect="oracle", format_sql=False)

        assert "INDEXTYPE IS CTXSYS.CONTEXT" in result
        assert result.rstrip().endswith(";")

    def test_format_statements_filters_empty(self):
        """Test filtering empty statements."""
        generator = OracleSqlGenerator()
        statements = ["CREATE TABLE users (id INT)", "", "   ", "CREATE TABLE orders (id INT)"]
        result = generator._format_statements(statements, "oracle")
        assert "CREATE TABLE users" in result
        assert "CREATE TABLE orders" in result


@pytest.mark.unit
class TestOracleSqlGeneratorDropStatement:
    """Tests for _generate_drop_statement method."""

    def test_generate_drop_statement_table(self):
        """Test generating DROP TABLE statement with CASCADE CONSTRAINTS."""
        generator = OracleSqlGenerator()
        table = Table(name="users", columns=[SqlColumn("id", "INTEGER")], dialect="oracle")
        result = generator._generate_drop_statement(table, "oracle")
        assert "DROP TABLE" in result.upper()
        assert "CASCADE CONSTRAINTS" in result.upper()
        assert "users" in result.lower() or '"users"' in result

    def test_generate_drop_statement_table_with_schema(self):
        """Test generating DROP TABLE with schema."""
        generator = OracleSqlGenerator()
        table = Table(
            name="users", schema="myschema", columns=[SqlColumn("id", "INTEGER")], dialect="oracle"
        )
        result = generator._generate_drop_statement(table, "oracle")
        assert "DROP TABLE" in result.upper()
        assert "myschema" in result.lower() or '"myschema"' in result

    def test_generate_drop_statement_view(self):
        """Test generating DROP VIEW statement."""
        generator = OracleSqlGenerator()
        view = View(name="active_users", query="SELECT 1", dialect="oracle")
        result = generator._generate_drop_statement(view, "oracle")
        assert "DROP VIEW" in result.upper()
        assert "active_users" in result.lower() or '"active_users"' in result

    def test_generate_drop_statement_materialized_view(self):
        """Test generating DROP MATERIALIZED VIEW statement."""
        generator = OracleSqlGenerator()
        view = View(name="mv_users", query="SELECT 1", materialized=True, dialect="oracle")
        result = generator._generate_drop_statement(view, "oracle")
        assert "DROP MATERIALIZED VIEW" in result.upper()
        assert "MATERIALIZED_VIEW" not in result.upper()

    def test_generate_drop_statement_index(self):
        """Test generating DROP INDEX statement."""
        generator = OracleSqlGenerator()
        index = Index(name="idx_email", table_name="users", columns=["email"], dialect="oracle")
        result = generator._generate_drop_statement(index, "oracle")
        assert "DROP INDEX" in result.upper()
        assert "idx_email" in result.lower() or '"idx_email"' in result

    def test_generate_drop_statement_sequence(self):
        """Test generating DROP SEQUENCE statement."""
        generator = OracleSqlGenerator()
        sequence = Sequence(name="seq_id", dialect="oracle")
        result = generator._generate_drop_statement(sequence, "oracle")
        assert "DROP SEQUENCE" in result.upper()
        assert "seq_id" in result.lower() or '"seq_id"' in result

    def test_generate_drop_statement_procedure(self):
        """Test generating DROP PROCEDURE statement."""
        generator = OracleSqlGenerator()
        procedure = Procedure(name="proc_test", body="BEGIN END", dialect="oracle")
        result = generator._generate_drop_statement(procedure, "oracle")
        assert "DROP PROCEDURE" in result.upper()
        assert "proc_test" in result.lower() or '"proc_test"' in result

    def test_generate_drop_statement_function(self):
        """Test generating DROP FUNCTION statement."""
        generator = OracleSqlGenerator()
        function = Procedure(name="func_test", body="RETURN 1", is_function=True, dialect="oracle")
        result = generator._generate_drop_statement(function, "oracle")
        assert "DROP FUNCTION" in result.upper()
        assert "func_test" in result.lower() or '"func_test"' in result

    def test_generate_drop_statement_trigger(self):
        """Test generating DROP TRIGGER statement."""
        generator = OracleSqlGenerator()
        trigger = Trigger(
            name="trg_insert", table_name="users", events=["INSERT"], dialect="oracle"
        )
        result = generator._generate_drop_statement(trigger, "oracle")
        assert "DROP TRIGGER" in result.upper()
        assert "trg_insert" in result.lower() or '"trg_insert"' in result

    def test_generate_drop_statement_fallback(self):
        """Test generating DROP statement fallback."""
        generator = OracleSqlGenerator()
        obj = MagicMock()
        obj.schema = None
        obj.name = "test_obj"
        obj.format_identifier = lambda x: x
        obj.object_type = "UNKNOWN_TYPE"
        result = generator._generate_drop_statement(obj, "oracle")
        assert "DROP UNKNOWN_TYPE" in result.upper()


@pytest.mark.unit
class TestOracleSqlGeneratorCreateStatement:
    """Tests for generate_create_statement method."""

    def test_generate_create_statement_view(self):
        """Test generating CREATE VIEW statement."""
        generator = OracleSqlGenerator()
        view = View(name="active_users", query="SELECT id FROM users", dialect="oracle")
        result = generator.generate_create_statement(view)
        assert "CREATE OR REPLACE VIEW" in result.upper()
        assert "active_users" in result.lower() or '"active_users"' in result

    def test_generate_create_statement_index(self):
        """Test generating CREATE INDEX statement."""
        generator = OracleSqlGenerator()
        index = Index(name="idx_email", table_name="users", columns=["email"], dialect="oracle")
        result = generator.generate_create_statement(index)
        assert "CREATE INDEX" in result.upper()
        assert "idx_email" in result.lower() or '"idx_email"' in result

    def test_generate_create_statement_procedure(self):
        """Test generating CREATE PROCEDURE statement."""
        generator = OracleSqlGenerator()
        procedure = Procedure(name="proc_test", body="BEGIN SELECT 1 END", dialect="oracle")
        result = generator.generate_create_statement(procedure)
        assert "CREATE OR REPLACE PROCEDURE" in result.upper()
        assert "proc_test" in result.lower() or '"proc_test"' in result

    def test_generate_create_statement_table(self):
        """Test generating CREATE TABLE statement."""
        generator = OracleSqlGenerator()
        table = Table(
            name="users",
            columns=[SqlColumn("id", "INTEGER"), SqlColumn("name", "VARCHAR2(100)")],
            dialect="oracle",
        )
        result = generator.generate_create_statement(table)
        assert "CREATE TABLE" in result.upper()
        assert "users" in result.lower() or '"users"' in result

    def test_generate_create_statement_table_does_not_emit_invalid_initial_next_clause(self):
        """Test Oracle table storage params render inside a STORAGE clause."""
        generator = OracleSqlGenerator()
        table = Table(name="users", columns=[SqlColumn("id", "NUMBER")], dialect="oracle")
        table.tablespace = "USERS"
        table.pctfree = 10
        table.pctused = 40
        table.initial = 65536
        table.next = 1048576

        result = generator.generate_ddl([table], target_dialect="oracle", format_sql=False)

        assert "TABLESPACE" in result.upper()
        assert "PCTFREE 10" in result.upper()
        assert "PCTUSED 40" in result.upper()
        assert "STORAGE (INITIAL 65536 NEXT 1048576)" in result.upper()
        assert ", PCTUSED" not in result.upper()
        assert ", INITIAL" not in result.upper()
        assert ", NEXT" not in result.upper()

    def test_generate_create_statement_synonym(self):
        """Test generating CREATE SYNONYM statement."""
        generator = OracleSqlGenerator()
        synonym = Synonym(name="syn_test", target_object="users", dialect="oracle")
        result = generator.generate_create_statement(synonym)
        assert "CREATE OR REPLACE SYNONYM" in result.upper()
        assert "syn_test" in result.lower() or '"syn_test"' in result

    def test_generate_create_statement_sequence(self):
        """Test generating CREATE SEQUENCE statement."""
        generator = OracleSqlGenerator()
        sequence = Sequence(name="seq_id", dialect="oracle")
        result = generator.generate_create_statement(sequence)
        assert "CREATE SEQUENCE" in result.upper()
        assert "seq_id" in result.lower() or '"seq_id"' in result

    def test_generate_create_statement_user_defined_type(self):
        """Test generating CREATE TYPE statement."""
        generator = OracleSqlGenerator()
        udt = UserDefinedType(
            name="status_type", type_category="DISTINCT", base_type="VARCHAR2(50)", dialect="oracle"
        )
        result = generator.generate_create_statement(udt)
        assert "CREATE TYPE" in result.upper()
        assert "status_type" in result.lower() or '"status_type"' in result

    def test_generate_create_statement_trigger(self):
        """Test generating CREATE TRIGGER statement."""
        generator = OracleSqlGenerator()
        trigger = Trigger(
            name="trg_insert", table_name="users", events=["INSERT"], dialect="oracle"
        )
        result = generator.generate_create_statement(trigger)
        assert "CREATE TRIGGER" in result.upper()
        assert "trg_insert" in result.lower() or '"trg_insert"' in result

    def test_generate_create_statement_package(self):
        """Test generating CREATE PACKAGE statement."""
        generator = OracleSqlGenerator()
        package = Package(name="pkg_test", spec="PROCEDURE proc1", dialect="oracle")
        result = generator.generate_create_statement(package)
        # Package generation delegates to package._generate_basic_create_statement
        assert result is not None

    def test_generate_create_statement_fallback(self):
        """Test generating CREATE statement fallback."""
        generator = OracleSqlGenerator()
        obj = MagicMock()
        obj.create_statement = "CREATE TEST_OBJ"
        result = generator.generate_create_statement(obj)
        assert result == "CREATE TEST_OBJ"


@pytest.mark.unit
class TestOracleSqlGeneratorViewCreate:
    """Tests for _generate_view_create_statement method."""

    def test_generate_view_create_statement_simple(self):
        """Test generating simple CREATE OR REPLACE VIEW statement."""
        generator = OracleSqlGenerator()
        view = View(name="active_users", query="SELECT id FROM users", dialect="oracle")
        result = generator._generate_view_create_statement(view)
        assert "CREATE OR REPLACE VIEW" in result.upper()
        assert "active_users" in result.lower() or '"active_users"' in result
        assert "SELECT id FROM users" in result

    def test_generate_view_create_statement_with_schema(self):
        """Test generating CREATE VIEW with schema."""
        generator = OracleSqlGenerator()
        view = View(name="active_users", schema="myschema", query="SELECT 1", dialect="oracle")
        result = generator._generate_view_create_statement(view)
        assert "myschema" in result.lower() or '"myschema"' in result

    def test_generate_view_create_statement_with_columns(self):
        """Test generating CREATE VIEW with column list."""
        generator = OracleSqlGenerator()
        view = View(
            name="active_users",
            columns=["id", "name"],
            query="SELECT id, name FROM users",
            dialect="oracle",
        )
        result = generator._generate_view_create_statement(view)
        assert "active_users" in result.lower() or '"active_users"' in result
        assert "id" in result.lower() or '"id"' in result

    def test_generate_view_create_statement_materialized(self):
        """Test generating CREATE MATERIALIZED VIEW statement."""
        generator = OracleSqlGenerator()
        view = View(
            name="mv_users", query="SELECT id FROM users", materialized=True, dialect="oracle"
        )
        result = generator._generate_view_create_statement(view)
        assert "CREATE MATERIALIZED VIEW" in result.upper()
        assert "OR REPLACE" not in result.upper()

    def test_generate_view_create_statement_materialized_options_before_as(self):
        """Oracle materialized view options must precede AS."""
        generator = OracleSqlGenerator()
        view = View(
            name="mv_users", query="SELECT id FROM users", materialized=True, dialect="oracle"
        )
        result = generator._generate_view_create_statement(view).upper()

        assert result.index("BUILD IMMEDIATE") < result.index(" AS")
        assert result.index("REFRESH COMPLETE ON DEMAND") < result.index(" AS")

    def test_generate_view_create_statement_materialized_build_immediate(self):
        """Test generating MATERIALIZED VIEW with BUILD IMMEDIATE."""
        generator = OracleSqlGenerator()
        view = View(
            name="mv_users", query="SELECT id FROM users", materialized=True, dialect="oracle"
        )
        view.is_populated = True
        result = generator._generate_view_create_statement(view)
        assert "BUILD IMMEDIATE" in result.upper()

    def test_generate_view_create_statement_materialized_build_deferred(self):
        """Test generating MATERIALIZED VIEW with BUILD DEFERRED."""
        generator = OracleSqlGenerator()
        view = View(
            name="mv_users", query="SELECT id FROM users", materialized=True, dialect="oracle"
        )
        view.is_populated = False
        result = generator._generate_view_create_statement(view)
        assert "BUILD DEFERRED" in result.upper()

    def test_generate_view_create_statement_materialized_refresh(self):
        """Test generating MATERIALIZED VIEW with REFRESH clause."""
        generator = OracleSqlGenerator()
        view = View(
            name="mv_users", query="SELECT id FROM users", materialized=True, dialect="oracle"
        )
        view.refresh_method = "FAST"
        view.refresh_mode = "COMMIT"
        result = generator._generate_view_create_statement(view)
        assert "REFRESH FAST ON COMMIT" in result.upper()

    def test_generate_view_create_statement_force(self):
        """Test generating CREATE VIEW with FORCE."""
        generator = OracleSqlGenerator()
        view = View(name="active_users", query="SELECT id FROM users", dialect="oracle")
        view.force = True
        result = generator._generate_view_create_statement(view)
        assert "FORCE" in result.upper()

    def test_generate_view_create_statement_noforce(self):
        """Test generating CREATE VIEW with NOFORCE."""
        generator = OracleSqlGenerator()
        view = View(name="active_users", query="SELECT id FROM users", dialect="oracle")
        view.force = False
        result = generator._generate_view_create_statement(view)
        assert "NOFORCE" in result.upper()


@pytest.mark.unit
class TestOracleSqlGeneratorIndexCreate:
    """Tests for _generate_index_create_statement method."""

    def test_generate_index_create_statement_simple(self):
        """Test generating simple CREATE INDEX statement."""
        generator = OracleSqlGenerator()
        index = Index(name="idx_email", table_name="users", columns=["email"], dialect="oracle")
        result = generator._generate_index_create_statement(index)
        assert "CREATE INDEX" in result.upper()
        assert "idx_email" in result.lower() or '"idx_email"' in result
        assert "ON" in result.upper()
        assert "users" in result.lower() or '"users"' in result

    def test_generate_index_create_statement_unique(self):
        """Test generating CREATE UNIQUE INDEX statement."""
        generator = OracleSqlGenerator()
        index = Index(
            name="idx_email", table_name="users", columns=["email"], unique=True, dialect="oracle"
        )
        result = generator._generate_index_create_statement(index)
        assert "CREATE UNIQUE INDEX" in result.upper()

    def test_generate_index_create_statement_bitmap(self):
        """Test generating CREATE BITMAP INDEX statement."""
        generator = OracleSqlGenerator()
        index = Index(
            name="idx_status",
            table_name="users",
            columns=["status"],
            type="BITMAP",
            dialect="oracle",
        )
        result = generator._generate_index_create_statement(index)
        assert "CREATE BITMAP INDEX" in result.upper()

    def test_generate_index_create_statement_with_schema(self):
        """Test generating CREATE INDEX with schema."""
        generator = OracleSqlGenerator()
        index = Index(
            name="idx_email",
            table_name="users",
            schema="myschema",
            columns=["email"],
            dialect="oracle",
        )
        result = generator._generate_index_create_statement(index)
        assert "myschema" in result.lower() or '"myschema"' in result

    def test_generate_index_create_statement_with_table_schema(self):
        """Test generating CREATE INDEX with table schema."""
        generator = OracleSqlGenerator()
        index = Index(
            name="idx_email",
            table_name="users",
            table_schema="myschema",
            columns=["email"],
            dialect="oracle",
        )
        result = generator._generate_index_create_statement(index)
        assert "myschema" in result.lower() or '"myschema"' in result

    def test_generate_index_create_statement_with_expression(self):
        """Test generating CREATE INDEX with expression."""
        generator = OracleSqlGenerator()
        index = Index(
            name="idx_expr",
            table_name="users",
            columns=["UPPER(email)"],
            expression_flags=[True],
            dialect="oracle",
        )
        result = generator._generate_index_create_statement(index)
        assert "UPPER(email)" in result

    def test_generate_index_create_statement_with_sort_direction(self):
        """Test generating CREATE INDEX with sort direction."""
        generator = OracleSqlGenerator()
        index = Index(
            name="idx_email",
            table_name="users",
            columns=["email"],
            sort_directions=["DESC"],
            dialect="oracle",
        )
        result = generator._generate_index_create_statement(index)
        assert "DESC" in result.upper()

    def test_generate_index_create_statement_local(self):
        """Test generating CREATE INDEX with LOCAL clause."""
        generator = OracleSqlGenerator()
        index = Index(name="idx_email", table_name="users", columns=["email"], dialect="oracle")
        index.is_local = True
        result = generator._generate_index_create_statement(index)
        assert "LOCAL" in result.upper()

    def test_generate_index_create_statement_tablespace(self):
        """Test generating CREATE INDEX with TABLESPACE clause."""
        generator = OracleSqlGenerator()
        index = Index(name="idx_email", table_name="users", columns=["email"], dialect="oracle")
        index.tablespace = "users_tbs"
        result = generator._generate_index_create_statement(index)
        assert "TABLESPACE" in result.upper()
        assert "users_tbs" in result.lower() or '"users_tbs"' in result


@pytest.mark.unit
class TestOracleSqlGeneratorProcedureCreate:
    """Tests for _generate_procedure_create_statement method."""

    def test_generate_procedure_create_statement_with_definition(self):
        """Test generating CREATE PROCEDURE from definition."""
        generator = OracleSqlGenerator()
        procedure = Procedure(
            name="proc_test",
            body="BEGIN SELECT 1 END",
            definition="CREATE OR REPLACE PROCEDURE proc_test AS BEGIN SELECT 1 END",
            dialect="oracle",
        )
        result = generator._generate_procedure_create_statement(procedure)
        # When definition is provided, it's returned as-is
        assert "CREATE OR REPLACE PROCEDURE" in result.upper()
        assert "proc_test" in result.lower()

    def test_generate_procedure_create_statement_simple(self):
        """Test generating simple CREATE OR REPLACE PROCEDURE statement."""
        generator = OracleSqlGenerator()
        procedure = Procedure(name="proc_test", body="BEGIN SELECT 1 END", dialect="oracle")
        result = generator._generate_procedure_create_statement(procedure)
        assert "CREATE OR REPLACE PROCEDURE" in result.upper()
        assert "proc_test" in result.lower() or '"proc_test"' in result
        assert "AS" in result.upper()
        assert "SELECT 1" in result

    def test_generate_procedure_create_statement_with_schema(self):
        """Test generating CREATE PROCEDURE with schema."""
        generator = OracleSqlGenerator()
        procedure = Procedure(
            name="proc_test", schema="myschema", body="BEGIN SELECT 1 END", dialect="oracle"
        )
        result = generator._generate_procedure_create_statement(procedure)
        assert "myschema" in result.lower() or '"myschema"' in result

    def test_generate_procedure_create_statement_with_parameters(self):
        """Test generating CREATE PROCEDURE with parameters."""
        generator = OracleSqlGenerator()
        from core.sql_model.procedure import Parameter

        param = Parameter(name="id", data_type="NUMBER")
        procedure = Procedure(
            name="proc_test", parameters=[param], body="BEGIN SELECT id END", dialect="oracle"
        )
        result = generator._generate_procedure_create_statement(procedure)
        assert "id" in result.lower() or '"id"' in result
        assert "NUMBER" in result.upper()

    def test_generate_procedure_create_statement_with_output_parameter(self):
        """Test generating CREATE PROCEDURE with OUT parameter."""
        generator = OracleSqlGenerator()
        from core.sql_model.procedure import Parameter

        param = Parameter(name="result", data_type="NUMBER", direction="OUT")
        procedure = Procedure(
            name="proc_test", parameters=[param], body="BEGIN SET result = 1 END", dialect="oracle"
        )
        result = generator._generate_procedure_create_statement(procedure)
        assert "OUT" in result.upper()

    def test_generate_procedure_create_statement_with_default_parameter(self):
        """Test generating CREATE PROCEDURE with DEFAULT parameter."""
        generator = OracleSqlGenerator()
        from core.sql_model.procedure import Parameter

        param = Parameter(name="id", data_type="NUMBER", default_value="1")
        procedure = Procedure(
            name="proc_test", parameters=[param], body="BEGIN SELECT id END", dialect="oracle"
        )
        result = generator._generate_procedure_create_statement(procedure)
        assert "DEFAULT 1" in result.upper()

    def test_generate_procedure_create_statement_empty_parameters(self):
        """Test generating CREATE PROCEDURE with empty parameter list."""
        generator = OracleSqlGenerator()
        procedure = Procedure(
            name="proc_test", parameters=[], body="BEGIN SELECT 1 END", dialect="oracle"
        )
        result = generator._generate_procedure_create_statement(procedure)
        assert "proc_test()" in result.lower() or '"proc_test"()' in result

    def test_generate_procedure_create_statement_function(self):
        """Test generating CREATE OR REPLACE FUNCTION statement."""
        generator = OracleSqlGenerator()
        function = Procedure(
            name="func_test",
            body="RETURN 1",
            is_function=True,
            return_type="NUMBER",
            dialect="oracle",
        )
        result = generator._generate_procedure_create_statement(function)
        assert "CREATE OR REPLACE FUNCTION" in result.upper()
        assert "RETURN NUMBER" in result.upper()

    def test_generate_procedure_create_statement_system_function(self):
        """Test skipping system functions."""
        generator = OracleSqlGenerator()
        function = Procedure(name="<", is_function=True, dialect="oracle")
        result = generator._generate_procedure_create_statement(function)
        assert result == ""


@pytest.mark.unit
class TestOracleSqlGeneratorSynonymCreate:
    """Tests for _generate_synonym_create_statement method."""

    def test_generate_synonym_create_statement_simple(self):
        """Test generating simple CREATE OR REPLACE SYNONYM statement."""
        generator = OracleSqlGenerator()
        synonym = Synonym(name="syn_test", target_object="users", dialect="oracle")
        result = generator._generate_synonym_create_statement(synonym)
        assert "CREATE OR REPLACE SYNONYM" in result.upper()
        assert "syn_test" in result.lower() or '"syn_test"' in result
        assert "FOR" in result.upper()

    def test_generate_synonym_create_statement_with_schema(self):
        """Test generating CREATE SYNONYM with schema."""
        generator = OracleSqlGenerator()
        synonym = Synonym(
            name="syn_test", schema="myschema", target_object="users", dialect="oracle"
        )
        result = generator._generate_synonym_create_statement(synonym)
        assert "myschema" in result.lower() or '"myschema"' in result


@pytest.mark.unit
class TestOracleSqlGeneratorSequenceCreate:
    """Tests for _generate_sequence_create_statement method."""

    def test_generate_sequence_create_statement_simple(self):
        """Test generating simple CREATE SEQUENCE statement."""
        generator = OracleSqlGenerator()
        sequence = Sequence(name="seq_id", dialect="oracle")
        result = generator._generate_sequence_create_statement(sequence)
        assert "CREATE SEQUENCE" in result.upper()
        assert "seq_id" in result.lower() or '"seq_id"' in result
        assert "NOCACHE" in result.upper()

    def test_generate_sequence_create_statement_with_start(self):
        """Test generating CREATE SEQUENCE with START WITH."""
        generator = OracleSqlGenerator()
        sequence = Sequence(name="seq_id", start_with=100, dialect="oracle")
        result = generator._generate_sequence_create_statement(sequence)
        assert "START WITH 100" in result.upper()

    def test_generate_sequence_create_statement_with_increment(self):
        """Test generating CREATE SEQUENCE with INCREMENT BY."""
        generator = OracleSqlGenerator()
        sequence = Sequence(name="seq_id", increment_by=2, dialect="oracle")
        result = generator._generate_sequence_create_statement(sequence)
        assert "INCREMENT BY 2" in result.upper()

    def test_generate_sequence_create_statement_with_min_max(self):
        """Test generating CREATE SEQUENCE with MINVALUE and MAXVALUE."""
        generator = OracleSqlGenerator()
        sequence = Sequence(name="seq_id", min_value=1, max_value=1000, dialect="oracle")
        result = generator._generate_sequence_create_statement(sequence)
        assert "MINVALUE 1" in result.upper()
        assert "MAXVALUE 1000" in result.upper()

    def test_generate_sequence_create_statement_with_cycle(self):
        """Test generating CREATE SEQUENCE with CYCLE."""
        generator = OracleSqlGenerator()
        sequence = Sequence(name="seq_id", cycle=True, dialect="oracle")
        result = generator._generate_sequence_create_statement(sequence)
        assert "CYCLE" in result.upper()

    def test_generate_sequence_create_statement_nocycle(self):
        """Test generating CREATE SEQUENCE with NOCYCLE."""
        generator = OracleSqlGenerator()
        sequence = Sequence(name="seq_id", cycle=False, dialect="oracle")
        result = generator._generate_sequence_create_statement(sequence)
        assert "NOCYCLE" in result.upper()

    def test_generate_sequence_create_statement_nocache(self):
        """Test generating CREATE SEQUENCE with NOCACHE."""
        generator = OracleSqlGenerator()
        sequence = Sequence(name="seq_id", cache=None, dialect="oracle")
        result = generator._generate_sequence_create_statement(sequence)
        assert "NOCACHE" in result.upper()

    def test_generate_sequence_create_statement_cache_one(self):
        """Test generating CREATE SEQUENCE with NOCACHE when cache <= 1."""
        generator = OracleSqlGenerator()
        sequence = Sequence(name="seq_id", cache=1, dialect="oracle")
        result = generator._generate_sequence_create_statement(sequence)
        assert "NOCACHE" in result.upper()

    def test_generate_sequence_create_statement_with_cache(self):
        """Test generating CREATE SEQUENCE with CACHE."""
        generator = OracleSqlGenerator()
        sequence = Sequence(name="seq_id", cache=10, dialect="oracle")
        result = generator._generate_sequence_create_statement(sequence)
        assert "CACHE 10" in result.upper()


@pytest.mark.unit
class TestOracleSqlGeneratorUserDefinedTypeCreate:
    """Tests for _generate_user_defined_type_create_statement method."""

    def test_generate_user_defined_type_create_statement_composite(self):
        """Test generating CREATE TYPE AS OBJECT for composite type."""
        generator = OracleSqlGenerator()
        udt = UserDefinedType(
            name="address_type",
            type_category="COMPOSITE",
            attributes=[
                {"name": "street", "type": "VARCHAR2(100)"},
                {"name": "city", "type": "VARCHAR2(50)"},
            ],
            dialect="oracle",
        )
        result = generator._generate_user_defined_type_create_statement(udt)
        assert "CREATE TYPE" in result.upper()
        assert "AS OBJECT" in result.upper()
        assert "street" in result.lower()
        assert "city" in result.lower()

    def test_generate_user_defined_type_create_statement_enum(self):
        """Test generating CREATE TYPE for ENUM type (VARCHAR2 workaround)."""
        generator = OracleSqlGenerator()
        udt = UserDefinedType(
            name="status_enum",
            type_category="ENUM",
            enum_values=["active", "inactive"],
            dialect="oracle",
        )
        result = generator._generate_user_defined_type_create_statement(udt)
        assert "CREATE TYPE" in result.upper()
        assert "AS VARCHAR2" in result.upper()
        assert "active" in result.lower()
        assert "inactive" in result.lower()

    def test_generate_user_defined_type_create_statement_with_definition(self):
        """Test generating CREATE TYPE with definition."""
        generator = OracleSqlGenerator()
        udt = UserDefinedType(
            name="custom_type",
            type_category="DISTINCT",
            definition="VARCHAR2(100)",
            dialect="oracle",
        )
        result = generator._generate_user_defined_type_create_statement(udt)
        assert "CREATE TYPE" in result.upper()
        assert "AS VARCHAR2(100)" in result.upper()

    def test_generate_user_defined_type_create_statement_fallback(self):
        """Test generating CREATE TYPE fallback."""
        generator = OracleSqlGenerator()
        udt = UserDefinedType(name="custom_type", type_category="UNKNOWN", dialect="oracle")
        result = generator._generate_user_defined_type_create_statement(udt)
        assert "CREATE TYPE" in result.upper()
        assert "custom_type" in result.lower() or '"custom_type"' in result


@pytest.mark.unit
class TestOracleSqlGeneratorTriggerCreate:
    """Tests for _generate_trigger_create_statement method."""

    def test_generate_trigger_create_statement_with_definition(self):
        """Test generating CREATE TRIGGER from definition."""
        generator = OracleSqlGenerator()
        trigger = Trigger(
            name="trg_insert",
            table_name="users",
            events=["INSERT"],
            definition="CREATE TRIGGER trg_insert BEFORE INSERT ON users FOR EACH ROW BEGIN SELECT 1; END",
            dialect="oracle",
        )
        result = generator._generate_trigger_create_statement(trigger)
        assert "CREATE TRIGGER" in result.upper()

    def test_generate_trigger_create_statement_simple(self):
        """Test generating simple CREATE TRIGGER statement."""
        generator = OracleSqlGenerator()
        trigger = Trigger(
            name="trg_insert", table_name="users", events=["INSERT"], dialect="oracle"
        )
        trigger.definition = "SELECT 1;"
        result = generator._generate_trigger_create_statement(trigger)
        assert "CREATE TRIGGER" in result.upper()
        assert "trg_insert" in result.lower() or '"trg_insert"' in result
        assert "ON" in result.upper()
        assert "users" in result.lower() or '"users"' in result
        assert result.endswith("/")

    def test_generate_trigger_create_statement_with_timing(self):
        """Test generating CREATE TRIGGER with timing."""
        generator = OracleSqlGenerator()
        trigger = Trigger(
            name="trg_insert",
            table_name="users",
            events=["INSERT"],
            timing="AFTER",
            dialect="oracle",
        )
        trigger.definition = "SELECT 1;"
        result = generator._generate_trigger_create_statement(trigger)
        assert "AFTER" in result.upper()

    def test_generate_trigger_create_statement_with_orientation(self):
        """Test generating CREATE TRIGGER with FOR EACH ROW."""
        generator = OracleSqlGenerator()
        trigger = Trigger(
            name="trg_insert", table_name="users", events=["INSERT"], dialect="oracle"
        )
        trigger.orientation = "ROW"
        trigger.definition = "SELECT 1;"
        result = generator._generate_trigger_create_statement(trigger)
        assert "FOR EACH ROW" in result.upper()

    def test_generate_trigger_create_statement_with_follows(self):
        """Test generating CREATE TRIGGER with FOLLOWS clause."""
        generator = OracleSqlGenerator()
        trigger = Trigger(
            name="trg_insert", table_name="users", events=["INSERT"], dialect="oracle"
        )
        trigger.follows_trigger = "trg_before"
        trigger.definition = "SELECT 1;"
        result = generator._generate_trigger_create_statement(trigger)
        assert "FOLLOWS" in result.upper()
        assert "trg_before" in result.lower() or '"trg_before"' in result

    def test_generate_trigger_create_statement_with_precedes(self):
        """Test generating CREATE TRIGGER with PRECEDES clause."""
        generator = OracleSqlGenerator()
        trigger = Trigger(
            name="trg_insert", table_name="users", events=["INSERT"], dialect="oracle"
        )
        trigger.precedes_trigger = "trg_after"
        trigger.definition = "SELECT 1;"
        result = generator._generate_trigger_create_statement(trigger)
        assert "PRECEDES" in result.upper()
        assert "trg_after" in result.lower() or '"trg_after"' in result


@pytest.mark.unit
class TestOracleCreateDispatch:
    """Test _get_create_dispatch registry for Oracle."""

    def test_get_create_dispatch_contains_expected_types(self):
        """Verify dispatch contains all 9 Oracle types (including Package)."""
        from core.sql_model.index import Index
        from core.sql_model.package import Package
        from core.sql_model.procedure import Procedure
        from core.sql_model.sequence import Sequence
        from core.sql_model.synonym import Synonym
        from core.sql_model.table import Table
        from core.sql_model.trigger import Trigger
        from core.sql_model.user_defined_type import UserDefinedType
        from core.sql_model.view import View

        generator = OracleSqlGenerator()
        dispatch = generator._get_create_dispatch()
        assert View in dispatch
        assert Index in dispatch
        assert Procedure in dispatch
        assert Table in dispatch
        assert Synonym in dispatch
        assert Sequence in dispatch
        assert UserDefinedType in dispatch
        assert Trigger in dispatch
        assert Package in dispatch
        assert len(dispatch) == 9

    def test_generate_create_statement_dispatches_view(self):
        """generate_create_statement routes View to _generate_view_create_statement."""
        from unittest.mock import patch

        from core.sql_model.view import View

        gen = OracleSqlGenerator()
        view = View(name="test_view", dialect="oracle")
        with patch.object(
            gen, "_generate_view_create_statement", return_value="ORA_VIEW_SQL"
        ) as mock:
            result = gen.generate_create_statement(view)
        mock.assert_called_once_with(view)
        assert result == "ORA_VIEW_SQL"

    def test_generate_create_fallback_uses_base_getattr(self):
        """Oracle has no _generate_create_fallback override — uses base getattr behavior."""
        from unittest.mock import MagicMock

        generator = OracleSqlGenerator()

        # Object with create_statement attribute — base fallback returns the value
        obj_with = MagicMock()
        obj_with.create_statement = "CREATE TABLE oracle_obj"
        result = generator._generate_create_fallback(obj_with)
        assert result == "CREATE TABLE oracle_obj"

        # Object without create_statement — base fallback returns ""
        obj_without = object()
        result = generator._generate_create_fallback(obj_without)
        assert result == ""
