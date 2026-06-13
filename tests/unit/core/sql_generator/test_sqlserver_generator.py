"""Tests for SQLServerSqlGenerator class."""

from unittest.mock import MagicMock, patch

import pytest

from core.sql_model.base import SqlColumn, SqlConstraint
from core.sql_model.index import Index
from core.sql_model.procedure import Procedure
from core.sql_model.sequence import Sequence
from core.sql_model.synonym import Synonym
from core.sql_model.table import Table
from core.sql_model.trigger import Trigger
from core.sql_model.user_defined_type import UserDefinedType
from core.sql_model.view import View
from db.plugins.sqlserver.generator.ddl_generator import SQLServerSqlGenerator
from db.plugins.sqlserver.quirks import SqlserverQuirks


@pytest.mark.unit
class TestSQLServerSqlGeneratorInit:
    """Tests for SQLServerSqlGenerator initialization."""

    def test_init(self):
        """Test initialization."""
        generator = SQLServerSqlGenerator()
        assert generator is not None


@pytest.mark.unit
class TestSQLServerSqlGeneratorFormatStatements:
    """Tests for _format_statements method."""

    def test_format_statements_empty(self):
        """Test formatting empty statements list."""
        generator = SQLServerSqlGenerator()
        result = generator._format_statements([], "sqlserver")
        assert result == ""

    def test_format_statements_single(self):
        """Test formatting single statement."""
        generator = SQLServerSqlGenerator()
        statements = ["CREATE TABLE users (id INT)"]
        result = generator._format_statements(statements, "sqlserver")
        assert "CREATE TABLE" in result
        assert "GO" in result

    def test_format_statements_multiple(self):
        """Test formatting multiple statements."""
        generator = SQLServerSqlGenerator()
        statements = ["CREATE TABLE users (id INT)", "CREATE TABLE orders (id INT)"]
        result = generator._format_statements(statements, "sqlserver")
        assert "CREATE TABLE users" in result
        assert "CREATE TABLE orders" in result
        assert result.count("GO") >= 2

    def test_format_statements_filters_empty(self):
        """Test filtering empty statements."""
        generator = SQLServerSqlGenerator()
        statements = ["CREATE TABLE users (id INT)", "", "   ", "CREATE TABLE orders (id INT)"]
        result = generator._format_statements(statements, "sqlserver")
        assert "CREATE TABLE users" in result
        assert "CREATE TABLE orders" in result
        assert result.count("GO") >= 2


