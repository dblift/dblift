"""Extended tests for SQL Server regex parser — targeting uncovered paths.

Covers:
- split_statements: tokenizer path and fallback (GO, intelligent batch split)
- _split_sqlserver_with_go
- _split_batch_intelligently (DDL detection, multiple DDL, single DDL, non-DDL)
- _split_non_ddl_statements
- _find_safe_semicolon_splits (strings, identifiers, comments)
- parse_sql (default schema, delegation)
- validate_sql
"""

import unittest

from db.plugins.sqlserver.parser.sqlserver_regex_parser import SqlServerRegexParser


class TestSplitStatements(unittest.TestCase):
    def setUp(self):
        self.parser = SqlServerRegexParser()

    def test_empty_returns_empty(self):
        self.assertEqual(self.parser.split_statements(""), [])

    def test_whitespace_only_returns_empty(self):
        self.assertEqual(self.parser.split_statements("   \n  "), [])

    def test_simple_select(self):
        sql = "SELECT 1"
        stmts = self.parser.split_statements(sql)
        self.assertGreaterEqual(len(stmts), 1)

    def test_go_batch_separator(self):
        sql = "SELECT 1\nGO\nSELECT 2\nGO"
        stmts = self.parser.split_statements(sql)
        self.assertGreaterEqual(len(stmts), 2)

    def test_go_case_insensitive(self):
        sql = "SELECT 1\ngo\nSELECT 2"
        stmts = self.parser.split_statements(sql)
        self.assertGreaterEqual(len(stmts), 2)

    def test_create_table_single_ddl(self):
        sql = "CREATE TABLE users (id INT PRIMARY KEY, name NVARCHAR(100));"
        stmts = self.parser.split_statements(sql)
        self.assertEqual(len(stmts), 1)

    def test_multiple_ddl_statements(self):
        sql = "CREATE TABLE a (id INT);\n" "CREATE TABLE b (id INT);\n"
        stmts = self.parser.split_statements(sql)
        self.assertGreaterEqual(len(stmts), 2)

    def test_go_with_trailing_comment(self):
        sql = "SELECT 1\nGO -- end of batch\nSELECT 2"
        stmts = self.parser.split_statements(sql)
        self.assertGreaterEqual(len(stmts), 2)

    def test_create_procedure_with_go(self):
        sql = (
            "CREATE PROCEDURE get_users AS\n" "BEGIN\n" "    SELECT * FROM users;\n" "END\n" "GO\n"
        )
        stmts = self.parser.split_statements(sql)
        self.assertGreaterEqual(len(stmts), 1)
        proc = next((s for s in stmts if "CREATE PROCEDURE" in s), None)
        self.assertIsNotNone(proc)


class TestSplitSqlServerWithGo(unittest.TestCase):
    def setUp(self):
        self.parser = SqlServerRegexParser()

    def test_single_go_separator(self):
        sql = "SELECT 1\nGO\nSELECT 2"
        stmts = self.parser._split_sqlserver_with_go(sql)
        self.assertEqual(len(stmts), 2)

    def test_multiple_go_separators(self):
        sql = "SELECT 1\nGO\nSELECT 2\nGO\nSELECT 3"
        stmts = self.parser._split_sqlserver_with_go(sql)
        self.assertEqual(len(stmts), 3)

    def test_empty_batch_skipped(self):
        sql = "\nGO\nSELECT 1\nGO"
        stmts = self.parser._split_sqlserver_with_go(sql)
        self.assertEqual(len(stmts), 1)

    def test_comment_only_batch_skipped(self):
        sql = "-- comment\nGO\nSELECT 1"
        stmts = self.parser._split_sqlserver_with_go(sql)
        # Comment-only batch skipped, real statement kept
        self.assertGreaterEqual(len(stmts), 1)
        self.assertTrue(any("SELECT 1" in s for s in stmts))

    def test_go_line_with_comment_is_separator(self):
        sql = "SELECT 1\nGO -- batch end\nSELECT 2"
        stmts = self.parser._split_sqlserver_with_go(sql)
        self.assertEqual(len(stmts), 2)

    def test_ddl_in_go_batch(self):
        sql = "CREATE TABLE t1 (id INT)\n" "GO\n" "CREATE TABLE t2 (id INT)\n" "GO\n"
        stmts = self.parser._split_sqlserver_with_go(sql)
        self.assertGreaterEqual(len(stmts), 2)
        self.assertTrue(any("t1" in s for s in stmts))
        self.assertTrue(any("t2" in s for s in stmts))


