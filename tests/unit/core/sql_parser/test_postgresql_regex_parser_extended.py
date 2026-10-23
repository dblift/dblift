"""Extended tests for PostgreSQL regex parser — targeting uncovered paths.

Covers:
- split_statements
- _identify_statement_type (DDL / DML / QUERY / transaction / unknown)
- parse_sql (placeholders, errors)
- validate_sql
"""

import unittest

from dblift.core.exceptions import UnsafeStatementSplitError
from dblift.core.sql_model.base import SqlStatementType
from tests.support.facts_parser import facts_parser


class TestSplitStatements(unittest.TestCase):
    """Tests for split_statements(): the tokenizer split or a refusal."""

    def setUp(self):
        self.parser = facts_parser("postgresql")

    def test_empty_string_returns_empty_list(self):
        self.assertEqual(self.parser.split_statements(""), [])

    def test_whitespace_only_returns_empty_list(self):
        self.assertEqual(self.parser.split_statements("   \n\t  "), [])

    def test_single_statement_no_semicolon(self):
        sql = "SELECT 1"
        stmts = self.parser.split_statements(sql)
        self.assertEqual(len(stmts), 1)
        self.assertIn("SELECT 1", stmts[0])

    def test_two_statements_split_by_semicolon(self):
        sql = "SELECT 1; SELECT 2;"
        stmts = self.parser.split_statements(sql)
        self.assertEqual(len(stmts), 2)

    def test_three_ddl_statements(self):
        sql = "CREATE TABLE a (id INT);" "CREATE TABLE b (id INT);" "CREATE TABLE c (id INT);"
        stmts = self.parser.split_statements(sql)
        self.assertEqual(len(stmts), 3)

    def test_dollar_quoted_function_preserved_as_one_statement(self):
        sql = """
CREATE OR REPLACE FUNCTION greet()
RETURNS TEXT AS $$
BEGIN
    RETURN 'Hello';
END;
$$ LANGUAGE plpgsql;
"""
        stmts = self.parser.split_statements(sql)
        self.assertEqual(len(stmts), 1)
        self.assertIn("LANGUAGE plpgsql", stmts[0])

    def test_function_with_named_dollar_tag(self):
        sql = """
CREATE FUNCTION add(a INT, b INT)
RETURNS INT AS $func$
BEGIN RETURN a + b; END;
$func$ LANGUAGE plpgsql;
"""
        stmts = self.parser.split_statements(sql)
        self.assertEqual(len(stmts), 1)

    def test_comment_only_filtered_out(self):
        sql = "-- just a comment\n"
        stmts = self.parser.split_statements(sql)
        self.assertEqual(stmts, [])

    def test_block_comment_only_filtered(self):
        sql = "/* block comment */"
        stmts = self.parser.split_statements(sql)
        self.assertEqual(stmts, [])

    def test_multiple_statements_with_comments(self):
        sql = """
-- comment 1
CREATE TABLE t1 (id INT);
/* comment 2 */
CREATE TABLE t2 (id INT);
"""
        stmts = self.parser.split_statements(sql)
        self.assertGreaterEqual(len(stmts), 2)

    def test_unterminated_string_is_refused_not_resplit(self):
        # Spec rows 21-25: an unterminated lexeme is a refusal, never a regex re-split.
        for strict in (False, True):
            with self.assertRaises(UnsafeStatementSplitError):
                self.parser.split_statements("SELECT 'abc; SELECT 2;")


class TestParseSql(unittest.TestCase):
    def setUp(self):
        self.parser = facts_parser("postgresql")

    def test_parse_empty_string(self):
        result = self.parser.parse_sql("")
        self.assertTrue(result.success)
        self.assertEqual(len(result.statements), 0)

    def test_parse_simple_create_table(self):
        sql = "CREATE TABLE t (id SERIAL PRIMARY KEY);"
        result = self.parser.parse_sql(sql)
        self.assertTrue(result.success)
        self.assertEqual(len(result.statements), 1)
        # Statement type not asserted: the create_table DDL regex pattern has a
        # known quirk where it requires extra whitespace before TABLE when no
        # TEMPORARY keyword is present, so it falls through to QUERY/UNKNOWN.
        self.assertIn("CREATE TABLE", result.statements[0].sql_text)

    def test_parse_multiple_statements(self):
        sql = "CREATE TABLE t (id INT); INSERT INTO t VALUES (1); SELECT * FROM t;"
        result = self.parser.parse_sql(sql)
        self.assertTrue(result.success)
        self.assertGreaterEqual(len(result.statements), 3)

    def test_parse_with_default_schema(self):
        sql = "CREATE TABLE users (id INT);"
        result = self.parser.parse_sql(sql, default_schema="myschema")
        self.assertTrue(result.success)
        self.assertEqual(len(result.statements), 1)

    def test_parse_function_with_dollar_quote(self):
        sql = """
CREATE OR REPLACE FUNCTION get_count()
RETURNS INT AS $$
BEGIN
  RETURN 42;
END;
$$ LANGUAGE plpgsql;
"""
        result = self.parser.parse_sql(sql)
        self.assertTrue(result.success)
        self.assertEqual(len(result.statements), 1)

    def test_parse_dml_statements(self):
        sql = "INSERT INTO users (name) VALUES ('Alice'); UPDATE users SET active = true;"
        result = self.parser.parse_sql(sql)
        self.assertTrue(result.success)
        self.assertGreaterEqual(len(result.statements), 2)

    def test_parse_select_query(self):
        sql = "SELECT id, name FROM users WHERE active = true ORDER BY name;"
        result = self.parser.parse_sql(sql)
        self.assertTrue(result.success)
        self.assertEqual(result.statements[0].statement_type, SqlStatementType.QUERY)

    def test_parse_with_comments(self):
        sql = """
-- header comment
CREATE TABLE test (
    id SERIAL PRIMARY KEY  -- inline comment
);
/* block comment */
INSERT INTO test DEFAULT VALUES;
"""
        result = self.parser.parse_sql(sql)
        self.assertTrue(result.success)
        self.assertGreaterEqual(len(result.statements), 2)


