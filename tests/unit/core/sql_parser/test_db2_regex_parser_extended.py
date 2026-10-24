"""Extended tests for DB2 regex parser — targeting uncovered paths.

Covers:
- client scanner for directives, block units, lexemes, and refusal
- _extract_sqlpl_procedure_name / _extract_sqlpl_function_name
- _extract_trigger_name / _extract_tablespace_name / _extract_stogroup_name
- parse_sql
- validate_sql / _validate_db2_syntax
- _clean_db2_comments
- is_utility_statement
"""

import unittest

from dblift.core.sql_model.base import ParseResult, SqlStatementType
from tests.support.facts_parser import facts_parser


class TestSplitStatements(unittest.TestCase):
    def setUp(self):
        self.parser = facts_parser("db2")

    def test_empty_returns_empty(self):
        self.assertEqual(self.parser.split_statements(""), [])

    def test_whitespace_only_returns_empty(self):
        self.assertEqual(self.parser.split_statements("   \n  "), [])

    def test_simple_statements(self):
        sql = "SELECT 1;\nSELECT 2;"
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


class TestClientScannerBehavior(unittest.TestCase):
    def setUp(self):
        self.parser = facts_parser("db2")

    def test_routines_packages_modules_and_compounds_stay_whole(self):
        scripts = (
            "EXEC SQL CREATE TABLE t (id INT) END-EXEC;",
            "CREATE PACKAGE pkg AS PROCEDURE p(); END pkg;",
            "ALTER MODULE m ADD PROCEDURE p() BEGIN SELECT 1; END;",
            "CREATE PROCEDURE p() LANGUAGE SQL BEGIN SELECT 1; END;",
            "CREATE FUNCTION f() RETURNS INTEGER LANGUAGE SQL BEGIN RETURN 1; END;",
            "BEGIN ATOMIC SELECT 1; END;",
            "BEGIN NOT ATOMIC SELECT 1; END;",
            "CREATE TRIGGER t AFTER INSERT ON tbl FOR EACH ROW BEGIN ATOMIC SELECT 1; END;",
        )
        for script in scripts:
            with self.subTest(script=script):
                self.assertEqual(len(self.parser.split_for_extraction(script)), 1)

    def test_create_module_is_not_a_procedural_block(self):
        script = "CREATE MODULE m\n PUBLISH FUNCTION f() RETURNS INT;\nEND MODULE;"
        self.assertEqual(len(self.parser.split_for_extraction(script)), 2)

    def test_directive_changes_terminator_and_is_not_sql(self):
        script = "--#SET TERMINATOR @\nSELECT 1@\nSELECT 2@\n" "--#SET TERMINATOR ;\nSELECT 3;"
        self.assertEqual(
            self.parser.split_for_extraction(script), ["SELECT 1", "SELECT 2", "SELECT 3"]
        )
        self.assertEqual(sum(r.kind == "directive" for r in self.parser.split(script)), 2)

    def test_lexemes_keep_internal_semicolons(self):
        scripts = (
            "SELECT 'a;b';\nSELECT 1;",
            'SELECT "col;name";\nSELECT 1;',
            "SELECT 'O''Brien';\nSELECT 1;",
            "SELECT /* a; */ 1;\nSELECT 2;",
            "SELECT 1; -- comment;\nSELECT 2;",
        )
        for script in scripts:
            with self.subTest(script=script):
                self.assertEqual(len(self.parser.split_for_extraction(script)), 2)
        self.assertEqual(self.parser.split_for_extraction(""), [])
        self.assertEqual(self.parser.split_for_extraction("SELECT 1"), ["SELECT 1"])
        self.assertEqual(self.parser.split_for_extraction("-- comment;"), [])

    def test_mid_line_semicolon_is_refused_before_the_driver_can_drop_sql(self):
        from dblift.core.exceptions import UnsafeStatementSplitError

        for script in ("SELECT 1; SELECT 2;", "SELECT 'a;b'; SELECT 1;"):
            with self.subTest(script=script):
                with self.assertRaises(UnsafeStatementSplitError):
                    self.parser.split_for_extraction(script)


class TestParseSql(unittest.TestCase):
    def setUp(self):
        self.parser = facts_parser("db2")

    def test_parse_empty(self):
        result = self.parser.parse_sql("")
        self.assertIsInstance(result, ParseResult)

    def test_parse_simple_create_table(self):
        sql = "CREATE TABLE t (id INTEGER PRIMARY KEY);"
        result = self.parser.parse_sql(sql)
        self.assertIsInstance(result, ParseResult)
        self.assertTrue(result.success)
        self.assertGreaterEqual(len(result.statements), 1)

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
        sql = (
            "CREATE TABLE a (id INTEGER);\nCREATE TABLE b (id INTEGER);\nINSERT INTO a VALUES (1);"
        )
        result = self.parser.parse_sql(sql)
        self.assertTrue(result.success)
        self.assertGreaterEqual(len(result.statements), 3)


class TestValidateSql(unittest.TestCase):
    def setUp(self):
        self.parser = facts_parser("db2")

    def test_valid_simple_sql(self):
        sql = "CREATE TABLE t (id INTEGER PRIMARY KEY);"
        result = self.parser.validate_sql(sql)
        self.assertTrue(result["valid"])

    def test_unmatched_quoted_identifier(self):
        sql = 'CREATE TABLE "test (id INTEGER);'
        result = self.parser.validate_sql(sql)
        self.assertFalse(result["valid"])
        self.assertIn("inside a string or a quoted identifier", result["errors"][0])

    def test_unmatched_begin_end(self):
        sql = "BEGIN ATOMIC INSERT INTO t VALUES (1);"
        result = self.parser.validate_sql(sql)
        self.assertFalse(result["valid"])
        self.assertIn("routine body", result["errors"][0])


class TestIntegration(unittest.TestCase):
    def setUp(self):
        self.parser = facts_parser("db2")

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
        sql = "--#SET TERMINATOR @\nSELECT 1@\nSELECT 2@\nSELECT 3@"
        stmts = self.parser.split_statements(sql)
        self.assertEqual(len(stmts), 3)

    def test_nested_quoted_in_string(self):
        sql = "SELECT 'O''Brien' FROM t;\nINSERT INTO t VALUES ('Jones');"
        stmts = self.parser.split_statements(sql)
        self.assertGreaterEqual(len(stmts), 2)


if __name__ == "__main__":
    unittest.main()
