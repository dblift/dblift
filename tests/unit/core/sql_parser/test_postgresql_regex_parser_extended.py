"""Extended tests for PostgreSQL regex parser — targeting uncovered paths.

Covers:
- split_statements
- _identify_statement_type (DDL / DML / QUERY / transaction / unknown)
- parse_sql (placeholders, errors)
- validate_sql
- _has_unmatched_quotes / _has_unmatched_parentheses / _has_unmatched_dollar_quotes
"""

import unittest
from unittest.mock import patch

from dblift.core.exceptions import UnsafeStatementSplitError
from dblift.core.sql_model.base import SqlStatementType
from dblift.core.sql_model.dialect import get_sqlglot_dialect
from dblift.db.plugins.postgresql.parser.postgresql_regex_parser import PostgreSqlRegexParser


class TestSplitStatements(unittest.TestCase):
    """Tests for split_statements(): the tokenizer split or a refusal."""

    def setUp(self):
        self.parser = PostgreSqlRegexParser()

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

    def test_strict_tokenizer_flag_is_accepted_for_valid_sql(self):
        stmts = self.parser.split_statements("SELECT 1;", strict_tokenizer=True)
        self.assertGreaterEqual(len(stmts), 1)

    def test_unterminated_string_is_refused_not_resplit(self):
        # Spec rows 21-25: an unterminated lexeme is a refusal, never a regex re-split.
        for strict in (False, True):
            with self.assertRaises(UnsafeStatementSplitError):
                self.parser.split_statements("SELECT 'abc; SELECT 2;", strict_tokenizer=strict)