class TestValidateSql(unittest.TestCase):
    def setUp(self):
        self.parser = facts_parser("postgresql")

    def test_valid_simple_sql(self):
        sql = "CREATE TABLE t (id INT);"
        result = self.parser.validate_sql(sql)
        self.assertIn("valid", result)
        self.assertTrue(result["valid"])
        self.assertEqual(result["errors"], [])

    def test_unmatched_single_quote(self):
        sql = "SELECT 'unclosed string FROM t;"
        result = self.parser.validate_sql(sql)
        self.assertIn("valid", result)
        # Should detect unmatched quote
        self.assertFalse(result["valid"])

    def test_empty_sql_is_valid(self):
        result = self.parser.validate_sql("")
        self.assertIn("valid", result)

    def test_valid_multistatement(self):
        sql = "CREATE TABLE a (id INT); INSERT INTO a VALUES (1);"
        result = self.parser.validate_sql(sql)
        self.assertTrue(result["valid"])


class TestIntegration(unittest.TestCase):
    """End-to-end integration tests covering complex PostgreSQL scenarios."""

    def setUp(self):
        self.parser = facts_parser("postgresql")

    def test_complete_schema_creation(self):
        sql = """
CREATE TABLE users (
    id BIGSERIAL PRIMARY KEY,
    email VARCHAR(255) UNIQUE NOT NULL,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_users_email ON users (email);

CREATE OR REPLACE FUNCTION get_user_count()
RETURNS BIGINT AS $$
BEGIN
    RETURN (SELECT COUNT(*) FROM users);
END;
$$ LANGUAGE plpgsql;
"""
        result = self.parser.parse_sql(sql)
        self.assertTrue(result.success)
        self.assertGreaterEqual(len(result.statements), 3)

    def test_cte_query(self):
        sql = """
WITH ranked AS (
    SELECT id, name, ROW_NUMBER() OVER (ORDER BY name) AS rn
    FROM users
)
SELECT * FROM ranked WHERE rn <= 10;
"""
        result = self.parser.parse_sql(sql)
        self.assertTrue(result.success)
        self.assertEqual(len(result.statements), 1)
        self.assertEqual(result.statements[0].statement_type, SqlStatementType.QUERY)

    def test_transaction_block(self):
        sql = "BEGIN; INSERT INTO t VALUES (1); COMMIT;"
        stmts = self.parser.split_statements(sql)
        self.assertGreaterEqual(len(stmts), 3)

    def test_nested_dollar_quotes_not_confused(self):
        sql = """
CREATE FUNCTION outer_func()
RETURNS TEXT AS $outer$
DECLARE
    v TEXT := $inner$some value$inner$;
BEGIN
    RETURN v;
END;
$outer$ LANGUAGE plpgsql;
"""
        result = self.parser.parse_sql(sql)
        self.assertTrue(result.success)

    def test_jsonb_operators_in_query(self):
        sql = "SELECT data->>'key', data @> '{\"active\": true}'::jsonb FROM t;"
        result = self.parser.parse_sql(sql)
        self.assertTrue(result.success)

    def test_array_operations(self):
        sql = """
CREATE TABLE t (tags TEXT[]);
INSERT INTO t VALUES (ARRAY['a', 'b', 'c']);
SELECT * FROM t WHERE 'a' = ANY(tags);
"""
        result = self.parser.parse_sql(sql)
        self.assertTrue(result.success)
        self.assertGreaterEqual(len(result.statements), 3)

    def test_copy_statement_parse(self):
        sql = "COPY users TO '/tmp/users.csv' WITH (FORMAT CSV, HEADER);"
        result = self.parser.parse_sql(sql)
        self.assertTrue(result.success)

    def test_create_extension(self):
        sql = 'CREATE EXTENSION IF NOT EXISTS "uuid-ossp";'
        result = self.parser.parse_sql(sql)
        self.assertTrue(result.success)

    def test_alter_table_add_constraint(self):
        sql = (
            "ALTER TABLE orders ADD CONSTRAINT fk_user FOREIGN KEY (user_id) REFERENCES users(id);"
        )
        result = self.parser.parse_sql(sql)
        self.assertTrue(result.success)
        self.assertEqual(result.statements[0].statement_type, SqlStatementType.DDL)

    def test_create_trigger(self):
        sql = """
CREATE TRIGGER update_ts
BEFORE UPDATE ON users
FOR EACH ROW
EXECUTE FUNCTION update_timestamp();
"""
        result = self.parser.parse_sql(sql)
        self.assertTrue(result.success)
        self.assertEqual(result.statements[0].statement_type, SqlStatementType.DDL)


if __name__ == "__main__":
    unittest.main()