@pytest.mark.unit
class TestSQLServerSqlGeneratorDropStatement:
    """Tests for _generate_drop_statement method."""

    def test_generate_drop_statement_table(self):
        """Test generating DROP TABLE statement."""
        generator = SQLServerSqlGenerator()
        table = Table(name="users", columns=[SqlColumn("id", "INTEGER")], dialect="sqlserver")
        result = generator._generate_drop_statement(table, "sqlserver")
        assert "DROP TABLE IF EXISTS" in result.upper()
        assert "users" in result.lower()

    def test_generate_drop_statement_table_with_schema(self):
        """Test generating DROP TABLE with schema."""
        generator = SQLServerSqlGenerator()
        table = Table(
            name="users", schema="dbo", columns=[SqlColumn("id", "INTEGER")], dialect="sqlserver"
        )
        result = generator._generate_drop_statement(table, "sqlserver")
        assert "DROP TABLE IF EXISTS" in result.upper()
        assert "dbo" in result.lower() or '"dbo"' in result
        assert "users" in result.lower()

    def test_generate_drop_statement_view(self):
        """Test generating DROP VIEW statement."""
        generator = SQLServerSqlGenerator()
        view = View(name="active_users", query="SELECT 1", dialect="sqlserver")
        result = generator._generate_drop_statement(view, "sqlserver")
        assert "DROP VIEW IF EXISTS" in result.upper()
        assert "active_users" in result.lower()

    def test_generate_drop_statement_materialized_view_uses_drop_view(self):
        """Test SQL Server indexed views are dropped as views."""
        generator = SQLServerSqlGenerator()
        view = View(
            name="v_sales_total",
            schema="dbo",
            query="SELECT 1",
            materialized=True,
            dialect="sqlserver",
        )

        result = generator._generate_drop_statement(view, "sqlserver")

        assert result == "DROP VIEW IF EXISTS [dbo].[v_sales_total]"
        assert "MATERIALIZED_VIEW" not in result.upper()

    def test_generate_drop_statement_index(self):
        """Test generating DROP INDEX statement."""
        generator = SQLServerSqlGenerator()
        index = Index(name="idx_email", table_name="users", columns=["email"], dialect="sqlserver")
        result = generator._generate_drop_statement(index, "sqlserver")
        assert "DROP INDEX IF EXISTS" in result.upper()
        assert "idx_email" in result.lower()
        assert "ON" in result.upper()
        assert "users" in result.lower()

    def test_generate_drop_statement_sequence(self):
        """Test generating DROP SEQUENCE statement."""
        generator = SQLServerSqlGenerator()
        sequence = Sequence(name="seq_id", dialect="sqlserver")
        result = generator._generate_drop_statement(sequence, "sqlserver")
        assert "DROP SEQUENCE IF EXISTS" in result.upper()
        assert "seq_id" in result.lower()

    def test_generate_drop_statement_procedure(self):
        """Test generating DROP PROCEDURE statement."""
        generator = SQLServerSqlGenerator()
        procedure = Procedure(name="proc_test", body="BEGIN END", dialect="sqlserver")
        result = generator._generate_drop_statement(procedure, "sqlserver")
        assert "DROP PROCEDURE IF EXISTS" in result.upper()
        assert "proc_test" in result.lower()

    def test_generate_drop_statement_function(self):
        """Test generating DROP FUNCTION statement."""
        generator = SQLServerSqlGenerator()
        function = Procedure(
            name="func_test", body="RETURN 1", is_function=True, dialect="sqlserver"
        )
        result = generator._generate_drop_statement(function, "sqlserver")
        assert "DROP FUNCTION IF EXISTS" in result.upper()
        assert "func_test" in result.lower()

    def test_generate_drop_statement_trigger(self):
        """Test generating DROP TRIGGER statement."""
        generator = SQLServerSqlGenerator()
        trigger = Trigger(
            name="trg_insert", table_name="users", events=["INSERT"], dialect="sqlserver"
        )
        result = generator._generate_drop_statement(trigger, "sqlserver")
        assert "DROP TRIGGER IF EXISTS" in result.upper()
        assert "trg_insert" in result.lower()

    def test_generate_drop_statement_fallback(self):
        """Test generating DROP statement fallback."""
        generator = SQLServerSqlGenerator()
        obj = MagicMock()
        obj.schema = None
        obj.name = "test_obj"
        obj.format_identifier = lambda x: x
        obj.object_type = "UNKNOWN_TYPE"
        result = generator._generate_drop_statement(obj, "sqlserver")
        assert "DROP UNKNOWN_TYPE IF EXISTS" in result.upper()


@pytest.mark.unit
class TestSQLServerQuirks:
    """Tests for SQL Server dialect quirks."""

    def test_script_header_includes_indexed_view_set_options(self):
        """Test exported scripts include session options required by indexed views."""
        header = "\n".join(SqlserverQuirks().script_header_session_init()).upper()

        assert "SET ANSI_NULLS ON" in header
        assert "SET QUOTED_IDENTIFIER ON" in header
        assert "SET ANSI_PADDING ON" in header
        assert "SET ANSI_WARNINGS ON" in header
        assert "SET CONCAT_NULL_YIELDS_NULL ON" in header
        assert "SET ARITHABORT ON" in header
        assert "SET NUMERIC_ROUNDABORT OFF" in header


