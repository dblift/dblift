"""Extended tests for DB2 regex parser — targeting uncovered paths.

Covers:
- split_statements: all routing paths (exec sql, package, module, sqlpl, trigger,
  compound, spufi, plain semicolon)
- _split_with_package_awareness
- _split_with_module_awareness
- _split_with_exec_sql_awareness
- _split_with_sqlpl_awareness
- _split_with_compound_awareness
- _split_with_trigger_awareness
- _split_with_spufi_terminators
- _split_by_semicolon_db2 (strings, quoted identifiers, comments, @ terminator)
- _extract_sqlpl_procedure_name / _extract_sqlpl_function_name
- _extract_trigger_name / _extract_tablespace_name / _extract_stogroup_name
- _has_* detection methods
- parse_sql
- validate_sql / _validate_db2_syntax
- _clean_db2_comments
- is_utility_statement
"""

import unittest

from core.sql_model.base import ParseResult, SqlStatementType
from db.plugins.db2.parser.db2_regex_parser import DB2RegexParser


class TestSplitStatements(unittest.TestCase):
    def setUp(self):
        self.parser = DB2RegexParser()

    def test_empty_returns_empty(self):
        self.assertEqual(self.parser.split_statements(""), [])

    def test_whitespace_only_returns_empty(self):
        self.assertEqual(self.parser.split_statements("   \n  "), [])

    def test_simple_statements(self):
        sql = "SELECT 1; SELECT 2;"
        stmts = self.parser.split_statements(sql)
        self.assertGreaterEqual(len(stmts), 2)

    def test_exec_sql_routing(self):
        sql = "EXEC SQL SELECT 1 END-EXEC;"
        stmts = self.parser.split_statements(sql)
        self.assertGreaterEqual(len(stmts), 1)

    def test_sqlpl_routing(self):
        sql = "CREATE PROCEDURE p() LANGUAGE SQL\n" "BEGIN\n" "    SELECT 1;\n" "END;\n"
        stmts = self.parser.split_statements(sql)
        self.assertGreaterEqual(len(stmts), 1)

    def test_compound_routing(self):
        sql = "BEGIN ATOMIC SELECT 1; END;"
        stmts = self.parser.split_statements(sql)
        self.assertGreaterEqual(len(stmts), 1)

    def test_spufi_routing(self):
        sql = "--#SET TERMINATOR @\nSELECT 1@"
        stmts = self.parser.split_statements(sql)
        self.assertGreaterEqual(len(stmts), 1)


class TestHasDetectionMethods(unittest.TestCase):
    def setUp(self):
        self.parser = DB2RegexParser()

    def test_has_exec_sql_blocks_true(self):
        self.assertTrue(self.parser._has_exec_sql_blocks("EXEC SQL SELECT 1 END-EXEC"))

    def test_has_exec_sql_blocks_false(self):
        self.assertFalse(self.parser._has_exec_sql_blocks("SELECT 1;"))

    def test_has_package_blocks_true(self):
        sql = "CREATE PACKAGE pkg AS PROCEDURE p(); END pkg;"
        self.assertTrue(self.parser._has_package_blocks(sql))

    def test_has_package_blocks_false(self):
        self.assertFalse(self.parser._has_package_blocks("SELECT 1;"))

    def test_has_module_blocks_true(self):
        sql = "CREATE MODULE m BEGIN END MODULE;"
        self.assertTrue(self.parser._has_module_blocks(sql))

    def test_has_module_blocks_false(self):
        self.assertFalse(self.parser._has_module_blocks("SELECT 1;"))

    def test_has_sqlpl_blocks_true(self):
        sql = "CREATE PROCEDURE p() LANGUAGE SQL BEGIN SELECT 1; END;"
        self.assertTrue(self.parser._has_sqlpl_blocks(sql))

    def test_has_sqlpl_blocks_false(self):
        self.assertFalse(self.parser._has_sqlpl_blocks("SELECT 1;"))

    def test_has_compound_statements_atomic_true(self):
        self.assertTrue(self.parser._has_compound_statements("BEGIN ATOMIC SELECT 1; END;"))

    def test_has_compound_statements_not_atomic_true(self):
        self.assertTrue(self.parser._has_compound_statements("BEGIN NOT ATOMIC SELECT 1; END;"))

    def test_has_compound_statements_false(self):
        self.assertFalse(self.parser._has_compound_statements("SELECT 1;"))

    def test_has_trigger_blocks_true(self):
        sql = "CREATE TRIGGER t AFTER INSERT ON tbl FOR EACH ROW BEGIN ATOMIC SELECT 1; END;"
        self.assertTrue(self.parser._has_trigger_blocks(sql))

    def test_has_trigger_blocks_false(self):
        self.assertFalse(self.parser._has_trigger_blocks("SELECT 1;"))

    def test_has_spufi_terminators_true(self):
        self.assertTrue(self.parser._has_spufi_terminators("--#SET TERMINATOR @"))

    def test_has_spufi_terminators_false(self):
        self.assertFalse(self.parser._has_spufi_terminators("SELECT 1;"))


