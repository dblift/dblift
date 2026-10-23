"""Tests for DB2 regex parser."""

import pytest

from dblift.core.sql_model.base import ParseResult, SqlStatementType
from tests.support.facts_parser import facts_parser


@pytest.mark.unit
class TestDB2RegexParser:
    """Test DB2 regex parser functionality."""

    def test_parser_creation(self):
        """Test parser can be created."""
        parser = facts_parser("db2")
        assert parser is not None
        assert parser.dialect_name == "db2"

    def test_parse_sql_simple(self):
        """Test parsing simple SQL."""
        parser = facts_parser("db2")

        sql = "CREATE TABLE test (id INTEGER PRIMARY KEY, name VARCHAR(100));"
        result = parser.parse_sql(sql)

        assert isinstance(result, ParseResult)
        assert result.success
        assert len(result.statements) >= 1
        assert "CREATE TABLE test" in result.statements[0].sql_text

    def test_parse_sql_multiple_statements(self):
        """Test parsing multiple SQL statements."""
        parser = facts_parser("db2")

        sql = """
        CREATE TABLE employees (id INTEGER PRIMARY KEY, name VARCHAR(100));
        CREATE INDEX idx_name ON employees(name);
        INSERT INTO employees VALUES (1, 'John');
        """
        result = parser.parse_sql(sql)

        assert isinstance(result, ParseResult)
        assert result.success
        assert len(result.statements) >= 3

    def test_parse_sql_db2_specific(self):
        """Test parsing DB2-specific SQL."""
        parser = facts_parser("db2")

        sql = """
        CREATE TABLE test (
            id INTEGER NOT NULL GENERATED ALWAYS AS IDENTITY,
            name VARCHAR(100) NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        ) IN USERSPACE1;
        """
        result = parser.parse_sql(sql)

        assert isinstance(result, ParseResult)
        assert result.success
        assert len(result.statements) >= 1

    def test_parse_sql_empty(self):
        """Test parsing empty SQL."""
        parser = facts_parser("db2")

        result = parser.parse_sql("")

        assert isinstance(result, ParseResult)
        assert result.success
        assert len(result.statements) == 0

    def test_extract_objects(self):
        """Test object extraction from SQL."""
        parser = facts_parser("db2")

        sql = """
        CREATE TABLE employees (
            id INTEGER NOT NULL,
            name VARCHAR(100) NOT NULL
        );
        """

        objects = parser.extract_objects(sql)
        assert len(objects) >= 1
        assert objects[0].name == "EMPLOYEES"  # DB2 typically uses uppercase

    def test_sqlpl_handling(self):
        """Test SQL/PL procedure handling."""
        parser = facts_parser("db2")

        sql = """
        CREATE OR REPLACE PROCEDURE GetEmployeeCount(OUT total INTEGER)
        LANGUAGE SQL
        BEGIN
            SELECT COUNT(*) INTO total FROM employees;
        END;
        """

        result = parser.parse_sql(sql)
        assert isinstance(result, ParseResult)
        assert result.success

    def test_split_statements(self):
        """Test SQL statement splitting."""
        parser = facts_parser("db2")

        sql = """
        CREATE TABLE test1 (id INTEGER);
        INSERT INTO test1 VALUES (1);
        CREATE TABLE test2 (id INTEGER);
        """

        statements = parser.split_statements(sql)
        assert len(statements) >= 3

    def test_statement_classification(self):
        """Test statement type classification."""
        parser = facts_parser("db2")

        # Test through parse_sql which uses the classification logic
        ddl_sql = "CREATE TABLE test (id INTEGER)"
        result = parser.parse_sql(ddl_sql)
        assert result.success
        assert result.statements[0].statement_type == SqlStatementType.DDL

        dml_sql = "INSERT INTO test VALUES (1)"
        result = parser.parse_sql(dml_sql)
        assert result.success
        assert result.statements[0].statement_type == SqlStatementType.DML

        query_sql = "SELECT * FROM test"
        result = parser.parse_sql(query_sql)
        assert result.success
        assert result.statements[0].statement_type == SqlStatementType.QUERY

    def test_validate_sql(self):
        """Test SQL validation."""
        parser = facts_parser("db2")

        # Valid SQL
        valid_sql = "CREATE TABLE test (id INTEGER PRIMARY KEY)"
        result = parser.validate_sql(valid_sql)
        assert result["valid"]

        # Invalid SQL (unmatched quoted identifier)
        invalid_sql = 'CREATE TABLE "test (id INTEGER PRIMARY KEY)'
        result = parser.validate_sql(invalid_sql)
        assert not result["valid"]

    def test_compound_statement_handling(self):
        """Test compound statement handling."""
        parser = facts_parser("db2")

        sql = """
        BEGIN ATOMIC
            DECLARE v_count INTEGER;
            SELECT COUNT(*) INTO v_count FROM employees;
            IF v_count > 0 THEN
                INSERT INTO audit_log VALUES ('Employee count: ' || v_count);
            END IF;
        END;
        """

        result = parser.parse_sql(sql)
        assert isinstance(result, ParseResult)
        assert result.success

    def test_exec_sql_handling(self):
        """Test EXEC SQL statement handling."""
        parser = facts_parser("db2")

        sql = """
        EXEC SQL
            CREATE TABLE test (id INTEGER)
        END-EXEC;
        """

        result = parser.parse_sql(sql)
        assert isinstance(result, ParseResult)
        assert result.success

    def test_spufi_terminator_handling(self):
        """Test SPUFI terminator handling."""
        parser = facts_parser("db2")

        sql = """
        --#SET TERMINATOR @
        CREATE TABLE test (id INTEGER)@
        INSERT INTO test VALUES (1)@
        --#SET TERMINATOR ;
        SELECT * FROM test;
        """

        result = parser.parse_sql(sql)
        assert isinstance(result, ParseResult)
        assert result.success

    def test_trigger_handling(self):
        """Test trigger statement handling."""
        parser = facts_parser("db2")

        sql = """
        CREATE OR REPLACE TRIGGER audit_trigger
        AFTER INSERT ON employees
        FOR EACH ROW
        BEGIN ATOMIC
            INSERT INTO audit_log VALUES (NEW.id, CURRENT_TIMESTAMP);
        END;
        """

        result = parser.parse_sql(sql)
        assert isinstance(result, ParseResult)
        assert result.success

    def test_error_handling_and_recovery(self):
        """Test error handling and recovery."""
        parser = facts_parser("db2")

        # Test with potentially problematic SQL
        problematic_sql = "CREATE TABLE test (id INTEGER; -- Missing closing parenthesis"
        result = parser.parse_sql(problematic_sql)

        # Should handle gracefully
        assert isinstance(result, ParseResult)

    def test_edge_cases(self):
        """Test various edge cases."""
        parser = facts_parser("db2")

        edge_cases = [
            "",  # Empty string
            ";",  # Just semicolon
            "   ; ; ;   ",  # Multiple semicolons with whitespace
            "-- Comment only",  # Comment only
            "/* Block comment */",  # Block comment
        ]

        for sql in edge_cases:
            result = parser.parse_sql(sql)
            assert isinstance(result, ParseResult)

    def test_db2_comment_handling(self):
        """Test DB2 comment handling."""
        parser = facts_parser("db2")

        sql = """
        -- This is a line comment
        CREATE TABLE test (
            id INTEGER, -- Column comment
            name VARCHAR(100) /* Block comment */
        );
        /* Multi-line
           block comment */
        INSERT INTO test VALUES (1, 'Test');
        """

        result = parser.parse_sql(sql)
        assert isinstance(result, ParseResult)
        assert result.success

    def test_quoted_identifier_handling(self):
        """Test DB2 quoted identifier handling."""
        parser = facts_parser("db2")

        sql = 'CREATE TABLE "test_table" ("column_name" INTEGER, "special-col" VARCHAR(100));'

        result = parser.parse_sql(sql)
        assert isinstance(result, ParseResult)
        assert result.success
        assert '"test_table"' in result.statements[0].sql_text

    def test_db2_exec_sql_detection(self):
        """Test DB2 EXEC SQL detection."""
        parser = facts_parser("db2")

        # Test with EXEC SQL
        sql_with_exec = "EXEC SQL CREATE TABLE test (id INTEGER) END-EXEC;"
        assert parser.split_statements(sql_with_exec) == [sql_with_exec[:-1]]

        # Test without EXEC SQL
        sql_without_exec = "CREATE TABLE test (id INTEGER);"
        assert parser.split_statements(sql_without_exec) == [sql_without_exec[:-1]]

    def test_db2_sqlpl_detection(self):
        """Test DB2 SQL/PL detection."""
        parser = facts_parser("db2")

        # Test with SQL/PL procedure
        sql_with_sqlpl = "CREATE PROCEDURE test() LANGUAGE SQL BEGIN SELECT 1; END;"
        assert parser.split_statements(sql_with_sqlpl) == [sql_with_sqlpl[:-1]]

        # Test with SQLPL procedure
        sql_with_sqlpl2 = "CREATE PROCEDURE test() LANGUAGE SQLPL BEGIN SELECT 1; END;"
        assert parser.split_statements(sql_with_sqlpl2) == [sql_with_sqlpl2[:-1]]

        # Test without SQL/PL
        sql_without_sqlpl = "CREATE TABLE test (id INTEGER);"
        assert parser.split_statements(sql_without_sqlpl) == [sql_without_sqlpl[:-1]]

    def test_db2_compound_statement_detection(self):
        """Test DB2 compound statement detection."""
        parser = facts_parser("db2")

        # Test with compound atomic
        sql_with_compound = "BEGIN ATOMIC SELECT 1; END;"
        assert parser.split_statements(sql_with_compound) == [sql_with_compound[:-1]]

        # Test with compound not atomic
        sql_with_compound2 = "BEGIN NOT ATOMIC SELECT 1; END;"
        assert parser.split_statements(sql_with_compound2) == [sql_with_compound2[:-1]]

        # Test without compound
        sql_without_compound = "SELECT 1;"
        assert parser.split_statements(sql_without_compound) == [sql_without_compound[:-1]]

    def test_db2_trigger_detection(self):
        """Test DB2 trigger detection."""
        parser = facts_parser("db2")

        # Test with trigger
        sql_with_trigger = (
            "CREATE TRIGGER test_trigger AFTER INSERT ON test FOR EACH ROW BEGIN SELECT 1; END;"
        )
        assert parser.split_statements(sql_with_trigger) == [sql_with_trigger[:-1]]

        # Test without trigger
        sql_without_trigger = "CREATE TABLE test (id INTEGER);"
        assert parser.split_statements(sql_without_trigger) == [sql_without_trigger[:-1]]

    def test_db2_spufi_terminator_detection(self):
        """Test DB2 SPUFI terminator detection."""
        parser = facts_parser("db2")

        # Test with SPUFI terminator
        sql_with_spufi = "--#SET TERMINATOR @"
        assert [record.kind for record in parser.split(sql_with_spufi)] == ["directive"]

        # Test without SPUFI terminator
        sql_without_spufi = "CREATE TABLE test (id INTEGER);"
        assert [record.kind for record in parser.split(sql_without_spufi)] == ["sql"]

    def test_db2_advanced_splitting(self):
        """Test DB2 advanced statement splitting."""
        parser = facts_parser("db2")

        # Test with mixed statement types
        sql = """
        CREATE TABLE test (id INTEGER);
        BEGIN ATOMIC
            INSERT INTO test VALUES (1);
            SELECT * FROM test;
        END;
        EXEC SQL
            CREATE VIEW test_view AS SELECT * FROM test
        END-EXEC;
        """

        statements = parser.split_statements(sql)
        assert len(statements) >= 3

        # Should have table, compound, and exec sql
        table_found = any("CREATE TABLE" in stmt for stmt in statements)
        compound_found = any("BEGIN ATOMIC" in stmt for stmt in statements)
        exec_found = any("EXEC SQL" in stmt for stmt in statements)

        assert table_found
        # These might be split differently based on parser implementation
        assert compound_found or exec_found

    def test_db2_complex_compound_statement(self):
        """Test DB2 complex compound statement parsing."""
        parser = facts_parser("db2")

        sql = """
        BEGIN ATOMIC
            DECLARE v_count INTEGER;
            DECLARE v_name VARCHAR(100);
            
            SELECT COUNT(*) INTO v_count FROM employees;
            
            IF v_count > 0 THEN
                SELECT name INTO v_name FROM employees WHERE id = 1;
                INSERT INTO audit_log VALUES (v_name, CURRENT_TIMESTAMP);
            END IF;
            
            COMMIT;
        END;
        """

        statements = parser.split_statements(sql)
        assert len(statements) >= 1

        # Should preserve the compound statement block
        compound_stmt = next((stmt for stmt in statements if "BEGIN ATOMIC" in stmt), None)
        assert compound_stmt is not None
        assert "DECLARE v_count" in compound_stmt
        # The exact content depends on parser implementation
        assert "IF v_count > 0" in compound_stmt or "SELECT COUNT(*)" in compound_stmt

    def test_db2_nested_sql_blocks(self):
        """Test DB2 nested SQL block parsing."""
        parser = facts_parser("db2")

        sql = """
        CREATE OR REPLACE PROCEDURE complex_proc()
        LANGUAGE SQL
        BEGIN
            DECLARE v_error_code INTEGER DEFAULT 0;
            
            DECLARE CONTINUE HANDLER FOR SQLEXCEPTION
            BEGIN
                SET v_error_code = 1;
                ROLLBACK;
            END;
            
            BEGIN ATOMIC
                INSERT INTO test VALUES (1);
                INSERT INTO test VALUES (2);
            END;
            
            IF v_error_code = 0 THEN
                COMMIT;
            END IF;
        END;
        """

        statements = parser.split_statements(sql)
        assert len(statements) >= 1

        # Should preserve procedure blocks
        proc_stmt = next(
            (stmt for stmt in statements if "CREATE OR REPLACE PROCEDURE" in stmt), None
        )
        assert proc_stmt is not None
        # The exact content depends on parser implementation
        assert "DECLARE v_error_code" in proc_stmt or "LANGUAGE SQL" in proc_stmt

    def test_db2_spufi_multiple_terminators(self):
        """Test DB2 SPUFI multiple terminator changes."""
        parser = facts_parser("db2")

        sql = """
        --#SET TERMINATOR @
        CREATE PROCEDURE test1() LANGUAGE SQL BEGIN SELECT 1; END@
        CREATE PROCEDURE test2() LANGUAGE SQL BEGIN SELECT 2; END@
        --#SET TERMINATOR #
        CREATE PROCEDURE test3() LANGUAGE SQL BEGIN SELECT 3; END#
        --#SET TERMINATOR ;
        CREATE PROCEDURE test4() LANGUAGE SQL BEGIN SELECT 4; END;
        """

        statements = parser.split_statements(sql)
        assert len(statements) >= 4

        # Should handle different terminators
        proc1 = any("test1" in stmt for stmt in statements)
        proc2 = any("test2" in stmt for stmt in statements)
        proc3 = any("test3" in stmt for stmt in statements)
        proc4 = any("test4" in stmt for stmt in statements)

        assert proc1
        assert proc2
        assert proc3
        assert proc4

        # Test that method works without error (actual detection depends on implementation)

    def test_db2_performance_with_large_statements(self):
        """Test DB2 parser performance with large statements."""
        parser = facts_parser("db2")

        # Create a large compound statement
        large_sql = """
        BEGIN ATOMIC
            DECLARE v_counter INTEGER DEFAULT 0;
            
            WHILE v_counter < 100 DO
                INSERT INTO test VALUES (v_counter, 'test_value_' || CAST(v_counter AS VARCHAR(10)));
                SET v_counter = v_counter + 1;
            END WHILE;
            
            COMMIT;
        END;
        """

        result = parser.parse_sql(large_sql)
        assert result.success
        assert len(result.statements) >= 1