@pytest.mark.unit
class TestSQLServerSqlGeneratorCreateStatement:
    """Tests for generate_create_statement method."""

    def test_generate_create_statement_view(self):
        """Test generating CREATE VIEW statement."""
        generator = SQLServerSqlGenerator()
        view = View(name="active_users", query="SELECT id FROM users", dialect="sqlserver")
        result = generator.generate_create_statement(view)
        assert "CREATE VIEW" in result.upper()
        assert "active_users" in result.lower()

    def test_generate_create_statement_index(self):
        """Test generating CREATE INDEX statement."""
        generator = SQLServerSqlGenerator()
        index = Index(name="idx_email", table_name="users", columns=["email"], dialect="sqlserver")
        result = generator.generate_create_statement(index)
        assert "CREATE INDEX" in result.upper()
        assert "idx_email" in result.lower()
        assert "ON" in result.upper()

    def test_generate_create_statement_procedure(self):
        """Test generating CREATE PROCEDURE statement."""
        generator = SQLServerSqlGenerator()
        procedure = Procedure(name="proc_test", body="BEGIN SELECT 1 END", dialect="sqlserver")
        result = generator.generate_create_statement(procedure)
        assert "CREATE PROCEDURE" in result.upper()
        assert "proc_test" in result.lower()

    def test_generate_create_statement_table(self):
        """Test generating CREATE TABLE statement."""
        generator = SQLServerSqlGenerator()
        table = Table(
            name="users",
            columns=[SqlColumn("id", "INTEGER"), SqlColumn("name", "VARCHAR(100)")],
            dialect="sqlserver",
        )
        result = generator.generate_create_statement(table)
        assert "CREATE TABLE" in result.upper()
        assert "users" in result.lower()

    def test_generate_create_statement_synonym(self):
        """Test generating CREATE SYNONYM statement."""
        generator = SQLServerSqlGenerator()
        synonym = Synonym(name="syn_test", target_object="users", dialect="sqlserver")
        result = generator.generate_create_statement(synonym)
        assert "CREATE SYNONYM" in result.upper()
        assert "syn_test" in result.lower()

    def test_generate_create_statement_sequence(self):
        """Test generating CREATE SEQUENCE statement."""
        generator = SQLServerSqlGenerator()
        sequence = Sequence(name="seq_id", dialect="sqlserver")
        result = generator.generate_create_statement(sequence)
        assert "CREATE SEQUENCE" in result.upper()
        assert "seq_id" in result.lower()

    def test_generate_create_statement_user_defined_type(self):
        """Test generating CREATE TYPE statement."""
        generator = SQLServerSqlGenerator()
        udt = UserDefinedType(
            name="status_type",
            type_category="DISTINCT",
            base_type="VARCHAR(50)",
            dialect="sqlserver",
        )
        result = generator.generate_create_statement(udt)
        assert "CREATE TYPE" in result.upper()
        assert "status_type" in result.lower()

    def test_generate_create_statement_trigger(self):
        """Test generating CREATE TRIGGER statement."""
        generator = SQLServerSqlGenerator()
        trigger = Trigger(
            name="trg_insert", table_name="users", events=["INSERT"], dialect="sqlserver"
        )
        result = generator.generate_create_statement(trigger)
        assert "CREATE TRIGGER" in result.upper()
        assert "trg_insert" in result.lower()

    def test_generate_create_statement_fallback(self):
        """Test generating CREATE statement fallback."""
        generator = SQLServerSqlGenerator()
        obj = MagicMock()
        obj.schema = None
        obj.name = "test_obj"
        obj.format_identifier = lambda x: x
        obj.object_type = "UNKNOWN_TYPE"
        result = generator.generate_create_statement(obj)
        assert "CREATE UNKNOWN_TYPE" in result.upper()