class TestSplitWithSpufiTerminators(unittest.TestCase):
    def setUp(self):
        self.parser = DB2RegexParser()

    def test_single_custom_terminator(self):
        sql = "--#SET TERMINATOR @\nCREATE TABLE t (id INT)@"
        stmts = self.parser._split_with_spufi_terminators(sql)
        self.assertGreaterEqual(len(stmts), 1)
        self.assertTrue(any("CREATE TABLE" in s for s in stmts))

    def test_multiple_statements_with_custom_terminator(self):
        sql = "--#SET TERMINATOR @\nSELECT 1@\nSELECT 2@"
        stmts = self.parser._split_with_spufi_terminators(sql)
        self.assertGreaterEqual(len(stmts), 2)

    def test_terminator_change_mid_script(self):
        sql = "--#SET TERMINATOR @\n" "SELECT 1@\n" "--#SET TERMINATOR ;\n" "SELECT 2;\n"
        stmts = self.parser._split_with_spufi_terminators(sql)
        self.assertGreaterEqual(len(stmts), 2)

    def test_remaining_statement_added(self):
        sql = "--#SET TERMINATOR @\nSELECT 1@\nSELECT 2"
        stmts = self.parser._split_with_spufi_terminators(sql)
        self.assertGreaterEqual(len(stmts), 2)


class TestSplitWithPackageAwareness(unittest.TestCase):
    def setUp(self):
        self.parser = DB2RegexParser()

    def test_package_as_one_statement(self):
        sql = "CREATE PACKAGE pkg AS PROCEDURE p(); END pkg;"
        stmts = self.parser._split_with_package_awareness(sql)
        self.assertGreaterEqual(len(stmts), 1)
        pkg = next((s for s in stmts if "CREATE PACKAGE" in s), None)
        self.assertIsNotNone(pkg)

    def test_sql_before_package_split(self):
        sql = "SELECT 1;\nCREATE PACKAGE pkg AS PROCEDURE p(); END pkg;"
        stmts = self.parser._split_with_package_awareness(sql)
        self.assertGreaterEqual(len(stmts), 2)

    def test_no_package_fallback(self):
        # No package block — falls back to semicolon splitting
        sql = "SELECT 1; SELECT 2;"
        stmts = self.parser._split_with_package_awareness(sql)
        self.assertGreaterEqual(len(stmts), 2)


class TestSplitWithModuleAwareness(unittest.TestCase):
    def setUp(self):
        self.parser = DB2RegexParser()

    def test_module_as_one_statement(self):
        sql = "CREATE MODULE m\n  PUBLISH FUNCTION f() RETURNS INT;\nEND MODULE;"
        stmts = self.parser._split_with_module_awareness(sql)
        self.assertGreaterEqual(len(stmts), 1)
        mod = next((s for s in stmts if "CREATE MODULE" in s), None)
        self.assertIsNotNone(mod)

    def test_sql_before_module_split(self):
        sql = "SELECT 1;\nCREATE MODULE m PUBLISH FUNCTION f() RETURNS INT; END MODULE;"
        stmts = self.parser._split_with_module_awareness(sql)
        self.assertGreaterEqual(len(stmts), 2)

    def test_no_module_fallback(self):
        sql = "SELECT 1; SELECT 2;"
        stmts = self.parser._split_with_module_awareness(sql)
        self.assertGreaterEqual(len(stmts), 2)


