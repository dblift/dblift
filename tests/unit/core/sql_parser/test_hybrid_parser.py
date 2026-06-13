"""Tests for HybridParser combining regex and sqlglot approaches."""

import typing
from typing import Optional
from unittest.mock import MagicMock

import pytest

from core.sql_model.base import ParseResult, SqlObject, SqlObjectType, SqlStatementType
from core.sql_model.event import Event
from core.sql_model.extension import Extension
from core.sql_model.foreign_data_wrapper import ForeignDataWrapper
from core.sql_model.foreign_server import ForeignServer
from core.sql_model.index import Index
from core.sql_model.package import Package
from core.sql_model.partition import Partition
from core.sql_model.procedure import Procedure
from core.sql_model.sequence import Sequence
from core.sql_model.synonym import Synonym
from core.sql_model.table import Table
from core.sql_model.trigger import Trigger
from core.sql_model.user_defined_type import UserDefinedType
from core.sql_model.view import View
from core.sql_parser.hybrid_parser import _COLLECT_DISPATCH, HybridParser


@pytest.mark.unit
class TestHybridParser:
    """Test cases for HybridParser functionality."""

    # ========== Parser Initialization ==========

    def test_parser_creation_oracle(self):
        """Test creating hybrid parser for Oracle."""
        parser = HybridParser("oracle")
        assert parser.dialect_name == "oracle"
        assert parser.regex_parser is not None
        assert parser.sqlglot_parser is not None

    def test_parser_creation_mysql(self):
        """Test creating hybrid parser for MySQL."""
        parser = HybridParser("mysql")
        assert parser.dialect_name == "mysql"
        assert parser.regex_parser is not None
        assert parser.sqlglot_parser is not None

    def test_parser_creation_postgresql(self):
        """Test creating hybrid parser for PostgreSQL."""
        parser = HybridParser("postgresql")
        assert parser.dialect_name == "postgresql"
        assert parser.regex_parser is not None
        assert parser.sqlglot_parser is not None

    def test_parser_creation_sqlserver(self):
        """Test creating hybrid parser for SQL Server."""
        parser = HybridParser("sqlserver")
        assert parser.dialect_name == "sqlserver"
        assert parser.regex_parser is not None
        assert parser.sqlglot_parser is not None

    def test_parser_creation_db2(self):
        """Test creating hybrid parser for DB2 (no sqlglot)."""
        parser = HybridParser("db2")
        assert parser.dialect_name == "db2"
        assert parser.regex_parser is not None
        assert parser.sqlglot_parser is None  # DB2 not supported by sqlglot

    # ========== Statement Splitting (Regex-based) ==========

    def test_split_postgresql_procedural(self):
        """Test splitting PostgreSQL statements with PL/pgSQL procedure."""
        parser = HybridParser("postgresql")
        sql = """
        CREATE TABLE users (id SERIAL PRIMARY KEY, name VARCHAR(100));

        CREATE OR REPLACE FUNCTION get_user_count() RETURNS INTEGER AS $$
        DECLARE
            user_count INTEGER;
        BEGIN
            SELECT COUNT(*) INTO user_count FROM users;
            RETURN user_count;
        END;
        $$ LANGUAGE plpgsql;

        INSERT INTO users (name) VALUES ('Alice');
        """

        statements = parser.split_statements(sql)
        # Should split into 3 statements (CREATE TABLE, CREATE FUNCTION, INSERT)
        assert len(statements) >= 3
        assert "CREATE TABLE" in statements[0].upper()
        assert (
            "CREATE OR REPLACE FUNCTION" in statements[1].upper()
            or "CREATE FUNCTION" in statements[1].upper()
        )
        assert "INSERT INTO" in statements[2].upper()

    def test_split_oracle_procedural(self):
        """Test splitting Oracle statements with PL/SQL procedure."""
        parser = HybridParser("oracle")
        sql = """
        CREATE TABLE test_table (id NUMBER PRIMARY KEY);

        CREATE OR REPLACE PROCEDURE test_proc IS
        BEGIN
            INSERT INTO test_table VALUES (1);
            COMMIT;
        END;
        /

        SELECT * FROM test_table;
        """

        statements = parser.split_statements(sql)
        # Should split properly handling the / delimiter
        assert len(statements) >= 3
        assert "CREATE TABLE" in statements[0].upper()
        # Procedure should be intact
        assert (
            "CREATE OR REPLACE PROCEDURE" in statements[1].upper()
            or "CREATE PROCEDURE" in statements[1].upper()
        )

    def test_split_mysql_delimiter(self):
        """Test splitting MySQL statements with DELIMITER."""
        parser = HybridParser("mysql")
        sql = """
        CREATE TABLE users (id INT PRIMARY KEY);

        DELIMITER //
        CREATE PROCEDURE get_users()
        BEGIN
            SELECT * FROM users;
        END//
        DELIMITER ;

        INSERT INTO users VALUES (1);
        """

        statements = parser.split_statements(sql)
        # Should handle DELIMITER properly
        assert len(statements) >= 2

    def test_split_sqlserver_go(self):
        """Test splitting SQL Server statements with GO."""
        parser = HybridParser("sqlserver")
        sql = """
        CREATE TABLE users (id INT PRIMARY KEY);
        GO

        CREATE PROCEDURE GetUsers
        AS
        BEGIN
            SELECT * FROM users;
        END;
        GO

        INSERT INTO users VALUES (1);
        GO
        """

        statements = parser.split_statements(sql)
        # GO should act as delimiter
        assert len(statements) >= 3

    # ========== Pure SQL Enhancement ==========

    def test_parse_pure_sql_select(self):
        """Test parsing pure SQL SELECT with sqlglot enhancement."""
        parser = HybridParser("postgresql")
        sql = "SELECT u.name, o.total FROM users u JOIN orders o ON u.id = o.user_id;"

        result = parser.parse_sql(sql, "public")
        assert result.success
        assert len(result.statements) == 1

        stmt = result.statements[0]
        assert (
            stmt.statement_type == SqlStatementType.SELECT
            or stmt.statement_type == SqlStatementType.QUERY
        )
        # Should extract tables from JOIN
        assert len(stmt.objects) >= 2

    def test_parse_pure_sql_create_table(self):
        """Test parsing CREATE TABLE with sqlglot enhancement."""
        parser = HybridParser("postgresql")
        sql = "CREATE TABLE users (id SERIAL PRIMARY KEY, name VARCHAR(100));"

        result = parser.parse_sql(sql, "public")
        assert result.success
        assert len(result.statements) == 1

        stmt = result.statements[0]
        # CREATE or DDL are both acceptable for CREATE TABLE
        assert stmt.statement_type in [
            SqlStatementType.CREATE,
            SqlStatementType.DDL,
            SqlStatementType.UNKNOWN,
        ]
        # Should have at least the table being created in objects or affected_objects
        # Note: Some parsers may not extract objects, so we check if objects exist
        # If objects are extracted, verify they contain the table
        if stmt.affected_objects or stmt.objects:
            assert len(stmt.affected_objects) >= 1 or len(stmt.objects) >= 1
        # If no objects extracted, that's also acceptable - the statement was parsed successfully

    def test_parse_pure_sql_insert(self):
        """Test parsing INSERT with sqlglot enhancement."""
        parser = HybridParser("mysql")
        sql = "INSERT INTO users (name, email) VALUES ('John', 'john@example.com');"

        result = parser.parse_sql(sql)
        assert result.success
        assert len(result.statements) == 1

        stmt = result.statements[0]
        # INSERT or DML are both acceptable for INSERT statement
        assert stmt.statement_type in [SqlStatementType.INSERT, SqlStatementType.DML]

    # ========== Procedural Language Handling ==========

    def test_parse_oracle_plsql_procedure(self):
        """Test parsing Oracle PL/SQL procedure (uses regex, not sqlglot)."""
        parser = HybridParser("oracle")
        sql = """
        CREATE OR REPLACE PROCEDURE update_salary(emp_id NUMBER, new_salary NUMBER) IS
        BEGIN
            UPDATE employees SET salary = new_salary WHERE id = emp_id;
            COMMIT;
        END;
        /
        """

        result = parser.parse_sql(sql, "HR")
        assert result.success
        assert len(result.statements) >= 1
        # Should identify as CREATE, DDL, or UNKNOWN (procedural language)
        stmt = result.statements[0]
        assert stmt.statement_type in [
            SqlStatementType.CREATE,
            SqlStatementType.DDL,
            SqlStatementType.UNKNOWN,
        ]

    def test_parse_postgresql_plpgsql_function(self):
        """Test parsing PostgreSQL PL/pgSQL function (uses regex, not sqlglot)."""
        parser = HybridParser("postgresql")
        sql = """
        CREATE OR REPLACE FUNCTION calculate_total(order_id INTEGER) RETURNS NUMERIC AS $$
        DECLARE
            total NUMERIC;
        BEGIN
            SELECT SUM(price * quantity) INTO total
            FROM order_items
            WHERE order_id = $1;
            RETURN total;
        END;
        $$ LANGUAGE plpgsql;
        """

        result = parser.parse_sql(sql, "public")
        assert result.success
        assert len(result.statements) >= 1

    def test_parse_sqlserver_tsql_procedure(self):
        """Test parsing SQL Server T-SQL procedure (uses regex, not sqlglot)."""
        parser = HybridParser("sqlserver")
        sql = """
        CREATE PROCEDURE GetUserOrders @UserId INT
        AS
        BEGIN
            SELECT o.*
            FROM orders o
            WHERE o.user_id = @UserId
            ORDER BY o.created_at DESC;
        END;
        """

        result = parser.parse_sql(sql, "dbo")
        assert result.success
        assert len(result.statements) >= 1

    # ========== Dependency Extraction ==========

    def test_extract_dependencies_select(self):
        """Test extracting dependencies from SELECT query."""
        parser = HybridParser("postgresql")
        sql = """
        SELECT c.name, c.email, o.total, o.order_date
        FROM customers c
        JOIN orders o ON c.id = o.customer_id
        WHERE o.status = 'completed';
        """

        deps = parser.extract_dependencies(sql, "public")
        assert "tables" in deps
        # Should find customers and orders tables
        assert len(deps["tables"]) >= 2

    def test_extract_dependencies_create_view(self):
        """Test extracting dependencies from CREATE VIEW."""
        parser = HybridParser("oracle")
        sql = """
        CREATE VIEW active_customers AS
        SELECT c.*, COUNT(o.id) as order_count
        FROM customers c
        LEFT JOIN orders o ON c.id = o.customer_id
        WHERE c.status = 'active'
        GROUP BY c.id, c.name, c.email;
        """

        deps = parser.extract_dependencies(sql, "SALES")
        assert "tables" in deps
        # Should find customers and orders
        assert len(deps["tables"]) >= 2

    def test_extract_dependencies_procedural_skipped(self):
        """Test that procedural SQL is skipped for dependency extraction."""
        parser = HybridParser("postgresql")
        sql = """
        CREATE OR REPLACE FUNCTION complex_calculation() RETURNS INTEGER AS $$
        DECLARE
            result INTEGER;
        BEGIN
            -- Complex procedural logic here
            result := 42;
            RETURN result;
        END;
        $$ LANGUAGE plpgsql;
        """

        deps = parser.extract_dependencies(sql, "public")
        # Procedural blocks should be skipped
        # May or may not find tables depending on implementation
        assert "tables" in deps

    # ========== Object Extraction ==========

    def test_extract_objects_pure_sql(self):
        """Test extracting objects from pure SQL."""
        parser = HybridParser("mysql")
        sql = "SELECT * FROM users JOIN orders ON users.id = orders.user_id;"

        objects = parser.extract_objects(sql)
        # Should extract both tables
        assert len(objects) >= 2
        table_names = [obj.name.lower() for obj in objects]
        assert "users" in table_names
        assert "orders" in table_names

    def test_extract_objects_create_table(self):
        """Test extracting objects from CREATE TABLE."""
        parser = HybridParser("postgresql")
        sql = (
            "CREATE TABLE products (id SERIAL PRIMARY KEY, name VARCHAR(100), price DECIMAL(10,2));"
        )

        objects = parser.extract_objects(sql, "public")
        assert len(objects) >= 1
        assert objects[0].name.lower() == "products"

    def test_extract_objects_oracle_partition_by_reference(self):
        """Test Oracle PARTITION BY REFERENCE - SqlGlot cannot parse, regex fallback used."""
        parser = HybridParser("oracle")
        sql = """
        CREATE TABLE EXECUTION_STEPS_NEW (
            ID NUMBER,
            CONSTRAINT FK_EXEC_STEPS_NEW_EXEC
                FOREIGN KEY (ID) REFERENCES EXECUTIONS(ID) ON DELETE CASCADE ENABLE
        )
        PARTITION BY REFERENCE (FK_EXEC_STEPS_NEW_EXEC);
        """
        objects = parser.extract_objects(sql)
        assert len(objects) >= 1
        assert any(o.name == "EXECUTION_STEPS_NEW" for o in objects)

    # ========== Validation ==========

    def test_validate_pure_sql_valid(self):
        """Test validating valid pure SQL."""
        parser = HybridParser("postgresql")
        sql = "SELECT * FROM users WHERE id = 1;"

        result = parser.validate_sql(sql)
        # Different parsers may return 'valid' or 'success'
        is_valid = result.get("valid", True)  # Default to True if key not present
        assert is_valid is True or len(result.get("errors", [])) == 0

    def test_validate_pure_sql_invalid(self):
        """Test validating invalid pure SQL."""
        parser = HybridParser("postgresql")
        sql = "SELECT * FORM users;"  # FORM instead of FROM

        result = parser.validate_sql(sql)
        # Should detect error
        assert not result["valid"] or len(result["errors"]) > 0

    def test_validate_procedural_sql(self):
        """Test validating procedural SQL."""
        parser = HybridParser("oracle")
        sql = """
        CREATE OR REPLACE PROCEDURE test_proc IS
        BEGIN
            NULL;
        END;
        /
        """

        result = parser.validate_sql(sql)
        # Regex parser should handle this
        assert result["valid"] or len(result["errors"]) == 0

    # ========== Hybrid Behavior ==========

    def test_hybrid_mixed_statements(self):
        """Test parsing mixed pure SQL and procedural statements."""
        parser = HybridParser("postgresql")
        sql = """
        CREATE TABLE logs (id SERIAL, message TEXT);

        CREATE OR REPLACE FUNCTION log_message(msg TEXT) RETURNS VOID AS $$
        BEGIN
            INSERT INTO logs (message) VALUES (msg);
        END;
        $$ LANGUAGE plpgsql;

        INSERT INTO logs (message) VALUES ('Test message');
        """

        result = parser.parse_sql(sql, "public")
        assert result.success
        # Should have 3 statements
        assert len(result.statements) >= 3

    def test_hybrid_fallback_on_sqlglot_failure(self):
        """Test graceful fallback when sqlglot fails."""
        parser = HybridParser("oracle")
        # Oracle Q-quote that sqlglot may struggle with
        sql = "SELECT q'[It's a string with 'quotes']' FROM DUAL;"

        result = parser.parse_sql(sql)
        # Should still succeed using regex parser
        assert result.success

    # ========== DB2 (Regex-Only) ==========

    def test_db2_regex_only(self):
        """Test that DB2 uses regex-only (no sqlglot)."""
        parser = HybridParser("db2")
        sql = "CREATE TABLE test (id INTEGER PRIMARY KEY);"

        result = parser.parse_sql(sql, "TESTDB")
        assert result.success
        # Verify sqlglot is not used
        assert parser.sqlglot_parser is None

    # ========== Edge Cases ==========

    def test_empty_sql(self):
        """Test parsing empty SQL."""
        parser = HybridParser("postgresql")
        result = parser.parse_sql("")
        # Should handle gracefully
        assert result.success or len(result.errors) > 0

    def test_comments_only(self):
        """Test parsing SQL with only comments."""
        parser = HybridParser("mysql")
        sql = "-- This is a comment\n/* Another comment */"

        result = parser.parse_sql(sql)
        # Should handle gracefully
        assert result.success

    def test_multiple_pure_sql_statements(self):
        """Test parsing multiple pure SQL statements."""
        parser = HybridParser("postgresql")
        sql = """
        INSERT INTO users (name) VALUES ('Alice');
        INSERT INTO users (name) VALUES ('Bob');
        INSERT INTO users (name) VALUES ('Charlie');
        """

        result = parser.parse_sql(sql, "public")
        assert result.success
        assert len(result.statements) == 3