@pytest.mark.unit
class TestSQLServerSqlGeneratorViewCreate:
    """Tests for _generate_view_create_statement method."""

    def test_generate_view_create_statement_simple(self):
        """Test generating simple CREATE VIEW statement."""
        generator = SQLServerSqlGenerator()
        view = View(name="active_users", query="SELECT id FROM users", dialect="sqlserver")
        result = generator._generate_view_create_statement(view)
        assert "CREATE VIEW" in result.upper()
        assert "active_users" in result.lower()
        assert "SELECT id FROM users" in result

    def test_generate_view_create_statement_with_schema(self):
        """Test generating CREATE VIEW with schema."""
        generator = SQLServerSqlGenerator()
        view = View(name="active_users", schema="dbo", query="SELECT 1", dialect="sqlserver")
        result = generator._generate_view_create_statement(view)
        assert "dbo" in result.lower() or '"dbo"' in result

    def test_generate_view_create_statement_with_columns(self):
        """Test generating CREATE VIEW with column list."""
        generator = SQLServerSqlGenerator()
        view = View(
            name="active_users",
            columns=["id", "name"],
            query="SELECT id, name FROM users",
            dialect="sqlserver",
        )
        result = generator._generate_view_create_statement(view)
        assert "active_users" in result.lower()
        assert "id" in result.lower() or '"id"' in result

    def test_generate_view_create_statement_materialized(self):
        """Test generating CREATE VIEW with SCHEMABINDING."""
        generator = SQLServerSqlGenerator()
        view = View(
            name="active_users",
            query="SELECT id FROM users",
            materialized=True,
            dialect="sqlserver",
        )
        result = generator._generate_view_create_statement(view)
        assert "SCHEMABINDING" in result.upper()

    def test_generate_view_create_statement_extract_select(self):
        """Test extracting SELECT from CREATE VIEW statement."""
        generator = SQLServerSqlGenerator()
        view = View(
            name="active_users",
            query="CREATE VIEW active_users AS SELECT id FROM users",
            dialect="sqlserver",
        )
        result = generator._generate_view_create_statement(view)
        assert "CREATE VIEW" in result.upper()
        assert "SELECT id FROM users" in result

    def test_generate_materialized_view_from_object_definition_keeps_schemabinding_once(self):
        """Indexed views exported from OBJECT_DEFINITION keep schemabinding in the DDL."""
        generator = SQLServerSqlGenerator()
        view = View(
            name="order_summary",
            schema="dbo",
            columns=["user_id", "cnt"],
            query=(
                "CREATE VIEW dbo.order_summary WITH SCHEMABINDING AS "
                "SELECT user_id, COUNT_BIG(*) AS cnt FROM dbo.orders GROUP BY user_id"
            ),
            materialized=True,
            dialect="sqlserver",
        )
        view.clustered_index_name = "idx_order_summary"  # type: ignore[attr-defined]
        view.clustered_index_columns = ["user_id"]  # type: ignore[attr-defined]

        result = generator._generate_view_create_statement(view)
        upper = result.upper()
        assert upper.count("WITH SCHEMABINDING") == 1
        assert upper.index("WITH SCHEMABINDING") < upper.index(" AS")
        assert "SELECT user_id, COUNT_BIG(*) AS cnt FROM dbo.orders GROUP BY user_id" in result
        assert "CREATE UNIQUE CLUSTERED INDEX" not in upper

    def test_generate_ddl_separates_indexed_view_clustered_index_with_go(self):
        """Indexed-view clustered index is emitted as a separate SQL Server batch."""
        generator = SQLServerSqlGenerator()
        view = View(
            name="order_summary",
            schema="dbo",
            query="SELECT user_id, COUNT_BIG(*) AS cnt FROM dbo.orders GROUP BY user_id",
            materialized=True,
            dialect="sqlserver",
        )
        view.clustered_index_name = "idx_order_summary"  # type: ignore[attr-defined]
        view.clustered_index_columns = ["user_id"]  # type: ignore[attr-defined]

        result = generator.generate_ddl([view], target_dialect="sqlserver")
        upper = result.upper()
        assert upper.count("WITH SCHEMABINDING") == 1
        assert "CREATE UNIQUE CLUSTERED INDEX" in upper
        assert upper.index("WITH SCHEMABINDING") < upper.index("CREATE UNIQUE CLUSTERED INDEX")
        assert "GO\n\nCREATE UNIQUE CLUSTERED INDEX" in upper
        assert result.rstrip().endswith("GO")