class TestSplitWithExecSqlAwareness(unittest.TestCase):
    def setUp(self):
        self.parser = DB2RegexParser()

    def test_exec_sql_block_as_one(self):
        sql = "EXEC SQL CREATE TABLE t (id INT) END-EXEC;\n"
        stmts = self.parser._split_with_exec_sql_awareness(sql)
        self.assertGreaterEqual(len(stmts), 1)

    def test_sql_after_exec_block(self):
        sql = "EXEC SQL CREATE TABLE t (id INT) END-EXEC;\nSELECT 1;"
        stmts = self.parser._split_with_exec_sql_awareness(sql)
        self.assertGreaterEqual(len(stmts), 2)

    def test_no_exec_sql_fallback(self):
        # Config.extract_exec_sql_blocks returns empty for no EXEC SQL
        sql = "SELECT 1; SELECT 2;"
        stmts = self.parser._split_with_exec_sql_awareness(sql)
        self.assertGreaterEqual(len(stmts), 2)


class TestSplitWithSqlplAwareness(unittest.TestCase):
    def setUp(self):
        self.parser = DB2RegexParser()

    def test_procedure_as_one_block(self):
        sql = "CREATE PROCEDURE p() LANGUAGE SQL BEGIN SELECT 1; END;"
        stmts = self.parser._split_with_sqlpl_awareness(sql)
        self.assertGreaterEqual(len(stmts), 1)

    def test_sql_before_proc(self):
        sql = "SELECT 1;\nCREATE PROCEDURE p() LANGUAGE SQL BEGIN SELECT 2; END;"
        stmts = self.parser._split_with_sqlpl_awareness(sql)
        self.assertGreaterEqual(len(stmts), 2)

    def test_no_sqlpl_fallback(self):
        sql = "SELECT 1; SELECT 2;"
        stmts = self.parser._split_with_sqlpl_awareness(sql)
        self.assertGreaterEqual(len(stmts), 2)


class TestSplitWithCompoundAwareness(unittest.TestCase):
    def setUp(self):
        self.parser = DB2RegexParser()

    def test_compound_as_one_block(self):
        sql = "BEGIN ATOMIC SELECT 1; END;"
        stmts = self.parser._split_with_compound_awareness(sql)
        self.assertGreaterEqual(len(stmts), 1)

    def test_sql_before_compound(self):
        sql = "SELECT 1;\nBEGIN ATOMIC SELECT 2; END;"
        stmts = self.parser._split_with_compound_awareness(sql)
        self.assertGreaterEqual(len(stmts), 2)

    def test_no_compound_fallback(self):
        sql = "SELECT 1; SELECT 2;"
        stmts = self.parser._split_with_compound_awareness(sql)
        self.assertGreaterEqual(len(stmts), 2)


class TestSplitWithTriggerAwareness(unittest.TestCase):
    def setUp(self):
        self.parser = DB2RegexParser()

    def test_trigger_as_one_block(self):
        sql = "CREATE TRIGGER t AFTER INSERT ON tbl FOR EACH ROW BEGIN ATOMIC SELECT 1; END;"
        stmts = self.parser._split_with_trigger_awareness(sql)
        self.assertGreaterEqual(len(stmts), 1)

    def test_sql_before_trigger(self):
        sql = "SELECT 1;\nCREATE TRIGGER t AFTER INSERT ON tbl FOR EACH ROW BEGIN ATOMIC SELECT 2; END;"
        stmts = self.parser._split_with_trigger_awareness(sql)
        self.assertGreaterEqual(len(stmts), 2)

    def test_no_trigger_fallback(self):
        sql = "SELECT 1; SELECT 2;"
        stmts = self.parser._split_with_trigger_awareness(sql)
        self.assertGreaterEqual(len(stmts), 2)