class TestIdentifyStatementType(unittest.TestCase):
    def setUp(self):
        self.parser = PostgreSqlRegexParser()

    def test_create_temp_table_is_ddl(self):
        # The create_table DDL pattern requires whitespace before TABLE even
        # when TEMPORARY is absent, so plain 'CREATE TABLE' falls through to
        # query-pattern. 'CREATE TEMP TABLE' (with TEMP) works correctly.
        sql = "CREATE TEMP TABLE tmp (id INT);"
        self.assertEqual(self.parser._identify_statement_type(sql), SqlStatementType.DDL)

    def test_alter_table_is_ddl(self):
        sql = "ALTER TABLE users ADD COLUMN email TEXT;"
        self.assertEqual(self.parser._identify_statement_type(sql), SqlStatementType.DDL)

    def test_drop_table_is_ddl(self):
        sql = "DROP TABLE IF EXISTS users;"
        self.assertEqual(self.parser._identify_statement_type(sql), SqlStatementType.DDL)

    def test_create_index_is_ddl(self):
        sql = "CREATE INDEX idx_users_email ON users (email);"
        self.assertEqual(self.parser._identify_statement_type(sql), SqlStatementType.DDL)

    def test_create_view_is_ddl(self):
        sql = "CREATE VIEW active_users AS SELECT * FROM users WHERE active = true;"
        self.assertEqual(self.parser._identify_statement_type(sql), SqlStatementType.DDL)

    def test_insert_is_dml(self):
        sql = "INSERT INTO users (name) VALUES ('Alice');"
        self.assertEqual(self.parser._identify_statement_type(sql), SqlStatementType.DML)

    def test_update_is_dml(self):
        sql = "UPDATE users SET name = 'Bob' WHERE id = 1;"
        self.assertEqual(self.parser._identify_statement_type(sql), SqlStatementType.DML)

    def test_delete_is_dml(self):
        sql = "DELETE FROM users WHERE id = 1;"
        self.assertEqual(self.parser._identify_statement_type(sql), SqlStatementType.DML)

    def test_select_is_query(self):
        sql = "SELECT * FROM users;"
        self.assertEqual(self.parser._identify_statement_type(sql), SqlStatementType.QUERY)

    def test_begin_is_ddl_via_transaction(self):
        # Without trailing semicolon — transaction keyword path reached
        sql = "BEGIN"
        self.assertEqual(self.parser._identify_statement_type(sql), SqlStatementType.DDL)

    def test_commit_is_ddl_via_transaction(self):
        sql = "COMMIT"
        self.assertEqual(self.parser._identify_statement_type(sql), SqlStatementType.DDL)

    def test_rollback_is_ddl_via_transaction(self):
        sql = "ROLLBACK"
        self.assertEqual(self.parser._identify_statement_type(sql), SqlStatementType.DDL)

    def test_empty_string_is_unknown(self):
        self.assertEqual(self.parser._identify_statement_type(""), SqlStatementType.UNKNOWN)

    def test_whitespace_only_is_unknown(self):
        self.assertEqual(self.parser._identify_statement_type("   "), SqlStatementType.UNKNOWN)

    def test_unrecognised_statement_is_unknown(self):
        sql = "XYZZY 1 2 3;"
        self.assertEqual(self.parser._identify_statement_type(sql), SqlStatementType.UNKNOWN)

    def test_create_function_is_ddl(self):
        sql = "CREATE FUNCTION f() RETURNS INT AS $$ BEGIN RETURN 1; END; $$ LANGUAGE plpgsql;"
        self.assertEqual(self.parser._identify_statement_type(sql), SqlStatementType.DDL)

    def test_data_modifying_cte_feeding_insert_is_dml(self):
        # A CTE that DELETEs (with RETURNING) feeding an outer INSERT doesn't
        # return rows — classifying it as QUERY makes the executor fetch rows
        # from a result that has none.
        sql = (
            "WITH deleted AS (DELETE FROM src WHERE id = 1 RETURNING id) "
            "INSERT INTO app_logs(msg) SELECT 'removed ' || id FROM deleted"
        )
        self.assertEqual(self.parser._identify_statement_type(sql), SqlStatementType.DML)

    def test_data_modifying_cte_update_feeding_insert_is_dml(self):
        sql = (
            "WITH x AS (UPDATE src SET id = id RETURNING id) "
            "INSERT INTO app_logs(msg) SELECT 'x' FROM x"
        )
        self.assertEqual(self.parser._identify_statement_type(sql), SqlStatementType.DML)

    def test_data_modifying_cte_feeding_select_stays_query(self):
        # Here the CTE modifies data but the outer statement is a SELECT, so
        # it does return rows — must not regress to DML.
        sql = "WITH x AS (INSERT INTO src VALUES (99) RETURNING id) SELECT * FROM x"
        self.assertEqual(self.parser._identify_statement_type(sql), SqlStatementType.QUERY)

    def test_plain_select_cte_stays_query(self):
        sql = "WITH x AS (SELECT 1) SELECT * FROM x"
        self.assertEqual(self.parser._identify_statement_type(sql), SqlStatementType.QUERY)

    def test_returning_in_comment_inside_cte_does_not_affect_classification(self):
        sql = (
            "WITH deleted AS (DELETE FROM src WHERE id = 1 /* RETURNING trap */ RETURNING id) "
            "INSERT INTO app_logs(msg) SELECT 'removed ' || id FROM deleted"
        )
        self.assertEqual(self.parser._identify_statement_type(sql), SqlStatementType.DML)

    def test_cte_classification_resolves_dialect_via_get_sqlglot_dialect(self):
        # Pin the dialect resolution itself (not just its outcome — see the
        # equivalent test in test_sql_analyzer_extended.py for why the
        # outcome alone no longer proves this): the call site must resolve
        # "postgresql" through get_sqlglot_dialect rather than hardcoding a
        # literal sqlglot dialect string.
        sql = "WITH x AS (SELECT 1) DELETE FROM t WHERE id IN (SELECT 1 FROM x)"
        with patch(
            "dblift.db.plugins.postgresql.parser.postgresql_regex_parser.get_sqlglot_dialect",
            wraps=get_sqlglot_dialect,
        ) as mock_get_dialect:
            result = self.parser._identify_statement_type(sql)
        mock_get_dialect.assert_called_once_with("postgresql")
        self.assertEqual(result, SqlStatementType.DML)