@pytest.mark.unit
class TestSQLServerSqlGeneratorIndexCreate:
    """Tests for _generate_index_create_statement method."""

    def test_generate_index_create_statement_simple(self):
        """Test generating simple CREATE INDEX statement."""
        generator = SQLServerSqlGenerator()
        index = Index(name="idx_email", table_name="users", columns=["email"], dialect="sqlserver")
        result = generator._generate_index_create_statement(index)
        assert "CREATE INDEX" in result.upper()
        assert "idx_email" in result.lower()
        assert "ON" in result.upper()
        assert "users" in result.lower()
        assert "email" in result.lower()

    def test_generate_index_create_statement_unique(self):
        """Test generating CREATE UNIQUE INDEX statement."""
        generator = SQLServerSqlGenerator()
        index = Index(
            name="idx_email",
            table_name="users",
            columns=["email"],
            unique=True,
            dialect="sqlserver",
        )
        result = generator._generate_index_create_statement(index)
        assert "CREATE UNIQUE INDEX" in result.upper()

    def test_generate_index_create_statement_with_schema(self):
        """Test generating CREATE INDEX with schema."""
        generator = SQLServerSqlGenerator()
        index = Index(
            name="idx_email",
            table_name="users",
            table_schema="dbo",
            columns=["email"],
            dialect="sqlserver",
        )
        result = generator._generate_index_create_statement(index)
        assert "dbo" in result.lower() or '"dbo"' in result

    def test_generate_index_create_statement_with_expression(self):
        """Test generating CREATE INDEX with expression."""
        generator = SQLServerSqlGenerator()
        index = Index(
            name="idx_expr",
            table_name="users",
            columns=["UPPER(email)"],
            expression_flags=[True],
            dialect="sqlserver",
        )
        result = generator._generate_index_create_statement(index)
        assert "UPPER(email)" in result

    def test_generate_index_create_statement_with_sort_direction(self):
        """Test generating CREATE INDEX with sort direction."""
        generator = SQLServerSqlGenerator()
        index = Index(
            name="idx_email",
            table_name="users",
            columns=["email"],
            sort_directions=["DESC"],
            dialect="sqlserver",
        )
        result = generator._generate_index_create_statement(index)
        assert "DESC" in result.upper()

    def test_generate_index_create_statement_with_include(self):
        """Test generating CREATE INDEX with INCLUDE clause."""
        generator = SQLServerSqlGenerator()
        index = Index(
            name="idx_email",
            table_name="users",
            columns=["email"],
            include_columns=["name", "created_at"],
            dialect="sqlserver",
        )
        result = generator._generate_index_create_statement(index)
        assert "INCLUDE" in result.upper()
        assert "name" in result.lower()
        assert "created_at" in result.lower()

    def test_generate_index_create_statement_with_where(self):
        """Test generating CREATE INDEX with WHERE clause."""
        generator = SQLServerSqlGenerator()
        index = Index(
            name="idx_email",
            table_name="users",
            columns=["email"],
            condition="email IS NOT NULL",
            dialect="sqlserver",
        )
        result = generator._generate_index_create_statement(index)
        assert "WHERE" in result.upper()
        assert "email IS NOT NULL" in result

    def test_generate_index_create_statement_with_fillfactor(self):
        """Test generating CREATE INDEX with FILLFACTOR."""
        generator = SQLServerSqlGenerator()
        index = Index(
            name="idx_email",
            table_name="users",
            columns=["email"],
            fillfactor=80,
            dialect="sqlserver",
        )
        result = generator._generate_index_create_statement(index)
        assert "FILLFACTOR" in result.upper()
        assert "80" in result

    def test_generate_index_create_statement_with_compression(self):
        """Test generating CREATE INDEX with compression."""
        generator = SQLServerSqlGenerator()
        index = Index(
            name="idx_email",
            table_name="users",
            columns=["email"],
            compression="PAGE",
            dialect="sqlserver",
        )
        result = generator._generate_index_create_statement(index)
        assert "DATA_COMPRESSION" in result.upper()
        assert "PAGE" in result.upper()