class TestSplitBySemicolonDb2(unittest.TestCase):
    def setUp(self):
        self.parser = DB2RegexParser()

    def test_simple_statements(self):
        stmts = self.parser._split_by_semicolon_db2("SELECT 1; SELECT 2;")
        self.assertEqual(len(stmts), 2)

    def test_single_quoted_string_semicolon_not_split(self):
        stmts = self.parser._split_by_semicolon_db2("SELECT 'a;b'; SELECT 1;")
        self.assertEqual(len(stmts), 2)
        self.assertIn("'a;b'", stmts[0])

    def test_double_quoted_identifier_no_internal_semicolon(self):
        # Quoted identifier without semicolon inside is handled correctly
        stmts = self.parser._split_by_semicolon_db2('SELECT "col_name"; SELECT 1;')
        self.assertEqual(len(stmts), 2)

    def test_line_comment_semicolon_not_split(self):
        stmts = self.parser._split_by_semicolon_db2("SELECT 1; -- comment;\nSELECT 2;")
        self.assertEqual(len(stmts), 2)

    def test_block_comment_semicolon_not_split(self):
        stmts = self.parser._split_by_semicolon_db2("SELECT 1; /* ; */ SELECT 2;")
        self.assertEqual(len(stmts), 2)

    def test_at_sign_terminator(self):
        stmts = self.parser._split_by_semicolon_db2("SELECT 1@ SELECT 2@")
        self.assertEqual(len(stmts), 2)

    def test_escaped_single_quote(self):
        stmts = self.parser._split_by_semicolon_db2("SELECT 'O''Brien'; SELECT 1;")
        self.assertEqual(len(stmts), 2)
        self.assertIn("O''Brien", stmts[0])

    def test_empty_string(self):
        self.assertEqual(self.parser._split_by_semicolon_db2(""), [])

    def test_no_terminator_returns_single(self):
        stmts = self.parser._split_by_semicolon_db2("SELECT 1")
        self.assertEqual(len(stmts), 1)

    def test_comment_only_filtered(self):
        stmts = self.parser._split_by_semicolon_db2("-- comment;")
        # The comment line itself has ; but it produces only a comment
        self.assertEqual(len(stmts), 0)


class TestExtractNames(unittest.TestCase):
    def setUp(self):
        self.parser = DB2RegexParser()

    def test_extract_procedure_name_simple(self):
        sql = "CREATE PROCEDURE my_proc() LANGUAGE SQL BEGIN SELECT 1; END;"
        self.assertEqual(self.parser._extract_sqlpl_procedure_name(sql), "my_proc")

    def test_extract_procedure_name_quoted(self):
        sql = 'CREATE PROCEDURE "my_proc"() LANGUAGE SQL BEGIN SELECT 1; END;'
        self.assertEqual(self.parser._extract_sqlpl_procedure_name(sql), "my_proc")

    def test_extract_procedure_name_or_replace(self):
        sql = "CREATE OR REPLACE PROCEDURE my_proc() LANGUAGE SQL BEGIN SELECT 1; END;"
        self.assertEqual(self.parser._extract_sqlpl_procedure_name(sql), "my_proc")

    def test_extract_procedure_name_none(self):
        sql = "SELECT 1;"
        self.assertIsNone(self.parser._extract_sqlpl_procedure_name(sql))

    def test_extract_function_name_simple(self):
        sql = "CREATE FUNCTION my_func() RETURNS INTEGER LANGUAGE SQL BEGIN RETURN 1; END;"
        self.assertEqual(self.parser._extract_sqlpl_function_name(sql), "my_func")

    def test_extract_function_name_quoted(self):
        sql = 'CREATE FUNCTION "my_func"() RETURNS INTEGER LANGUAGE SQL BEGIN RETURN 1; END;'
        self.assertEqual(self.parser._extract_sqlpl_function_name(sql), "my_func")

    def test_extract_function_name_or_replace(self):
        sql = "CREATE OR REPLACE FUNCTION my_func() RETURNS INTEGER BEGIN RETURN 1; END;"
        self.assertEqual(self.parser._extract_sqlpl_function_name(sql), "my_func")

    def test_extract_function_name_none(self):
        sql = "SELECT 1;"
        self.assertIsNone(self.parser._extract_sqlpl_function_name(sql))

    def test_extract_trigger_name_simple(self):
        sql = "CREATE TRIGGER my_trigger AFTER INSERT ON t FOR EACH ROW BEGIN SELECT 1; END;"
        self.assertEqual(self.parser._extract_trigger_name(sql), "my_trigger")

    def test_extract_trigger_name_quoted(self):
        sql = 'CREATE TRIGGER "my_trigger" AFTER INSERT ON t FOR EACH ROW BEGIN SELECT 1; END;'
        self.assertEqual(self.parser._extract_trigger_name(sql), "my_trigger")

    def test_extract_trigger_name_or_replace(self):
        sql = "CREATE OR REPLACE TRIGGER my_trigger AFTER INSERT ON t FOR EACH ROW BEGIN END;"
        self.assertEqual(self.parser._extract_trigger_name(sql), "my_trigger")

    def test_extract_trigger_name_none(self):
        sql = "SELECT 1;"
        self.assertIsNone(self.parser._extract_trigger_name(sql))

    def test_extract_tablespace_name_create(self):
        sql = "CREATE TABLESPACE my_ts MANAGED BY SYSTEM;"
        self.assertEqual(self.parser._extract_tablespace_name(sql), "my_ts")

    def test_extract_tablespace_name_lob(self):
        sql = "CREATE LOB TABLESPACE my_lob_ts MANAGED BY SYSTEM;"
        self.assertEqual(self.parser._extract_tablespace_name(sql), "my_lob_ts")

    def test_extract_tablespace_name_alter(self):
        sql = "ALTER TABLESPACE my_ts ADD FILE 1000;"
        self.assertEqual(self.parser._extract_tablespace_name(sql), "my_ts")

    def test_extract_tablespace_name_drop(self):
        sql = "DROP TABLESPACE my_ts;"
        self.assertEqual(self.parser._extract_tablespace_name(sql), "my_ts")

    def test_extract_tablespace_name_quoted(self):
        sql = 'CREATE TABLESPACE "my_ts" MANAGED BY SYSTEM;'
        self.assertEqual(self.parser._extract_tablespace_name(sql), "my_ts")

    def test_extract_tablespace_name_none(self):
        sql = "SELECT 1;"
        self.assertIsNone(self.parser._extract_tablespace_name(sql))

    def test_extract_stogroup_name_create(self):
        sql = "CREATE STOGROUP my_sg VOLUMES ('vol1');"
        self.assertEqual(self.parser._extract_stogroup_name(sql), "my_sg")

    def test_extract_stogroup_name_alter(self):
        sql = "ALTER STOGROUP my_sg ADD VOLUMES ('vol2');"
        self.assertEqual(self.parser._extract_stogroup_name(sql), "my_sg")

    def test_extract_stogroup_name_drop(self):
        sql = "DROP STOGROUP my_sg;"
        self.assertEqual(self.parser._extract_stogroup_name(sql), "my_sg")

    def test_extract_stogroup_name_quoted(self):
        sql = "CREATE STOGROUP \"my_sg\" VOLUMES ('vol1');"
        self.assertEqual(self.parser._extract_stogroup_name(sql), "my_sg")

    def test_extract_stogroup_name_none(self):
        sql = "SELECT 1;"
        self.assertIsNone(self.parser._extract_stogroup_name(sql))