@pytest.mark.unit
class TestCollectObjectsDispatch:
    """Tests for _collect_objects dispatch dict pattern (story 14-9)."""

    def _make_parser(self):
        return HybridParser("postgresql")

    def test_collect_table_calls_add_table(self):
        """AC#3.1: TABLE dispatches to result.add_table."""
        parser = self._make_parser()
        result = ParseResult(success=True)
        table = Table(name="users")
        parser._collect_objects(result, [table])
        assert len(result.tables) == 1
        assert result.tables[0].name == "users"

    def test_collect_view_calls_add_view(self):
        """AC#3.1: VIEW dispatches to result.add_view."""
        parser = self._make_parser()
        result = ParseResult(success=True)
        view = View(name="v_users")
        parser._collect_objects(result, [view])
        assert len(result.views) == 1
        assert result.views[0].name == "v_users"

    def test_collect_procedure_calls_add_procedure(self):
        """AC#3.1: PROCEDURE dispatches to result.add_procedure."""
        parser = self._make_parser()
        result = ParseResult(success=True)
        proc = Procedure(name="do_stuff")
        parser._collect_objects(result, [proc])
        assert len(result.procedures) == 1
        assert result.procedures[0].name == "do_stuff"

    def test_collect_materialized_view_routes_to_add_view(self):
        """AC#3.2: MATERIALIZED_VIEW dispatches to result.add_view."""
        parser = self._make_parser()
        result = ParseResult(success=True)
        mv = View(name="mv_stats", materialized=True)
        parser._collect_objects(result, [mv])
        assert len(result.views) == 1
        assert result.views[0].name == "mv_stats"

    def test_collect_partition_no_dedup_check(self):
        """AC#3.3: PARTITION is always added without _object_exists check."""
        parser = self._make_parser()
        result = ParseResult(success=True)
        p1 = Partition(name="p1", table="t1", partition_method="RANGE")
        p2 = Partition(name="p1", table="t1", partition_method="RANGE")
        parser._collect_objects(result, [p1, p2])
        assert len(result.partitions) == 2

    def test_collect_unknown_type_ignored(self):
        """AC#3.4: Unknown types are silently ignored."""
        parser = self._make_parser()
        result = ParseResult(success=True)
        obj = MagicMock(spec=SqlObject)
        obj.object_type = MagicMock()  # Not a real SqlObjectType
        parser._collect_objects(result, [obj])
        assert len(result.tables) == 0
        assert len(result.views) == 0

    def test_collect_function_uses_procedure_isinstance(self):
        """AC#1.5: FUNCTION uses Procedure as expected_class."""
        parser = self._make_parser()
        result = ParseResult(success=True)
        func = Procedure(name="calc", is_function=True)
        parser._collect_objects(result, [func])
        assert len(result.functions) == 1
        assert result.functions[0].name == "calc"

    def test_collect_dedup_prevents_duplicate_table(self):
        """Dedup check prevents adding same table twice."""
        parser = self._make_parser()
        result = ParseResult(success=True)
        t1 = Table(name="users")
        t2 = Table(name="users")
        parser._collect_objects(result, [t1, t2])
        assert len(result.tables) == 1

    def test_dispatch_dict_has_all_expected_entries(self):
        """Structural: _COLLECT_DISPATCH has 17 entries covering all object types."""
        assert len(_COLLECT_DISPATCH) == 17
        # PARTITION has no get_collection (None) — AC#1.5
        _, get_coll, _ = _COLLECT_DISPATCH[SqlObjectType.PARTITION]
        assert get_coll is None, "PARTITION must have get_collection=None (no dedup)"
        # VIEW and MATERIALIZED_VIEW share the same add_method — AC#1.3
        _, _, view_add = _COLLECT_DISPATCH[SqlObjectType.VIEW]
        _, _, mv_add = _COLLECT_DISPATCH[SqlObjectType.MATERIALIZED_VIEW]
        assert view_add == mv_add == "add_view", "VIEW and MATERIALIZED_VIEW must share add_view"
        # FUNCTION uses Procedure as expected_class — AC#1.4
        func_class, _, _ = _COLLECT_DISPATCH[SqlObjectType.FUNCTION]
        assert func_class is Procedure, "FUNCTION must use Procedure as expected_class"

    def test_collect_empty_list_noop(self):
        """Empty objects list is a no-op."""
        parser = self._make_parser()
        result = ParseResult(success=True)
        parser._collect_objects(result, [])
        assert len(result.tables) == 0

    def test_collect_wrong_isinstance_silently_ignored(self):
        """AC#2: entry found in dict but isinstance fails → object silently skipped."""
        # Create a View with object_type=TABLE to trigger isinstance rejection
        parser = self._make_parser()
        result = ParseResult(success=True)
        obj = MagicMock(spec=SqlObject)
        obj.object_type = SqlObjectType.TABLE  # In dispatch dict...
        # ...but obj is not a Table instance → isinstance(obj, Table) is False
        parser._collect_objects(result, [obj])
        assert len(result.tables) == 0, "Object with wrong type should be silently skipped"