@pytest.mark.unit
class TestSQLServerSqlGeneratorProcedureCreate:
    """Tests for _generate_procedure_create_statement method."""

    def test_generate_procedure_create_statement_with_definition(self):
        """Test generating CREATE PROCEDURE from definition."""
        generator = SQLServerSqlGenerator()
        procedure = Procedure(
            name="proc_test",
            body="BEGIN SELECT 1 END",
            definition="CREATE PROCEDURE proc_test AS BEGIN SELECT 1 END",
            dialect="sqlserver",
        )
        result = generator._generate_procedure_create_statement(procedure)
        # When definition is provided, it's returned as-is
        assert "CREATE PROCEDURE" in result.upper()
        assert "proc_test" in result.lower()

    def test_generate_procedure_create_statement_simple(self):
        """Test generating simple CREATE PROCEDURE statement."""
        generator = SQLServerSqlGenerator()
        procedure = Procedure(name="proc_test", body="BEGIN SELECT 1 END", dialect="sqlserver")
        result = generator._generate_procedure_create_statement(procedure)
        assert "CREATE PROCEDURE" in result.upper()
        assert "proc_test" in result.lower()
        assert "BEGIN" in result.upper()
        assert "SELECT 1" in result

    def test_generate_procedure_create_statement_with_schema(self):
        """Test generating CREATE PROCEDURE with schema."""
        generator = SQLServerSqlGenerator()
        procedure = Procedure(
            name="proc_test", schema="dbo", body="BEGIN SELECT 1 END", dialect="sqlserver"
        )
        result = generator._generate_procedure_create_statement(procedure)
        assert "dbo" in result.lower() or '"dbo"' in result

    def test_generate_procedure_create_statement_with_parameters(self):
        """Test generating CREATE PROCEDURE with parameters."""
        generator = SQLServerSqlGenerator()
        from core.sql_model.procedure import Parameter

        param = Parameter(name="id", data_type="INT")
        procedure = Procedure(
            name="proc_test", parameters=[param], body="BEGIN SELECT @id END", dialect="sqlserver"
        )
        result = generator._generate_procedure_create_statement(procedure)
        assert "@id" in result or "id" in result.lower()
        assert "INT" in result.upper()

    def test_generate_procedure_create_statement_function(self):
        """Test generating CREATE FUNCTION statement."""
        generator = SQLServerSqlGenerator()
        function = Procedure(
            name="func_test",
            body="RETURN 1",
            is_function=True,
            return_type="INT",
            dialect="sqlserver",
        )
        result = generator._generate_procedure_create_statement(function)
        assert "CREATE FUNCTION" in result.upper()
        assert "RETURNS INT" in result.upper()

    def test_generate_procedure_create_statement_system_function(self):
        """Test skipping system functions."""
        generator = SQLServerSqlGenerator()
        function = Procedure(name="<", is_function=True, dialect="sqlserver")
        result = generator._generate_procedure_create_statement(function)
        assert result == ""


@pytest.mark.unit
class TestSQLServerSqlGeneratorSynonymCreate:
    """Tests for _generate_synonym_create_statement method."""

    def test_generate_synonym_create_statement_simple(self):
        """Test generating simple CREATE SYNONYM statement."""
        generator = SQLServerSqlGenerator()
        synonym = Synonym(name="syn_test", target_object="users", dialect="sqlserver")
        result = generator._generate_synonym_create_statement(synonym)
        assert "CREATE SYNONYM" in result.upper()
        assert "syn_test" in result.lower()
        assert "FOR" in result.upper()

    def test_generate_synonym_create_statement_with_schema(self):
        """Test generating CREATE SYNONYM with schema."""
        generator = SQLServerSqlGenerator()
        synonym = Synonym(name="syn_test", schema="dbo", target_object="users", dialect="sqlserver")
        result = generator._generate_synonym_create_statement(synonym)
        assert "dbo" in result.lower() or '"dbo"' in result


@pytest.mark.unit
class TestSQLServerSqlGeneratorSequenceCreate:
    """Tests for _generate_sequence_create_statement method."""

    def test_generate_sequence_create_statement_simple(self):
        """Test generating simple CREATE SEQUENCE statement."""
        generator = SQLServerSqlGenerator()
        sequence = Sequence(name="seq_id", dialect="sqlserver")
        result = generator._generate_sequence_create_statement(sequence)
        assert "CREATE SEQUENCE" in result.upper()
        assert "seq_id" in result.lower()

    def test_generate_sequence_create_statement_with_start(self):
        """Test generating CREATE SEQUENCE with START WITH."""
        generator = SQLServerSqlGenerator()
        sequence = Sequence(name="seq_id", start_with=100, dialect="sqlserver")
        result = generator._generate_sequence_create_statement(sequence)
        assert "START WITH 100" in result.upper()

    def test_generate_sequence_create_statement_with_increment(self):
        """Test generating CREATE SEQUENCE with INCREMENT BY."""
        generator = SQLServerSqlGenerator()
        sequence = Sequence(name="seq_id", increment_by=2, dialect="sqlserver")
        result = generator._generate_sequence_create_statement(sequence)
        assert "INCREMENT BY 2" in result.upper()

    def test_generate_sequence_create_statement_with_min_max(self):
        """Test generating CREATE SEQUENCE with MINVALUE and MAXVALUE."""
        generator = SQLServerSqlGenerator()
        sequence = Sequence(name="seq_id", min_value=1, max_value=1000, dialect="sqlserver")
        result = generator._generate_sequence_create_statement(sequence)
        assert "MINVALUE 1" in result.upper()
        assert "MAXVALUE 1000" in result.upper()

    def test_generate_sequence_create_statement_with_cycle(self):
        """Test generating CREATE SEQUENCE with CYCLE."""
        generator = SQLServerSqlGenerator()
        sequence = Sequence(name="seq_id", cycle=True, dialect="sqlserver")
        result = generator._generate_sequence_create_statement(sequence)
        assert "CYCLE" in result.upper()

    def test_generate_sequence_create_statement_no_cycle(self):
        """Test generating CREATE SEQUENCE with NO CYCLE."""
        generator = SQLServerSqlGenerator()
        sequence = Sequence(name="seq_id", cycle=False, dialect="sqlserver")
        result = generator._generate_sequence_create_statement(sequence)
        assert "NO CYCLE" in result.upper()

    def test_generate_sequence_create_statement_with_cache(self):
        """Test generating CREATE SEQUENCE with CACHE."""
        generator = SQLServerSqlGenerator()
        sequence = Sequence(name="seq_id", cache=10, dialect="sqlserver")
        result = generator._generate_sequence_create_statement(sequence)
        assert "CACHE 10" in result.upper()