class TestSplitBatchIntelligently(unittest.TestCase):
    def setUp(self):
        self.parser = SqlServerRegexParser()

    def test_empty_batch_returns_empty(self):
        stmts = self.parser._split_batch_intelligently("")
        self.assertEqual(stmts, [])

    def test_single_ddl_returns_as_is(self):
        batch = "CREATE TABLE users (id INT, name NVARCHAR(100))"
        stmts = self.parser._split_batch_intelligently(batch)
        self.assertEqual(len(stmts), 1)
        self.assertIn("CREATE TABLE", stmts[0])

    def test_multiple_ddl_split_at_keywords(self):
        batch = "CREATE TABLE a (id INT)\n" "CREATE TABLE b (id INT)\n"
        stmts = self.parser._split_batch_intelligently(batch)
        self.assertEqual(len(stmts), 2)

    def test_create_procedure_ddl(self):
        batch = "CREATE PROCEDURE p AS BEGIN SELECT 1; END"
        stmts = self.parser._split_batch_intelligently(batch)
        self.assertEqual(len(stmts), 1)
        self.assertIn("CREATE PROCEDURE", stmts[0])

    def test_create_or_alter_table(self):
        batch = "CREATE OR ALTER TABLE t (id INT)\nCREATE TABLE t2 (id INT)"
        stmts = self.parser._split_batch_intelligently(batch)
        self.assertEqual(len(stmts), 2)

    def test_alter_table(self):
        batch = "ALTER TABLE users ADD COLUMN email NVARCHAR(255)"
        stmts = self.parser._split_batch_intelligently(batch)
        self.assertEqual(len(stmts), 1)

    def test_drop_table(self):
        batch = "DROP TABLE IF EXISTS users\nDROP TABLE IF EXISTS orders"
        stmts = self.parser._split_batch_intelligently(batch)
        self.assertEqual(len(stmts), 2)

    def test_create_index(self):
        batch = (
            "CREATE INDEX idx_users ON users (email)\nCREATE INDEX idx_orders ON orders (user_id)"
        )
        stmts = self.parser._split_batch_intelligently(batch)
        self.assertEqual(len(stmts), 2)

    def test_non_ddl_split_by_semicolon(self):
        batch = "SELECT 1; SELECT 2; SELECT 3"
        stmts = self.parser._split_batch_intelligently(batch)
        self.assertGreaterEqual(len(stmts), 2)

    def test_create_view(self):
        batch = "CREATE VIEW v AS SELECT 1\nCREATE VIEW v2 AS SELECT 2"
        stmts = self.parser._split_batch_intelligently(batch)
        self.assertEqual(len(stmts), 2)

    def test_create_trigger(self):
        batch = "CREATE TRIGGER t ON users AFTER INSERT AS BEGIN SELECT 1; END"
        stmts = self.parser._split_batch_intelligently(batch)
        self.assertEqual(len(stmts), 1)

    def test_create_function(self):
        batch = "CREATE FUNCTION fn() RETURNS INT AS BEGIN RETURN 1; END\nCREATE FUNCTION fn2() RETURNS INT AS BEGIN RETURN 2; END"
        stmts = self.parser._split_batch_intelligently(batch)
        self.assertEqual(len(stmts), 2)


class TestSplitNonDdlStatements(unittest.TestCase):
    def setUp(self):
        self.parser = SqlServerRegexParser()

    def test_empty_returns_empty(self):
        self.assertEqual(self.parser._split_non_ddl_statements(""), [])

    def test_no_semicolons_returns_whole(self):
        batch = "SELECT 1 FROM t"
        stmts = self.parser._split_non_ddl_statements(batch)
        self.assertEqual(len(stmts), 1)

    def test_multiple_semicolons(self):
        batch = "SELECT 1; SELECT 2; SELECT 3;"
        stmts = self.parser._split_non_ddl_statements(batch)
        self.assertGreaterEqual(len(stmts), 3)

    def test_semicolon_inside_string_not_split(self):
        batch = "SELECT 'a;b'; SELECT 1;"
        stmts = self.parser._split_non_ddl_statements(batch)
        self.assertEqual(len(stmts), 2)
        self.assertIn("'a;b'", stmts[0])

    def test_semicolon_inside_bracket_identifier_not_split(self):
        batch = "SELECT [col;name]; SELECT 1;"
        stmts = self.parser._split_non_ddl_statements(batch)
        self.assertEqual(len(stmts), 2)
        self.assertIn("[col;name]", stmts[0])

    def test_remaining_after_last_semicolon_added(self):
        batch = "SELECT 1; SELECT 2"
        stmts = self.parser._split_non_ddl_statements(batch)
        self.assertEqual(len(stmts), 2)