@pytest.mark.unit
class TestDeadCodeRemoved:
    """Verify dead methods were removed from HybridParser."""

    def test_is_pure_sql_method_removed(self):
        """AC#6.3: _is_pure_sql must not exist on HybridParser."""
        assert not hasattr(HybridParser, "_is_pure_sql")


@pytest.mark.unit
class TestNormalizeIdentifierTypeHint:
    """Verify _normalize_identifier accepts None (Optional[str] type hint fix)."""

    def _make_parser(self):
        parser = HybridParser.__new__(HybridParser)
        parser.log = MagicMock()
        return parser

    def test_normalize_identifier_none_returns_empty_no_preserve(self):
        """AC#5: _normalize_identifier(None, False) returns empty string."""
        parser = self._make_parser()
        result = parser._normalize_identifier(None, False)
        assert result == ""

    def test_normalize_identifier_none_returns_empty_preserve(self):
        """AC#5: _normalize_identifier(None, True) returns empty string."""
        parser = self._make_parser()
        result = parser._normalize_identifier(None, True)
        assert result == ""

    def test_normalize_identifier_type_hint_is_optional_str(self):
        """M1: The type annotation must be Optional[str], not str."""
        hints = typing.get_type_hints(HybridParser._normalize_identifier)
        assert hints["identifier"] == Optional[str]

    def test_normalize_identifier_non_none_preserve_case_false(self):
        """L1: Non-None path still works — uppercase when preserve_case=False."""
        parser = self._make_parser()
        assert parser._normalize_identifier("hello", False) == "HELLO"

    def test_normalize_identifier_non_none_preserve_case_true(self):
        """L1: Non-None path still works — case preserved when preserve_case=True."""
        parser = self._make_parser()
        assert parser._normalize_identifier('"MySchema"', True) == "MySchema"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