@pytest.mark.unit
class TestSQLServerSqlGeneratorUserDefinedTypeCreate:
    """Tests for _generate_user_defined_type_create_statement method."""

    def test_generate_user_defined_type_create_statement_composite(self):
        """Test generating CREATE TYPE for composite type."""
        generator = SQLServerSqlGenerator()
        udt = UserDefinedType(
            name="address_type",
            type_category="COMPOSITE",
            attributes=[
                {"name": "street", "type": "VARCHAR(100)"},
                {"name": "city", "type": "VARCHAR(50)"},
            ],
            dialect="sqlserver",
        )
        result = generator._generate_user_defined_type_create_statement(udt)
        assert "CREATE TYPE" in result.upper()
        assert "AS TABLE" in result.upper()
        assert "street" in result.lower()
        assert "city" in result.lower()

    def test_generate_user_defined_type_create_statement_enum(self):
        """Test generating CREATE TYPE for ENUM type."""
        generator = SQLServerSqlGenerator()
        udt = UserDefinedType(
            name="status_enum",
            type_category="ENUM",
            enum_values=["active", "inactive"],
            dialect="sqlserver",
        )
        result = generator._generate_user_defined_type_create_statement(udt)
        assert "CREATE TYPE" in result.upper()
        assert "FROM VARCHAR" in result.upper()
        assert "active" in result.lower()
        assert "inactive" in result.lower()

    def test_generate_user_defined_type_create_statement_distinct(self):
        """Test generating CREATE TYPE for distinct type."""
        generator = SQLServerSqlGenerator()
        udt = UserDefinedType(
            name="status_type",
            type_category="DISTINCT",
            base_type="VARCHAR(50)",
            dialect="sqlserver",
        )
        result = generator._generate_user_defined_type_create_statement(udt)
        assert "CREATE TYPE" in result.upper()
        assert "FROM VARCHAR(50)" in result.upper()

    def test_generate_user_defined_type_create_statement_with_definition(self):
        """Test generating CREATE TYPE with definition."""
        generator = SQLServerSqlGenerator()
        udt = UserDefinedType(
            name="custom_type",
            type_category="DISTINCT",
            definition="VARCHAR(100)",
            dialect="sqlserver",
        )
        result = generator._generate_user_defined_type_create_statement(udt)
        assert "CREATE TYPE" in result.upper()
        assert "FROM VARCHAR(100)" in result.upper()

    def test_generate_user_defined_type_create_statement_fallback(self):
        """Test generating CREATE TYPE fallback."""
        generator = SQLServerSqlGenerator()
        udt = UserDefinedType(name="custom_type", type_category="UNKNOWN", dialect="sqlserver")
        result = generator._generate_user_defined_type_create_statement(udt)
        assert "CREATE TYPE" in result.upper()
        assert "custom_type" in result.lower()