class TestFindSafeSemicolonSplits(unittest.TestCase):
    def setUp(self):
        self.parser = SqlServerRegexParser()

    def test_simple_semicolons(self):
        sql = "SELECT 1; SELECT 2;"
        indices = self.parser._find_safe_semicolon_splits(sql)
        self.assertEqual(len(indices), 2)

    def test_semicolon_in_string_not_included(self):
        sql = "SELECT 'a;b'; SELECT 2;"
        indices = self.parser._find_safe_semicolon_splits(sql)
        self.assertEqual(len(indices), 2)
        # First index should be after the closing quote
        first_semi = sql.index(";", sql.index("'a;b'") + len("'a;b'"))
        self.assertIn(first_semi, indices)

    def test_semicolon_in_bracket_identifier_not_included(self):
        sql = "SELECT [col;name]; SELECT 1;"
        indices = self.parser._find_safe_semicolon_splits(sql)
        # Should not include the one inside [...]
        self.assertEqual(len(indices), 2)

    def test_semicolon_in_line_comment_not_included(self):
        sql = "SELECT 1; -- comment;\nSELECT 2;"
        indices = self.parser._find_safe_semicolon_splits(sql)
        # Comment semicolon excluded
        self.assertEqual(len(indices), 2)

    def test_semicolon_in_block_comment_not_included(self):
        sql = "SELECT 1; /* ; */ SELECT 2;"
        indices = self.parser._find_safe_semicolon_splits(sql)
        # Block comment semicolon excluded
        self.assertEqual(len(indices), 2)

    def test_no_semicolons_returns_empty(self):
        sql = "SELECT 1 FROM t"
        indices = self.parser._find_safe_semicolon_splits(sql)
        self.assertEqual(indices, [])

    def test_string_toggle(self):
        # Toggle in and out of string
        sql = "SELECT 'open'; SELECT 'close';"
        indices = self.parser._find_safe_semicolon_splits(sql)
        self.assertEqual(len(indices), 2)


class TestParseSql(unittest.TestCase):
    def setUp(self):
        self.parser = SqlServerRegexParser()

    def test_parse_simple_create_table(self):
        sql = "CREATE TABLE users (id INT PRIMARY KEY, name NVARCHAR(100));"
        result = self.parser.parse_sql(sql)
        self.assertIsNotNone(result)
        self.assertGreaterEqual(len(result.statements), 1)

    def test_parse_with_default_schema_dbo(self):
        # default_schema=None should use 'dbo'
        sql = "SELECT * FROM users;"
        result = self.parser.parse_sql(sql)
        self.assertIsNotNone(result)

    def test_parse_with_explicit_schema(self):
        sql = "SELECT * FROM users;"
        result = self.parser.parse_sql(sql, default_schema="hr")
        self.assertIsNotNone(result)
        self.assertGreaterEqual(len(result.statements), 1)

    def test_parse_go_batches(self):
        sql = "SELECT 1\nGO\nSELECT 2\nGO"
        result = self.parser.parse_sql(sql)
        self.assertIsNotNone(result)
        self.assertGreaterEqual(len(result.statements), 2)

    def test_parse_procedure(self):
        sql = "CREATE PROCEDURE get_users AS\n" "BEGIN\n" "    SELECT * FROM users;\n" "END\n"
        result = self.parser.parse_sql(sql)
        self.assertIsNotNone(result)

    def test_parse_empty_sql(self):
        result = self.parser.parse_sql("")
        self.assertIsNotNone(result)

    def test_parse_alter_table(self):
        sql = "ALTER TABLE users ADD email NVARCHAR(255);"
        result = self.parser.parse_sql(sql)
        self.assertGreaterEqual(len(result.statements), 1)

    def test_parse_drop_statements(self):
        sql = "DROP TABLE IF EXISTS old_table; DROP INDEX idx_old ON users;"
        result = self.parser.parse_sql(sql)
        self.assertGreaterEqual(len(result.statements), 2)