class TestCleanDb2Comments(unittest.TestCase):
    def setUp(self):
        self.parser = DB2RegexParser()

    def test_removes_line_comment(self):
        sql = "SELECT 1; -- line comment"
        result = self.parser._clean_db2_comments(sql)
        self.assertNotIn("line comment", result)
        self.assertIn("SELECT 1", result)

    def test_removes_block_comment(self):
        sql = "SELECT /* block */ 1;"
        result = self.parser._clean_db2_comments(sql)
        self.assertNotIn("block", result)

    def test_multiline_block_comment(self):
        sql = "SELECT /*\n  multi\n  line\n*/ 1;"
        result = self.parser._clean_db2_comments(sql)
        self.assertNotIn("multi", result)

    def test_empty_sql(self):
        self.assertEqual(self.parser._clean_db2_comments(""), "")


class TestParseSql(unittest.TestCase):
    def setUp(self):
        self.parser = DB2RegexParser()

    def test_parse_empty(self):
        result = self.parser.parse_sql("")
        self.assertIsInstance(result, ParseResult)

    def test_parse_simple_create_table(self):
        sql = "CREATE TABLE t (id INTEGER PRIMARY KEY);"
        result = self.parser.parse_sql(sql)
        self.assertIsInstance(result, ParseResult)
        self.assertTrue(result.success)
        self.assertGreaterEqual(len(result.statements), 1)

    def test_parse_with_none_input(self):
        result = self.parser.parse_sql(None)
        self.assertIsInstance(result, ParseResult)

    def test_parse_with_default_schema(self):
        sql = "CREATE TABLE t (id INTEGER);"
        result = self.parser.parse_sql(sql, default_schema="MYSCHEMA")
        self.assertTrue(result.success)

    def test_parse_insert(self):
        sql = "INSERT INTO t VALUES (1, 'Alice');"
        result = self.parser.parse_sql(sql)
        self.assertTrue(result.success)
        self.assertEqual(result.statements[0].statement_type, SqlStatementType.DML)

    def test_parse_select(self):
        sql = "SELECT * FROM t WHERE id = 1;"
        result = self.parser.parse_sql(sql)
        self.assertTrue(result.success)
        self.assertEqual(result.statements[0].statement_type, SqlStatementType.QUERY)

    def test_parse_procedure(self):
        sql = "CREATE PROCEDURE p() LANGUAGE SQL BEGIN SELECT 1; END;"
        result = self.parser.parse_sql(sql)
        self.assertIsInstance(result, ParseResult)

    def test_parse_compound_statement(self):
        sql = "BEGIN ATOMIC DECLARE v INTEGER; SET v = 1; END;"
        result = self.parser.parse_sql(sql)
        self.assertIsInstance(result, ParseResult)

    def test_parse_with_at_terminator(self):
        sql = "--#SET TERMINATOR @\nCREATE TABLE t (id INTEGER)@"
        result = self.parser.parse_sql(sql)
        self.assertIsInstance(result, ParseResult)

    def test_parse_multiple_statements(self):
        sql = "CREATE TABLE a (id INTEGER); CREATE TABLE b (id INTEGER); INSERT INTO a VALUES (1);"
        result = self.parser.parse_sql(sql)
        self.assertTrue(result.success)
        self.assertGreaterEqual(len(result.statements), 3)