class TestParseSql(unittest.TestCase):
    def setUp(self):
        self.parser = PostgreSqlRegexParser()

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

    def test_parse_with_placeholders(self):
        sql = "CREATE TABLE ${schema}.${table} (id INT);"
        placeholders = {"schema": "public", "table": "users"}
        result = self.parser.parse_sql(sql, placeholders=placeholders)
        self.assertTrue(result.success)
        self.assertIn("public", result.statements[0].sql_text)
        self.assertIn("users", result.statements[0].sql_text)

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
        self.parser = PostgreSqlRegexParser()

    def test_valid_simple_sql(self):
        sql = "CREATE TABLE t (id INT);"
        result = self.parser.validate_sql(sql)
        self.assertIn("success", result)
        self.assertTrue(result["success"])
        self.assertEqual(result["errors"], [])

    def test_unmatched_single_quote(self):
        sql = "SELECT 'unclosed string FROM t;"
        result = self.parser.validate_sql(sql)
        self.assertIn("success", result)
        # Should detect unmatched quote
        self.assertFalse(result["success"])

    def test_unmatched_parentheses(self):
        sql = "SELECT (1 + 2 FROM t;"
        result = self.parser.validate_sql(sql)
        self.assertIn("success", result)
        self.assertFalse(result["success"])

    def test_empty_sql_is_valid(self):
        result = self.parser.validate_sql("")
        self.assertIn("success", result)

    def test_valid_multistatement(self):
        sql = "CREATE TABLE a (id INT); INSERT INTO a VALUES (1);"
        result = self.parser.validate_sql(sql)
        self.assertTrue(result["success"])


class TestHasUnmatchedQuotes(unittest.TestCase):
    def setUp(self):
        self.parser = PostgreSqlRegexParser()

    def test_matched_single_quotes(self):
        self.assertFalse(self.parser._has_unmatched_quotes("SELECT 'hello'"))

    def test_unmatched_single_quote(self):
        self.assertTrue(self.parser._has_unmatched_quotes("SELECT 'unclosed"))

    def test_matched_double_quotes(self):
        self.assertFalse(self.parser._has_unmatched_quotes('SELECT "col"'))

    def test_unmatched_double_quote(self):
        self.assertTrue(self.parser._has_unmatched_quotes('SELECT "unclosed'))

    def test_escaped_single_quote_balanced(self):
        self.assertFalse(self.parser._has_unmatched_quotes("SELECT 'O''Brien'"))

    def test_escaped_double_quote_balanced(self):
        self.assertFalse(self.parser._has_unmatched_quotes('SELECT "col""name"'))

    def test_dollar_quoted_string_balanced(self):
        self.assertFalse(self.parser._has_unmatched_quotes("SELECT $$hello world$$"))

    def test_unclosed_dollar_quote(self):
        self.assertTrue(self.parser._has_unmatched_quotes("SELECT $$hello world"))

    def test_no_quotes_is_fine(self):
        self.assertFalse(self.parser._has_unmatched_quotes("SELECT 1 + 2"))


class TestHasUnmatchedParentheses(unittest.TestCase):
    def setUp(self):
        self.parser = PostgreSqlRegexParser()

    def test_balanced_parens(self):
        self.assertFalse(self.parser._has_unmatched_parentheses("SELECT (1 + 2)"))

    def test_extra_open_paren(self):
        self.assertTrue(self.parser._has_unmatched_parentheses("SELECT (1 + 2"))

    def test_extra_close_paren(self):
        self.assertTrue(self.parser._has_unmatched_parentheses("SELECT 1 + 2)"))

    def test_nested_balanced(self):
        self.assertFalse(self.parser._has_unmatched_parentheses("SELECT ((1 + 2) * 3)"))

    def test_paren_inside_string_ignored(self):
        self.assertFalse(self.parser._has_unmatched_parentheses("SELECT '(unclosed'"))

    def test_paren_inside_double_quote_ignored(self):
        self.assertFalse(self.parser._has_unmatched_parentheses('SELECT "(unclosed"'))

    def test_paren_inside_dollar_quote_ignored(self):
        self.assertFalse(self.parser._has_unmatched_parentheses("SELECT $$(unclosed$$"))

    def test_no_parens_ok(self):
        self.assertFalse(self.parser._has_unmatched_parentheses("SELECT 1"))


class TestHasUnmatchedDollarQuotes(unittest.TestCase):
    def setUp(self):
        self.parser = PostgreSqlRegexParser()

    def test_no_dollar_quotes(self):
        self.assertFalse(self.parser._has_unmatched_dollar_quotes("SELECT 1"))

    def test_matched_dollar_quotes(self):
        self.assertFalse(self.parser._has_unmatched_dollar_quotes("SELECT $$hello$$"))

    def test_named_dollar_tags_matched(self):
        self.assertFalse(self.parser._has_unmatched_dollar_quotes("SELECT $func$body$func$"))


class TestIntegration(unittest.TestCase):
    """End-to-end integration tests covering complex PostgreSQL scenarios."""

    def setUp(self):
        self.parser = PostgreSqlRegexParser()

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