@pytest.mark.unit
class TestSQLServerSqlGeneratorTriggerCreate:
    """Tests for _generate_trigger_create_statement method."""

    def test_generate_trigger_create_statement_with_definition(self):
        """Test generating CREATE TRIGGER from definition."""
        generator = SQLServerSqlGenerator()
        trigger = Trigger(
            name="trg_insert",
            table_name="users",
            events=["INSERT"],
            definition="CREATE TRIGGER trg_insert ON users FOR INSERT AS BEGIN SELECT 1 END",
            dialect="sqlserver",
        )
        result = generator._generate_trigger_create_statement(trigger)
        assert "CREATE TRIGGER" in result.upper()

    def test_generate_trigger_create_statement_simple(self):
        """Test generating simple CREATE TRIGGER statement."""
        generator = SQLServerSqlGenerator()
        trigger = Trigger(
            name="trg_insert", table_name="users", events=["INSERT"], dialect="sqlserver"
        )
        result = generator._generate_trigger_create_statement(trigger)
        assert "CREATE TRIGGER" in result.upper()
        assert "trg_insert" in result.lower()
        assert "ON" in result.upper()
        assert "users" in result.lower()

    def test_generate_trigger_create_statement_with_timing(self):
        """Test generating CREATE TRIGGER with timing."""
        generator = SQLServerSqlGenerator()
        trigger = Trigger(
            name="trg_insert",
            table_name="users",
            events=["INSERT"],
            timing="AFTER",
            dialect="sqlserver",
        )
        result = generator._generate_trigger_create_statement(trigger)
        assert "AFTER" in result.upper()


@pytest.mark.unit
class TestSQLServerSqlGeneratorBasicCreate:
    """Tests for _generate_basic_create_statement method."""

    def test_generate_basic_create_statement(self):
        """Test generating basic CREATE statement."""
        generator = SQLServerSqlGenerator()
        obj = MagicMock()
        obj.schema = None
        obj.name = "test_obj"
        obj.format_identifier = lambda x: x
        obj.object_type = "UNKNOWN_TYPE"
        result = generator._generate_basic_create_statement(obj)
        assert "CREATE UNKNOWN_TYPE" in result.upper()
        assert "test_obj" in result.lower()

    def test_generate_basic_create_statement_with_schema(self):
        """Test generating basic CREATE statement with schema."""
        generator = SQLServerSqlGenerator()
        obj = MagicMock()
        obj.schema = "dbo"
        obj.name = "test_obj"
        obj.format_identifier = lambda x: x
        obj.object_type = "UNKNOWN_TYPE"
        result = generator._generate_basic_create_statement(obj)
        assert "dbo" in result.lower()
        assert "test_obj" in result.lower()


@pytest.mark.unit
class TestSQLServerCreateDispatch:
    """Test _get_create_dispatch registry for SQL Server."""

    def test_get_create_dispatch_contains_expected_types(self):
        """Verify dispatch contains all 8 SQL Server types."""
        from core.sql_model.index import Index
        from core.sql_model.procedure import Procedure
        from core.sql_model.sequence import Sequence
        from core.sql_model.synonym import Synonym
        from core.sql_model.table import Table
        from core.sql_model.trigger import Trigger
        from core.sql_model.user_defined_type import UserDefinedType
        from core.sql_model.view import View

        generator = SQLServerSqlGenerator()
        dispatch = generator._get_create_dispatch()
        assert View in dispatch
        assert Index in dispatch
        assert Procedure in dispatch
        assert Table in dispatch
        assert Synonym in dispatch
        assert Sequence in dispatch
        assert UserDefinedType in dispatch
        assert Trigger in dispatch
        assert len(dispatch) == 8

    def test_generate_create_statement_dispatches_view(self):
        """generate_create_statement routes View to _generate_view_create_statement."""
        from unittest.mock import patch

        from core.sql_model.view import View

        gen = SQLServerSqlGenerator()
        view = View(name="test_view", dialect="sqlserver")
        with patch.object(
            gen, "_generate_view_create_statement", return_value="SS_VIEW_SQL"
        ) as mock:
            result = gen.generate_create_statement(view)
        mock.assert_called_once_with(view)
        assert result == "SS_VIEW_SQL"

    def test_generate_create_fallback_delegates_to_basic(self):
        """Verify SQL Server fallback delegates to _generate_basic_create_statement."""
        generator = SQLServerSqlGenerator()
        obj = MagicMock()
        obj.schema = "dbo"
        obj.name = "unknown_obj"
        obj.format_identifier = lambda x: x
        obj.object_type = "CUSTOM"
        result = generator._generate_create_fallback(obj)
        assert result == "CREATE CUSTOM dbo.unknown_obj"