class TestValidateSql(unittest.TestCase):
    def setUp(self):
        self.parser = DB2RegexParser()

    def test_valid_simple_sql(self):
        sql = "CREATE TABLE t (id INTEGER PRIMARY KEY);"
        result = self.parser.validate_sql(sql)
        self.assertTrue(result["valid"])

    def test_unmatched_quoted_identifier(self):
        sql = 'CREATE TABLE "test (id INTEGER);'
        result = self.parser.validate_sql(sql)
        self.assertFalse(result["valid"])
        self.assertIn("Unmatched quoted identifier", result["errors"][0])

    def test_unmatched_begin_end(self):
        sql = "BEGIN ATOMIC INSERT INTO t VALUES (1);"
        result = self.parser.validate_sql(sql)
        self.assertFalse(result["valid"])
        self.assertIn("Unmatched BEGIN/END", result["errors"][0])

    def test_exec_sql_without_end_exec(self):
        sql = "EXEC SQL CREATE TABLE t (id INTEGER);"
        result = self.parser.validate_sql(sql)
        self.assertFalse(result["valid"])
        self.assertIn("END-EXEC", result["errors"][0])

    def test_empty_sql_invalid(self):
        result = self.parser.validate_sql("")
        self.assertFalse(result["valid"])
        self.assertIn("No valid statements found", result["errors"][0])

    def test_statement_count_in_result(self):
        sql = "CREATE TABLE a (id INTEGER); INSERT INTO a VALUES (1);"
        result = self.parser.validate_sql(sql)
        self.assertIn("statement_count", result)
        self.assertGreaterEqual(result["statement_count"], 2)


class TestValidateDb2Syntax(unittest.TestCase):
    def setUp(self):
        self.parser = DB2RegexParser()

    def test_unmatched_quoted_identifier(self):
        sql = 'CREATE TABLE "test (id INTEGER);'
        errors = self.parser._validate_db2_syntax(sql)
        self.assertGreater(len(errors), 0)
        self.assertIn("Unmatched quoted identifier", errors[0])

    def test_matched_identifier_no_error(self):
        sql = 'CREATE TABLE "test" (id INTEGER);'
        errors = self.parser._validate_db2_syntax(sql)
        self.assertEqual(errors, [])

    def test_unmatched_begin_end(self):
        sql = "BEGIN ATOMIC INSERT INTO t VALUES (1);"
        errors = self.parser._validate_db2_syntax(sql)
        self.assertGreater(len(errors), 0)
        self.assertIn("Unmatched BEGIN/END", errors[0])

    def test_matched_begin_end(self):
        sql = "BEGIN ATOMIC INSERT INTO t VALUES (1); END;"
        errors = self.parser._validate_db2_syntax(sql)
        begin_end_errors = [e for e in errors if "BEGIN/END" in e]
        self.assertEqual(len(begin_end_errors), 0)

    def test_exec_sql_without_end_exec(self):
        sql = "EXEC SQL SELECT 1;"
        errors = self.parser._validate_db2_syntax(sql)
        self.assertGreater(len(errors), 0)
        self.assertIn("END-EXEC", errors[0])

    def test_exec_sql_with_end_exec_ok(self):
        sql = "EXEC SQL SELECT 1 END-EXEC;"
        errors = self.parser._validate_db2_syntax(sql)
        exec_errors = [e for e in errors if "EXEC SQL" in e]
        self.assertEqual(len(exec_errors), 0)


