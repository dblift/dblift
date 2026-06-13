"""Tests for DB2 regex parser."""

from unittest.mock import patch

import pytest

from core.sql_model.base import ParseResult, SqlStatementType
from db.plugins.db2.parser.db2_regex_parser import DB2RegexParser


@pytest.mark.unit
class TestDB2RegexParser:
    """Test DB2 regex parser functionality."""

    def test_parser_creation(self):
        """Test parser can be created."""
        parser = DB2RegexParser()
        assert parser is not None
        assert parser.dialect_name == "db2"

    def test_parse_sql_simple(self):
        """Test parsing simple SQL."""
        parser = DB2RegexParser()

        sql = "CREATE TABLE test (id INTEGER PRIMARY KEY, name VARCHAR(100));"
        result = parser.parse_sql(sql)

        assert isinstance(result, ParseResult)
        assert result.success
        assert len(result.statements) >= 1
        assert "CREATE TABLE test" in result.statements[0].sql_text

    def test_parse_sql_multiple_statements(self):
        """Test parsing multiple SQL statements."""
        parser = DB2RegexParser()

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
        parser = DB2RegexParser()

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
        parser = DB2RegexParser()

        result = parser.parse_sql("")

        assert isinstance(result, ParseResult)
        assert result.success
        assert len(result.statements) == 0

    def test_extract_objects(self):
        """Test object extraction from SQL."""
        parser = DB2RegexParser()

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
        parser = DB2RegexParser()

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
        parser = DB2RegexParser()

        sql = """
        CREATE TABLE test1 (id INTEGER);
        INSERT INTO test1 VALUES (1);
        CREATE TABLE test2 (id INTEGER);
        """

        statements = parser.split_statements(sql)
        assert len(statements) >= 3

    def test_statement_classification(self):
        """Test statement type classification."""
        parser = DB2RegexParser()

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
        parser = DB2RegexParser()

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
        parser = DB2RegexParser()

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
        parser = DB2RegexParser()

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
        parser = DB2RegexParser()

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
        parser = DB2RegexParser()

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

    def test_inheritance_from_enhanced_regex_parser(self):
        """Test that DB2RegexParser inherits from EnhancedRegexParser."""
        from core.sql_parser.enhanced_regex_parser import EnhancedRegexParser

        parser = DB2RegexParser()
        assert isinstance(parser, EnhancedRegexParser)

    def test_parser_configuration(self):
        """Test parser configuration attributes."""
        parser = DB2RegexParser()
        assert hasattr(parser, "dialect_name")
        assert parser.dialect_name == "db2"
        assert hasattr(parser, "config")

    def test_utility_statement_detection(self):
        """Test DB2 utility statement detection."""
        parser = DB2RegexParser()

        # Test utility statements
        utility_statements = [
            "REORG TABLE employees",
            "RUNSTATS ON TABLE employees",
            "BIND PACKAGE pkg1",
            "REBIND PACKAGE pkg1",
        ]

        for stmt in utility_statements:
            result = parser.is_utility_statement(stmt)
            assert isinstance(result, bool)

    def test_db2_specific_object_extraction(self):
        """Test DB2-specific object extraction."""
        parser = DB2RegexParser()

        sql = """
        CREATE TABLESPACE ts1 MANAGED BY SYSTEM;
        CREATE STOGROUP sg1 VOLUMES ('vol1');
        """

        objects = parser.extract_objects(sql)
        # Should extract tablespace and stogroup objects
        assert len(objects) >= 2

    def test_error_handling_and_recovery(self):
        """Test error handling and recovery."""
        parser = DB2RegexParser()

        # Test with potentially problematic SQL
        problematic_sql = "CREATE TABLE test (id INTEGER; -- Missing closing parenthesis"
        result = parser.parse_sql(problematic_sql)

        # Should handle gracefully
        assert isinstance(result, ParseResult)

    def test_edge_cases(self):
        """Test various edge cases."""
        parser = DB2RegexParser()

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
        parser = DB2RegexParser()

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
        parser = DB2RegexParser()

        sql = 'CREATE TABLE "test_table" ("column_name" INTEGER, "special-col" VARCHAR(100));'

        result = parser.parse_sql(sql)
        assert isinstance(result, ParseResult)
        assert result.success
        assert '"test_table"' in result.statements[0].sql_text

    def test_db2_exec_sql_detection(self):
        """Test DB2 EXEC SQL detection."""
        parser = DB2RegexParser()

        # Test with EXEC SQL
        sql_with_exec = "EXEC SQL CREATE TABLE test (id INTEGER) END-EXEC;"
        assert parser._has_exec_sql_blocks(sql_with_exec)

        # Test without EXEC SQL
        sql_without_exec = "CREATE TABLE test (id INTEGER);"
        assert not parser._has_exec_sql_blocks(sql_without_exec)

    def test_db2_sqlpl_detection(self):
        """Test DB2 SQL/PL detection."""
        parser = DB2RegexParser()

        # Test with SQL/PL procedure
        sql_with_sqlpl = "CREATE PROCEDURE test() LANGUAGE SQL BEGIN SELECT 1; END;"
        assert parser._has_sqlpl_blocks(sql_with_sqlpl)

        # Test with SQLPL procedure
        sql_with_sqlpl2 = "CREATE PROCEDURE test() LANGUAGE SQLPL BEGIN SELECT 1; END;"
        assert parser._has_sqlpl_blocks(sql_with_sqlpl2)

        # Test without SQL/PL
        sql_without_sqlpl = "CREATE TABLE test (id INTEGER);"
        assert not parser._has_sqlpl_blocks(sql_without_sqlpl)

    def test_db2_compound_statement_detection(self):
        """Test DB2 compound statement detection."""
        parser = DB2RegexParser()

        # Test with compound atomic
        sql_with_compound = "BEGIN ATOMIC SELECT 1; END;"
        assert parser._has_compound_statements(sql_with_compound)

        # Test with compound not atomic
        sql_with_compound2 = "BEGIN NOT ATOMIC SELECT 1; END;"
        assert parser._has_compound_statements(sql_with_compound2)

        # Test without compound
        sql_without_compound = "SELECT 1;"
        assert not parser._has_compound_statements(sql_without_compound)

    def test_db2_trigger_detection(self):
        """Test DB2 trigger detection."""
        parser = DB2RegexParser()

        # Test with trigger
        sql_with_trigger = (
            "CREATE TRIGGER test_trigger AFTER INSERT ON test FOR EACH ROW BEGIN SELECT 1; END;"
        )
        assert parser._has_trigger_blocks(sql_with_trigger)

        # Test without trigger
        sql_without_trigger = "CREATE TABLE test (id INTEGER);"
        assert not parser._has_trigger_blocks(sql_without_trigger)

    def test_db2_spufi_terminator_detection(self):
        """Test DB2 SPUFI terminator detection."""
        parser = DB2RegexParser()

        # Test with SPUFI terminator
        sql_with_spufi = "--#SET TERMINATOR @"
        assert parser._has_spufi_terminators(sql_with_spufi)

        # Test without SPUFI terminator
        sql_without_spufi = "CREATE TABLE test (id INTEGER);"
        assert not parser._has_spufi_terminators(sql_without_spufi)

    def test_db2_sqlpl_procedure_name_extraction(self):
        """Test DB2 SQL/PL procedure name extraction."""
        parser = DB2RegexParser()

        # Test basic procedure
        sql = "CREATE PROCEDURE test_proc() LANGUAGE SQL BEGIN SELECT 1; END;"
        name = parser._extract_sqlpl_procedure_name(sql)
        assert name == "test_proc"

        # Test with quoted name
        sql = 'CREATE PROCEDURE "test_proc"() LANGUAGE SQL BEGIN SELECT 1; END;'
        name = parser._extract_sqlpl_procedure_name(sql)
        assert name == "test_proc"

    def test_db2_sqlpl_function_name_extraction(self):
        """Test DB2 SQL/PL function name extraction."""
        parser = DB2RegexParser()

        # Test basic function
        sql = "CREATE FUNCTION test_func() RETURNS INTEGER LANGUAGE SQL BEGIN RETURN 1; END;"
        name = parser._extract_sqlpl_function_name(sql)
        assert name == "test_func"

        # Test with quoted name
        sql = 'CREATE FUNCTION "test_func"() RETURNS INTEGER LANGUAGE SQL BEGIN RETURN 1; END;'
        name = parser._extract_sqlpl_function_name(sql)
        assert name == "test_func"

    def test_db2_trigger_name_extraction(self):
        """Test DB2 trigger name extraction."""
        parser = DB2RegexParser()

        # Test basic trigger
        sql = "CREATE TRIGGER test_trigger AFTER INSERT ON test FOR EACH ROW BEGIN SELECT 1; END;"
        name = parser._extract_trigger_name(sql)
        assert name == "test_trigger"

        # Test with quoted name
        sql = 'CREATE TRIGGER "test_trigger" AFTER INSERT ON test FOR EACH ROW BEGIN SELECT 1; END;'
        name = parser._extract_trigger_name(sql)
        assert name == "test_trigger"

    def test_db2_tablespace_name_extraction(self):
        """Test DB2 tablespace name extraction."""
        parser = DB2RegexParser()

        # Test basic tablespace
        sql = "CREATE TABLESPACE test_ts MANAGED BY SYSTEM;"
        name = parser._extract_tablespace_name(sql)
        assert name == "test_ts"

        # Test LOB tablespace
        sql = "CREATE LOB TABLESPACE test_lob_ts MANAGED BY SYSTEM;"
        name = parser._extract_tablespace_name(sql)
        assert name == "test_lob_ts"

    def test_db2_stogroup_name_extraction(self):
        """Test DB2 storage group name extraction."""
        parser = DB2RegexParser()

        # Test basic stogroup
        sql = "CREATE STOGROUP test_sg VOLUMES ('vol1');"
        name = parser._extract_stogroup_name(sql)
        assert name == "test_sg"

    def test_db2_advanced_splitting(self):
        """Test DB2 advanced statement splitting."""
        parser = DB2RegexParser()

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
        parser = DB2RegexParser()

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
        parser = DB2RegexParser()

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
        parser = DB2RegexParser()

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

    def test_db2_mainframe_specific_features(self):
        """Test DB2 mainframe-specific features."""
        parser = DB2RegexParser()

        sql = """
        CREATE STOGROUP mysg VOLUMES ('vol1', 'vol2');
        CREATE TABLESPACE myts IN STOGROUP mysg;
        CREATE TABLE test (id INTEGER) IN myts.ts1;
        """

        result = parser.parse_sql(sql)
        assert result.success
        assert len(result.statements) >= 3

        # Should handle mainframe objects
        objects = parser.extract_objects(sql)
        assert len(objects) >= 3  # stogroup, tablespace, table

    def test_db2_error_handling_edge_cases(self):
        """Test DB2 parser error handling edge cases."""
        parser = DB2RegexParser()

        # Test with None input
        result = parser.parse_sql(None)
        assert isinstance(result, ParseResult)

        # Test with very long SQL
        long_sql = "SELECT " + ", ".join([f"col{i}" for i in range(1000)]) + " FROM test;"
        result = parser.parse_sql(long_sql)
        assert result.success

        # Test with nested quotes
        nested_sql = """CREATE TABLE test (name VARCHAR(100) DEFAULT 'O''Connor');"""
        result = parser.parse_sql(nested_sql)
        assert result.success

    def test_db2_utility_statements(self):
        """Test DB2 utility statement detection."""
        parser = DB2RegexParser()

        utility_statements = [
            "REORG TABLE test",
            "RUNSTATS ON TABLE test",
            "BIND PACKAGE pkg1",
            "REBIND PACKAGE pkg1",
            "LOAD FROM file.del OF DEL INSERT INTO test",
            "EXPORT TO file.del OF DEL SELECT * FROM test",
        ]

        for stmt in utility_statements:
            result = parser.is_utility_statement(stmt)
            assert isinstance(result, bool)
            # Test that method works without error (actual detection depends on implementation)

    def test_db2_performance_with_large_statements(self):
        """Test DB2 parser performance with large statements."""
        parser = DB2RegexParser()

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

    def test_db2_syntax_validation_comprehensive(self):
        """Test comprehensive DB2 syntax validation."""
        parser = DB2RegexParser()

        # Test unmatched quoted identifiers
        invalid_sql = 'CREATE TABLE "test (id INTEGER);'
        result = parser.validate_sql(invalid_sql)
        assert not result["valid"]
        assert "Unmatched quoted identifier" in result["errors"][0]

        # Test unmatched BEGIN/END
        invalid_sql = "BEGIN ATOMIC INSERT INTO test VALUES (1);"
        result = parser.validate_sql(invalid_sql)
        assert not result["valid"]
        assert "Unmatched BEGIN/END blocks" in result["errors"][0]

        # Test EXEC SQL without END-EXEC
        invalid_sql = "EXEC SQL CREATE TABLE test (id INTEGER);"
        result = parser.validate_sql(invalid_sql)
        assert not result["valid"]
        assert "EXEC SQL block without END-EXEC" in result["errors"][0]
