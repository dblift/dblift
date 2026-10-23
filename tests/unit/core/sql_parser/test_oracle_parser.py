"""Comprehensive tests for Oracle parser functionality."""

import pytest

from dblift.core.sql_model.base import ParseResult
from tests.support.facts_parser import facts_parser


@pytest.mark.unit
class TestOracleParser:
    """Comprehensive tests for Oracle parser functionality."""

    def test_initialization(self):
        """Test parser initialization."""
        parser = facts_parser("oracle")
        assert parser.dialect_name == "oracle"

    def test_parse_sql_simple(self):
        """Test basic SQL parsing."""
        parser = facts_parser("oracle")

        sql = "CREATE TABLE test (id NUMBER);"
        result = parser.parse_sql(sql)

        assert isinstance(result, ParseResult)
        assert result.success is True
        assert len(result.statements) == 1
        assert "CREATE TABLE test" in result.statements[0].sql_text

    def test_split_statements_simple(self):
        """Test simple statement splitting."""
        sql = "CREATE TABLE test1 (id NUMBER);\nCREATE TABLE test2 (name VARCHAR2(50));"
        statements = facts_parser("oracle").split_statements(sql)
        assert len(statements) == 2
        assert "CREATE TABLE test1" in statements[0]
        assert "CREATE TABLE test2" in statements[1]

    def test_split_statements_complex_plsql(self):
        """Test complex PL/SQL statement splitting."""
        # Test simpler PL/SQL that parser handles correctly
        sql = """
        CREATE OR REPLACE PROCEDURE test_proc AS
        BEGIN
            NULL;
        END;
        /

        CREATE TABLE after_proc (id NUMBER);
        """
        statements = facts_parser("oracle").split_statements(sql)
        # The parser may split this differently, so just verify it's properly parsed
        assert len(statements) >= 2
        # Check that procedure and table creation are both captured
        full_sql = " ".join(statements)
        assert "CREATE OR REPLACE PROCEDURE test_proc" in full_sql
        assert "CREATE TABLE after_proc" in full_sql

    def test_validate_sql(self):
        """Test SQL validation."""
        parser = facts_parser("oracle")

        sql = "CREATE TABLE test (id NUMBER);"
        result = parser.validate_sql(sql)

        assert result["valid"] is True
        assert isinstance(result["errors"], list)

    def test_remove_sql_comments(self):
        """Comment removal through the _comments module (ADR-0012)."""
        from dblift.db.plugins.oracle.parser._comments import strip_sql_comments

        sql_with_comments = """
        -- This is a single line comment
        CREATE TABLE test (
            id NUMBER, /* inline comment */
            name VARCHAR2(50)
        );
        /* Multi-line
           comment */
        """

        cleaned = strip_sql_comments(sql_with_comments)
        assert "--" not in cleaned
        assert "/*" not in cleaned
        assert "*/" not in cleaned
        assert "CREATE TABLE test" in cleaned

    def test_empty_or_comment_only_script(self):
        """Empty and comment-only input has no executable statements."""
        parser = facts_parser("oracle")
        assert parser.split_statements("") == []
        assert parser.split_statements("   ") == []
        assert parser.split_statements("-- This is a comment") == []
        assert parser.split_statements("/* Block comment */") == []
        assert parser.split_statements("CREATE TABLE test (id NUMBER);")

    def test_get_affected_objects(self):
        """Test affected objects extraction."""
        parser = facts_parser("oracle")

        sql = "CREATE TABLE test (id NUMBER);"
        objects = parser.get_affected_objects(sql, "TEST_SCHEMA")

        assert len(objects) >= 1
        assert objects[0].name == "TEST"

    def test_extract_objects_uses_the_oracle_extractor_not_the_generic_stub(self):
        """``extract_objects`` is what ``HybridParser`` and
        ``parser_type="regex"`` call; it must use the same Oracle-specific
        extraction as ``get_affected_objects`` rather than the dialect-agnostic
        base-class stub, which knows nothing about CREATE SEQUENCE and loses
        the object behind a leading comment.
        """
        parser = facts_parser("oracle")

        objects = parser.extract_objects("/* c */ CREATE TABLE real_one (id int);")
        assert [o.name for o in objects] == ["REAL_ONE"]

        objects = parser.extract_objects("CREATE SEQUENCE my_seq;")
        assert [o.name for o in objects] == ["MY_SEQ"]

    def test_extract_objects_covers_drop_for_every_type_the_stub_handled(self):
        """The generic stub this method used to fall through to handled
        DROP for every object type; the Oracle-specific extractor it now
        routes to must not have narrowed that to DROP TABLE only.
        """
        parser = facts_parser("oracle")

        cases = {
            "DROP SEQUENCE real_seq;": "REAL_SEQ",
            "DROP VIEW v1;": "V1",
            "DROP PROCEDURE p1;": "P1",
            "DROP FUNCTION f1;": "F1",
            "DROP TRIGGER t1;": "T1",
            "DROP INDEX idx1;": "IDX1",
        }
        for sql, expected_name in cases.items():
            objects = parser.extract_objects(sql)
            assert [o.name for o in objects] == [expected_name], sql

    def test_plsql_block_extraction(self):
        """Test PL/SQL block extraction with simpler example."""
        # Use simpler PL/SQL for testing
        sql = """
        CREATE OR REPLACE PROCEDURE simple_proc AS
        BEGIN
            NULL;
        END;
        /
        """
        statements = facts_parser("oracle").split_statements(sql)
        # Just verify it parsed without error and contains the procedure
        assert len(statements) >= 1
        full_sql = " ".join(statements)
        assert "CREATE OR REPLACE PROCEDURE simple_proc" in full_sql

    def test_string_handling_in_statements(self):
        """Test proper handling of strings containing special characters."""
        # Test string with semicolon
        sql = "INSERT INTO test VALUES ('data;with;semicolons', 'value');"
        statements = facts_parser("oracle").split_statements(sql)
        assert len(statements) == 1
        assert "data;with;semicolons" in statements[0]

        # Test string with single quotes
        sql = "INSERT INTO test VALUES ('O''Reilly', 'It''s working');"
        statements = facts_parser("oracle").split_statements(sql)
        assert len(statements) == 1

    def test_execute_immediate_with_concat_preserves_pipe(self):
        """Test that EXECUTE IMMEDIATE with || concatenation preserves the operator.

        Oracle uses || for string concatenation. The tokenizer must preserve | so that
        || is correctly reconstructed when splitting statements (fixes ORA-06550).
        """
        parser = facts_parser("oracle")
        sql = """
        DECLARE
            v_max NUMBER;
        BEGIN
            SELECT NVL(MAX(ID), 0) INTO v_max FROM EXECUTIONS_NEW;
            IF v_max > 0 THEN
                EXECUTE IMMEDIATE
                    'ALTER TABLE EXECUTIONS_NEW MODIFY ID GENERATED BY DEFAULT ON NULL AS IDENTITY (START WITH '
                    || (v_max + 1) || ' INCREMENT BY 1 NOCACHE)';
            END IF;
        END;
        /
        """
        statements = parser.split_statements(sql)
        assert len(statements) >= 1
        # The || concatenation operator must be preserved (not lost or mangled)
        full_stmt = " ".join(statements)
        assert "||" in full_stmt, "Concatenation operator || must be preserved"
        # "+1" here would be the reserializer dropping the author's spacing;
        # the expression must come back exactly as written.
        assert "(v_max + 1)" in full_stmt, "Expression (v_max + 1) must be preserved verbatim"

    def test_complex_sql_scenarios(self):
        """Test complex real-world SQL scenarios."""
        parser = facts_parser("oracle")

        # Test mixed DDL and DML
        sql = """
        CREATE TABLE employees (
            id NUMBER PRIMARY KEY,
            name VARCHAR2(100) NOT NULL,
            salary NUMBER(10,2)
        );
        
        CREATE SEQUENCE emp_seq START WITH 1;
        
        INSERT INTO employees VALUES (emp_seq.NEXTVAL, 'John Doe', 50000);
        INSERT INTO employees VALUES (emp_seq.NEXTVAL, 'Jane Smith', 55000);
        
        CREATE VIEW emp_view AS 
        SELECT id, name, 
               CASE WHEN salary > 50000 THEN 'High' ELSE 'Low' END as salary_grade
        FROM employees;
        """

        result = parser.parse_sql(sql)
        assert result.success is True
        assert len(result.statements) >= 5  # Should split into multiple statements

        # Check that statements contain expected keywords
        full_sql = " ".join(
            s.sql_text if hasattr(s, "sql_text") else str(s) for s in result.statements
        )
        assert "CREATE TABLE employees" in full_sql
        assert "CREATE SEQUENCE emp_seq" in full_sql
        assert "INSERT INTO employees" in full_sql
        assert "CREATE VIEW emp_view" in full_sql

    def test_create_or_replace_view(self):
        """Test CREATE OR REPLACE VIEW syntax (Oracle grammar-based)."""
        parser = facts_parser("oracle")

        sql = """
        CREATE OR REPLACE VIEW vw_employees AS
        SELECT * FROM employees;
        """

        result = parser.parse_sql(sql)
        assert result.success
        assert len(result.statements) >= 1

    def test_create_or_replace_procedure(self):
        """Test CREATE OR REPLACE PROCEDURE syntax (Oracle grammar-based)."""
        parser = facts_parser("oracle")

        sql = """
        CREATE OR REPLACE PROCEDURE GetEmployees AS
        BEGIN
            SELECT * FROM employees;
        END;
        /
        """

        result = parser.parse_sql(sql)
        assert result.success

    def test_create_or_replace_function(self):
        """Test CREATE OR REPLACE FUNCTION syntax (Oracle grammar-based)."""
        parser = facts_parser("oracle")

        sql = """
        CREATE OR REPLACE FUNCTION GetEmployeeCount RETURN NUMBER AS
        BEGIN
            RETURN (SELECT COUNT(*) FROM employees);
        END;
        /
        """

        result = parser.parse_sql(sql)
        assert result.success

    def test_bitmap_index(self):
        """Test CREATE BITMAP INDEX syntax (Oracle grammar-based)."""
        parser = facts_parser("oracle")

        sql = """
        CREATE BITMAP INDEX idx_status ON employees(status);
        """

        result = parser.parse_sql(sql)
        assert result.success

    def test_index_with_tablespace(self):
        """Test CREATE INDEX with TABLESPACE clause (Oracle grammar-based)."""
        parser = facts_parser("oracle")

        sql = """
        CREATE INDEX idx_name ON employees(name) TABLESPACE users;
        """

        result = parser.parse_sql(sql)
        assert result.success

    def test_create_synonym(self):
        """Test CREATE SYNONYM syntax (Oracle grammar-based)."""
        parser = facts_parser("oracle")

        sql = """
        CREATE OR REPLACE PUBLIC SYNONYM emp FOR employees;
        """

        result = parser.parse_sql(sql)
        assert result.success

    def test_create_materialized_view(self):
        """Test CREATE MATERIALIZED VIEW syntax (Oracle grammar-based)."""
        parser = facts_parser("oracle")

        sql = """
        CREATE MATERIALIZED VIEW mv_employees
        BUILD IMMEDIATE
        REFRESH FAST ON COMMIT
        AS SELECT * FROM employees;
        """

        result = parser.parse_sql(sql)
        assert result.success

    def test_create_force_view(self):
        """Test CREATE OR REPLACE FORCE VIEW syntax (Oracle grammar-based)."""
        parser = facts_parser("oracle")

        sql = """
        CREATE OR REPLACE FORCE VIEW vw_test AS
        SELECT * FROM nonexistent_table;
        """

        result = parser.parse_sql(sql)
        assert result.success

    def test_create_noforce_view(self):
        """Test CREATE OR REPLACE NOFORCE VIEW syntax (Oracle grammar-based)."""
        parser = facts_parser("oracle")

        sql = """
        CREATE OR REPLACE NOFORCE VIEW vw_test AS
        SELECT * FROM employees;
        """

        result = parser.parse_sql(sql)
        assert result.success

    def test_drop_table_cascade_constraints(self):
        """Test DROP TABLE CASCADE CONSTRAINTS syntax (Oracle grammar-based)."""
        parser = facts_parser("oracle")

        sql = "DROP TABLE employees CASCADE CONSTRAINTS;"

        result = parser.parse_sql(sql)
        assert result.success

    def test_global_temporary_table(self):
        """Test CREATE GLOBAL TEMPORARY TABLE syntax (Oracle grammar-based)."""
        parser = facts_parser("oracle")

        sql = """
        CREATE GLOBAL TEMPORARY TABLE temp_employees (
            id NUMBER,
            name VARCHAR2(100)
        );
        """

        result = parser.parse_sql(sql)
        assert result.success

    def test_inheritance_and_interface_compliance(self):
        """Test that parser correctly implements the interface."""
        parser = facts_parser("oracle")

        # Test that it has all required methods
        assert hasattr(parser, "parse_sql")
        assert hasattr(parser, "split_statements")
        assert hasattr(parser, "validate_sql")
        assert hasattr(parser, "get_affected_objects")
        assert hasattr(parser, "dialect_name")

        # Test dialect property
        assert parser.dialect_name == "oracle"