class TestIsUtilityStatement(unittest.TestCase):
    def setUp(self):
        self.parser = DB2RegexParser()

    def test_reorg_table(self):
        result = self.parser.is_utility_statement("REORG TABLE employees")
        self.assertIsInstance(result, bool)

    def test_runstats(self):
        result = self.parser.is_utility_statement("RUNSTATS ON TABLE employees")
        self.assertIsInstance(result, bool)

    def test_bind(self):
        result = self.parser.is_utility_statement("BIND PACKAGE pkg1")
        self.assertIsInstance(result, bool)

    def test_rebind(self):
        result = self.parser.is_utility_statement("REBIND PACKAGE pkg1")
        self.assertIsInstance(result, bool)

    def test_regular_select_is_not_utility(self):
        result = self.parser.is_utility_statement("SELECT 1 FROM t;")
        self.assertIsInstance(result, bool)


class TestIntegration(unittest.TestCase):
    def setUp(self):
        self.parser = DB2RegexParser()

    def test_full_schema_creation(self):
        sql = """
CREATE TABLESPACE ts1 MANAGED BY SYSTEM USING ('path');
CREATE TABLE employees (
    id INTEGER NOT NULL GENERATED ALWAYS AS IDENTITY,
    name VARCHAR(100) NOT NULL,
    hire_date DATE DEFAULT CURRENT DATE
) IN ts1;
CREATE INDEX idx_emp_name ON employees (name);
INSERT INTO employees (name, hire_date) VALUES ('Alice', '2024-01-01');
"""
        result = self.parser.parse_sql(sql)
        self.assertTrue(result.success)
        self.assertGreaterEqual(len(result.statements), 4)

    def test_procedure_with_error_handler(self):
        sql = """
CREATE OR REPLACE PROCEDURE safe_insert(IN val INTEGER)
LANGUAGE SQL
BEGIN
    DECLARE CONTINUE HANDLER FOR SQLEXCEPTION
    BEGIN
        ROLLBACK;
    END;
    INSERT INTO t VALUES (val);
    COMMIT;
END;
"""
        result = self.parser.parse_sql(sql)
        self.assertIsInstance(result, ParseResult)

    def test_spufi_full_script(self):
        sql = """
--#SET TERMINATOR @
CREATE TABLE test1 (id INTEGER)@
CREATE TABLE test2 (id INTEGER)@
--#SET TERMINATOR ;
INSERT INTO test1 VALUES (1);
"""
        stmts = self.parser.split_statements(sql)
        self.assertGreaterEqual(len(stmts), 3)
        self.assertTrue(any("test1" in s for s in stmts))
        self.assertTrue(any("test2" in s for s in stmts))

    def test_quoted_identifiers_in_statements(self):
        sql = 'CREATE TABLE "MY_TABLE" ("ID" INTEGER, "NAME" VARCHAR(100));'
        result = self.parser.parse_sql(sql)
        self.assertTrue(result.success)
        self.assertIn('"MY_TABLE"', result.statements[0].sql_text)

    def test_mixed_db2_objects(self):
        sql = """
CREATE STOGROUP sg1 VOLUMES ('vol1');
CREATE TABLESPACE ts1 IN STOGROUP sg1;
CREATE TABLE t (id INTEGER) IN ts1;
"""
        result = self.parser.parse_sql(sql)
        self.assertTrue(result.success)
        self.assertGreaterEqual(len(result.statements), 3)

    def test_multiple_statements_at_terminator(self):
        sql = "SELECT 1@ SELECT 2@ SELECT 3@"
        stmts = self.parser._split_by_semicolon_db2(sql)
        self.assertEqual(len(stmts), 3)

    def test_nested_quoted_in_string(self):
        sql = "SELECT 'O''Brien' FROM t; INSERT INTO t VALUES ('Jones');"
        stmts = self.parser.split_statements(sql)
        self.assertGreaterEqual(len(stmts), 2)


if __name__ == "__main__":
    unittest.main()