class TestValidateSql(unittest.TestCase):
    def setUp(self):
        self.parser = SqlServerRegexParser()

    def test_valid_sql(self):
        sql = "CREATE TABLE t (id INT PRIMARY KEY);"
        result = self.parser.validate_sql(sql)
        self.assertTrue(result["valid"])
        self.assertEqual(result["errors"], [])

    def test_valid_go_batch(self):
        sql = "SELECT 1\nGO\nSELECT 2"
        result = self.parser.validate_sql(sql)
        self.assertTrue(result["valid"])

    def test_statement_count(self):
        sql = "SELECT 1; SELECT 2;"
        result = self.parser.validate_sql(sql)
        self.assertIn("statements_found", result)
        self.assertGreaterEqual(result["statements_found"], 2)

    def test_empty_sql(self):
        result = self.parser.validate_sql("")
        self.assertIn("valid", result)
        # Empty sql returns 0 statements
        self.assertEqual(result["statements_found"], 0)

    def test_whitespace_only_sql(self):
        result = self.parser.validate_sql("   \n  ")
        self.assertIn("valid", result)

    def test_multiple_ddl_statements(self):
        sql = (
            "CREATE TABLE a (id INT);\n"
            "CREATE TABLE b (id INT);\n"
            "ALTER TABLE a ADD name VARCHAR(100);\n"
        )
        result = self.parser.validate_sql(sql)
        self.assertTrue(result["valid"])
        self.assertGreaterEqual(result["statements_found"], 3)


class TestDialectName(unittest.TestCase):
    def test_dialect_name_is_sqlserver(self):
        parser = SqlServerRegexParser()
        self.assertEqual(parser.dialect_name, "sqlserver")


class TestIntegration(unittest.TestCase):
    def setUp(self):
        self.parser = SqlServerRegexParser()

    def test_complete_script_with_go(self):
        sql = """
USE master;
GO

CREATE TABLE dbo.employees (
    id INT IDENTITY(1,1) PRIMARY KEY,
    name NVARCHAR(200) NOT NULL,
    hire_date DATE DEFAULT GETDATE()
);
GO

CREATE INDEX idx_emp_name ON dbo.employees (name);
GO

INSERT INTO dbo.employees (name, hire_date) VALUES ('Alice', '2024-01-01');
GO
"""
        result = self.parser.parse_sql(sql)
        self.assertIsNotNone(result)
        self.assertGreaterEqual(len(result.statements), 4)

    def test_create_procedure_and_call(self):
        sql = """
CREATE PROCEDURE dbo.get_employees
AS
BEGIN
    SET NOCOUNT ON;
    SELECT * FROM dbo.employees ORDER BY name;
END
GO

EXEC dbo.get_employees;
GO
"""
        result = self.parser.parse_sql(sql)
        self.assertIsNotNone(result)

    def test_multiple_alter_table_statements(self):
        sql = """
ALTER TABLE users ADD email NVARCHAR(255);
ALTER TABLE users ADD phone NVARCHAR(20);
ALTER TABLE users ADD created_at DATETIME DEFAULT GETDATE();
"""
        stmts = self.parser.split_statements(sql)
        self.assertGreaterEqual(len(stmts), 3)

    def test_create_view_and_select(self):
        sql = "CREATE VIEW active_users AS SELECT * FROM users WHERE active = 1;\nSELECT * FROM active_users;"
        stmts = self.parser.split_statements(sql)
        self.assertGreaterEqual(len(stmts), 2)

    def test_transaction_statements(self):
        sql = "BEGIN TRANSACTION; INSERT INTO t VALUES (1); COMMIT;"
        stmts = self.parser.split_statements(sql)
        self.assertGreaterEqual(len(stmts), 1)

    def test_cte_query(self):
        sql = """
WITH ranked AS (
    SELECT id, name, ROW_NUMBER() OVER (ORDER BY name) AS rn
    FROM users
)
SELECT * FROM ranked WHERE rn <= 10;
"""
        result = self.parser.parse_sql(sql)
        self.assertIsNotNone(result)


if __name__ == "__main__":
    unittest.main()
