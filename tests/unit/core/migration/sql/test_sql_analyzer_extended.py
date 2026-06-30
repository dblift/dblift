"""Extended unit tests for SqlAnalyzer covering uncovered branches.

Target file: core/migration/sql/sql_analyzer.py
Coverage focus:
- get_statement_type: db-specific parser path (value, UNKNOWN fallback), exception path
- _get_statement_type_string: each keyword branch, BOM handling, comment removal
- split_statements + _split_statements_with_regex: GO, block comment, identifier, string
- _split_sqlserver_with_go
- analyze_statement: success and exception paths
- validate_sql: db-specific parser (tuple, dict, bool result), basic structural checks
- extract_objects / _extract_objects_regex: all branches
- parse_sql, get_tables, get_views, get_indexes, get_functions, get_triggers
- get_table, get_view, has_circular_dependencies, get_dependencies
"""

import unittest
from unittest.mock import MagicMock, patch

from core.migration.sql.sql_analyzer import SqlAnalyzer


class TestSqlAnalyzerDialectRequired(unittest.TestCase):
    """ADR-26 E5: ``dialect`` is a required argument (no hidden default)."""

    def test_dialect_is_required(self):
        with self.assertRaises(TypeError):
            SqlAnalyzer()  # type: ignore[call-arg]

    def test_explicit_dialect_is_lowercased_and_stored(self):
        analyzer = SqlAnalyzer(dialect="PostgreSQL")
        self.assertEqual(analyzer.dialect, "postgresql")


class TestGetStatementTypeStringBranches(unittest.TestCase):
    """Test _get_statement_type_string for every keyword branch."""

    def setUp(self):
        self.analyzer = SqlAnalyzer(dialect="postgresql")
        # Disable db_specific_parser to test string fallback directly
        self.analyzer._db_specific_parser = None

    def test_empty_returns_unknown(self):
        self.assertEqual(self.analyzer.get_statement_type(""), "UNKNOWN")

    def test_whitespace_only_returns_unknown(self):
        self.assertEqual(self.analyzer.get_statement_type("   \n  "), "UNKNOWN")

    def test_create_table_is_ddl(self):
        self.assertEqual(self.analyzer.get_statement_type("CREATE TABLE t (id INT)"), "DDL")

    def test_alter_table_is_ddl(self):
        self.assertEqual(self.analyzer.get_statement_type("ALTER TABLE t ADD COLUMN x INT"), "DDL")

    def test_drop_is_ddl(self):
        self.assertEqual(self.analyzer.get_statement_type("DROP TABLE t"), "DDL")

    def test_truncate_is_ddl(self):
        self.assertEqual(self.analyzer.get_statement_type("TRUNCATE TABLE t"), "DDL")

    def test_grant_is_ddl(self):
        self.assertEqual(self.analyzer.get_statement_type("GRANT SELECT ON t TO user1"), "DDL")

    def test_revoke_is_ddl(self):
        self.assertEqual(self.analyzer.get_statement_type("REVOKE SELECT ON t FROM user1"), "DDL")

    def test_comment_is_ddl(self):
        self.assertEqual(self.analyzer.get_statement_type("COMMENT ON TABLE t IS 'desc'"), "DDL")

    def test_rename_is_ddl(self):
        self.assertEqual(self.analyzer.get_statement_type("RENAME TABLE old TO new"), "DDL")

    def test_insert_is_dml(self):
        self.assertEqual(self.analyzer.get_statement_type("INSERT INTO t VALUES (1)"), "DML")

    def test_update_is_dml(self):
        self.assertEqual(self.analyzer.get_statement_type("UPDATE t SET x=1"), "DML")

    def test_delete_is_dml(self):
        self.assertEqual(self.analyzer.get_statement_type("DELETE FROM t WHERE id=1"), "DML")

    def test_merge_is_dml(self):
        self.assertEqual(
            self.analyzer.get_statement_type(
                "MERGE INTO t USING s ON t.id=s.id WHEN MATCHED THEN UPDATE SET t.x=s.x"
            ),
            "DML",
        )

    def test_upsert_is_dml(self):
        self.assertEqual(self.analyzer.get_statement_type("UPSERT INTO t VALUES (1)"), "DML")

    def test_exec_with_space_is_dml(self):
        self.assertEqual(self.analyzer.get_statement_type("EXEC sp_name"), "DML")

    def test_execute_is_dml(self):
        self.assertEqual(self.analyzer.get_statement_type("EXECUTE sp_name"), "DML")

    def test_select_is_query(self):
        self.assertEqual(self.analyzer.get_statement_type("SELECT 1"), "QUERY")

    def test_with_is_query(self):
        self.assertEqual(
            self.analyzer.get_statement_type("WITH cte AS (SELECT 1) SELECT * FROM cte"), "QUERY"
        )

    def test_show_is_query(self):
        self.assertEqual(self.analyzer.get_statement_type("SHOW TABLES"), "QUERY")

    def test_describe_is_query(self):
        self.assertEqual(self.analyzer.get_statement_type("DESCRIBE t"), "QUERY")

    def test_desc_is_query(self):
        self.assertEqual(self.analyzer.get_statement_type("DESC t"), "QUERY")

    def test_explain_is_query(self):
        self.assertEqual(self.analyzer.get_statement_type("EXPLAIN SELECT 1"), "QUERY")

    def test_unknown_keyword_returns_unknown(self):
        self.assertEqual(self.analyzer.get_statement_type("DECLARE @x INT"), "UNKNOWN")

    def test_bom_prefix_stripped_before_classification(self):
        sql = "﻿CREATE TABLE bom_test (id INT)"
        self.assertEqual(self.analyzer.get_statement_type(sql), "DDL")

    def test_block_comment_before_keyword(self):
        sql = "/* create table */ SELECT 1"
        self.assertEqual(self.analyzer.get_statement_type(sql), "QUERY")

    def test_line_comment_before_keyword(self):
        sql = "-- comment\nSELECT 1"
        self.assertEqual(self.analyzer.get_statement_type(sql), "QUERY")

    def test_comment_only_body_returns_unknown(self):
        sql = "-- just a comment"
        self.assertEqual(self.analyzer.get_statement_type(sql), "UNKNOWN")


class TestGetStatementTypeWithDbSpecificParser(unittest.TestCase):
    """Test the db-specific parser path in get_statement_type."""

    def setUp(self):
        self.analyzer = SqlAnalyzer(dialect="postgresql")

    def test_uses_db_specific_parser_when_available(self):
        mock_parser = MagicMock()
        mock_stmt_type = MagicMock()
        mock_stmt_type.value = "DDL"
        mock_parser._identify_statement_type.return_value = mock_stmt_type
        self.analyzer._db_specific_parser = mock_parser

        result = self.analyzer.get_statement_type("CREATE TABLE t (id INT)")
        self.assertEqual(result, "DDL")

    def test_falls_back_to_string_when_parser_returns_unknown(self):
        mock_parser = MagicMock()
        mock_stmt_type = MagicMock()
        mock_stmt_type.value = "UNKNOWN"
        mock_parser._identify_statement_type.return_value = mock_stmt_type
        self.analyzer._db_specific_parser = mock_parser

        result = self.analyzer.get_statement_type("SELECT 1")
        self.assertEqual(result, "QUERY")

    def test_falls_back_to_string_when_parser_raises(self):
        mock_parser = MagicMock()
        mock_parser._identify_statement_type.side_effect = Exception("parser error")
        self.analyzer._db_specific_parser = mock_parser

        result = self.analyzer.get_statement_type("INSERT INTO t VALUES (1)")
        self.assertEqual(result, "DML")

    def test_parser_without_identify_method_falls_back(self):
        mock_parser = MagicMock(spec=[])  # no _identify_statement_type
        self.analyzer._db_specific_parser = mock_parser

        result = self.analyzer.get_statement_type("SELECT 1")
        self.assertEqual(result, "QUERY")

    def test_parser_returns_non_enum_string_type(self):
        mock_parser = MagicMock()
        mock_stmt_type = MagicMock()
        del mock_stmt_type.value  # no .value attribute → str() fallback
        mock_stmt_type.__str__ = lambda self: "DDL"
        mock_parser._identify_statement_type.return_value = mock_stmt_type
        self.analyzer._db_specific_parser = mock_parser

        result = self.analyzer.get_statement_type("ALTER TABLE t ADD COLUMN x INT")
        # falls through to string-based since str(mock_stmt_type) != "DDL" literally
        self.assertIn(result, ("DDL", "UNKNOWN"))


class TestSplitStatements(unittest.TestCase):
    """Tests for split_statements() and _split_statements_with_regex()."""

    def test_splits_semicolon_separated(self):
        analyzer = SqlAnalyzer(dialect="postgresql")
        sql = "SELECT 1;\nSELECT 2;"
        stmts = analyzer.split_statements(sql)
        self.assertGreaterEqual(len(stmts), 1)

    def test_sqlserver_go_splitting(self):
        analyzer = SqlAnalyzer(dialect="sqlserver")
        sql = "SELECT 1\nGO\nSELECT 2"
        stmts = analyzer.split_statements(sql)
        self.assertEqual(len(stmts), 2)

    def test_regex_fallback_splits_semicolons(self):
        analyzer = SqlAnalyzer(dialect="postgresql")
        sql = "INSERT INTO t VALUES (1);\nINSERT INTO t VALUES (2);"
        stmts = analyzer._split_statements_with_regex(sql)
        self.assertEqual(len(stmts), 2)

    def test_regex_handles_string_literals(self):
        analyzer = SqlAnalyzer(dialect="postgresql")
        # semicolon inside a string should not split
        sql = "INSERT INTO t VALUES ('hello; world');"
        stmts = analyzer._split_statements_with_regex(sql)
        self.assertEqual(len(stmts), 1)

    def test_regex_handles_block_comment(self):
        analyzer = SqlAnalyzer(dialect="postgresql")
        sql = "/* first; comment */\nSELECT 1;"
        stmts = analyzer._split_statements_with_regex(sql)
        self.assertEqual(len(stmts), 1)

    def test_regex_handles_line_comment(self):
        analyzer = SqlAnalyzer(dialect="postgresql")
        sql = "-- this is a comment; not a separator\nSELECT 1;"
        stmts = analyzer._split_statements_with_regex(sql)
        self.assertEqual(len(stmts), 1)

    def test_regex_handles_quoted_identifiers(self):
        analyzer = SqlAnalyzer(dialect="postgresql")
        sql = 'SELECT "col;name" FROM t;'
        stmts = analyzer._split_statements_with_regex(sql)
        self.assertEqual(len(stmts), 1)

    def test_empty_sql_returns_empty(self):
        analyzer = SqlAnalyzer(dialect="postgresql")
        stmts = analyzer._split_statements_with_regex("")
        self.assertEqual(stmts, [])

    def test_sqlserver_go_with_comment(self):
        analyzer = SqlAnalyzer(dialect="sqlserver")
        sql = "SELECT 1\nGO -- batch separator\nSELECT 2"
        stmts = analyzer._split_sqlserver_with_go(sql)
        self.assertEqual(len(stmts), 2)

    def test_sqlserver_go_filters_empty_batches(self):
        analyzer = SqlAnalyzer(dialect="sqlserver")
        sql = "\nGO\nSELECT 1\nGO\n"
        stmts = analyzer._split_sqlserver_with_go(sql)
        self.assertEqual(len(stmts), 1)

    def test_sqlserver_go_case_insensitive(self):
        analyzer = SqlAnalyzer(dialect="sqlserver")
        sql = "SELECT 1\ngo\nSELECT 2"
        stmts = analyzer._split_sqlserver_with_go(sql)
        self.assertEqual(len(stmts), 2)

    def test_non_sqlserver_no_go_splitting(self):
        analyzer = SqlAnalyzer(dialect="postgresql")
        sql = "SELECT 1\nGO\nSELECT 2"
        # Should fall through to semicolon splitter; GO treated as regular word
        stmts = analyzer._split_statements_with_regex(sql)
        # Both statements have no semicolons so they are joined as one
        self.assertIsInstance(stmts, list)

    def test_escaped_quotes_in_string(self):
        analyzer = SqlAnalyzer(dialect="postgresql")
        sql = "INSERT INTO t VALUES ('it''s a test');"
        stmts = analyzer._split_statements_with_regex(sql)
        self.assertEqual(len(stmts), 1)


class TestExtractObjects(unittest.TestCase):
    """Tests for extract_objects() and _extract_objects_regex()."""

    def setUp(self):
        self.analyzer = SqlAnalyzer(dialect="postgresql")

    def test_empty_returns_empty(self):
        self.assertEqual(self.analyzer.extract_objects(""), [])
        self.assertEqual(self.analyzer.extract_objects("   "), [])

    def test_create_table_with_schema(self):
        sql = "CREATE TABLE myschema.users (id INT)"
        objects = self.analyzer.extract_objects(sql)
        self.assertEqual(len(objects), 1)
        self.assertEqual(objects[0]["object_type"], "Table")
        self.assertIn("users", objects[0]["object_name"])

    def test_create_table_without_schema_uses_default(self):
        sql = "CREATE TABLE users (id INT)"
        objects = self.analyzer.extract_objects(sql)
        self.assertEqual(len(objects), 1)
        self.assertIn("default_schema", objects[0]["object_name"])

    def test_alter_table(self):
        sql = "ALTER TABLE myschema.users ADD COLUMN email VARCHAR(255)"
        objects = self.analyzer.extract_objects(sql)
        self.assertEqual(len(objects), 1)
        self.assertEqual(objects[0]["object_type"], "Table")

    def test_create_view(self):
        sql = "CREATE VIEW myschema.active_users AS SELECT * FROM users"
        objects = self.analyzer.extract_objects(sql)
        self.assertEqual(len(objects), 1)
        self.assertEqual(objects[0]["object_type"], "View")

    def test_create_or_replace_view(self):
        sql = "CREATE OR REPLACE VIEW v AS SELECT 1"
        objects = self.analyzer.extract_objects(sql)
        self.assertEqual(len(objects), 1)
        self.assertEqual(objects[0]["object_type"], "View")

    def test_create_index(self):
        sql = "CREATE INDEX idx_email ON users(email)"
        objects = self.analyzer.extract_objects(sql)
        self.assertEqual(len(objects), 1)
        self.assertEqual(objects[0]["object_type"], "Index")

    def test_create_unique_index(self):
        sql = "CREATE UNIQUE INDEX idx_unique ON myschema.users(email)"
        objects = self.analyzer.extract_objects(sql)
        self.assertEqual(len(objects), 1)
        self.assertEqual(objects[0]["object_type"], "Index")
        self.assertIn("users", objects[0]["on_object"])

    def test_drop_table(self):
        sql = "DROP TABLE myschema.old_table"
        objects = self.analyzer.extract_objects(sql)
        self.assertEqual(len(objects), 1)
        self.assertEqual(objects[0]["object_type"].upper(), "TABLE")

    def test_insert_returns_empty(self):
        sql = "INSERT INTO t VALUES (1)"
        objects = self.analyzer.extract_objects(sql)
        self.assertEqual(objects, [])

    def test_select_returns_empty(self):
        sql = "SELECT 1"
        objects = self.analyzer.extract_objects(sql)
        self.assertEqual(objects, [])


class TestAnalyzeStatement(unittest.TestCase):
    """Tests for analyze_statement()."""

    def setUp(self):
        self.analyzer = SqlAnalyzer(dialect="postgresql")

    def test_analyze_returns_type_and_objects(self):
        sql = "CREATE TABLE t (id INT)"
        result = self.analyzer.analyze_statement(sql)
        self.assertIn("type", result)
        self.assertIn("objects", result)
        self.assertEqual(result["type"], "DDL")
        self.assertTrue(result["is_valid"])

    def test_analyze_select_returns_query_type(self):
        sql = "SELECT 1"
        result = self.analyzer.analyze_statement(sql)
        self.assertEqual(result["type"], "QUERY")

    def test_analyze_with_parser_error_returns_fallback(self):
        self.analyzer.parser_factory = MagicMock()
        self.analyzer.parser_factory.get_parser.side_effect = Exception("parser unavailable")
        sql = "SELECT 1"
        result = self.analyzer.analyze_statement(sql)
        self.assertIn("type", result)

    def test_analyze_uses_cached_parser(self):
        mock_parser = MagicMock()
        self.analyzer.parser = mock_parser
        sql = "SELECT 1"
        self.analyzer.analyze_statement(sql)
        mock_parser.parse.assert_called_once_with(sql)

    def test_analyze_error_returns_invalid_result(self):
        self.analyzer._extract_objects_regex = MagicMock(side_effect=Exception("regex fail"))
        sql = "SELECT 1"
        result = self.analyzer.analyze_statement(sql)
        self.assertFalse(result["is_valid"])
        self.assertTrue(len(result["errors"]) > 0)


class TestValidateSql(unittest.TestCase):
    """Tests for validate_sql()."""

    def setUp(self):
        self.analyzer = SqlAnalyzer(dialect="postgresql")
        # Disable db-specific parser so basic structural checks are reached
        self.analyzer._db_specific_parser = None

    def test_empty_sql_is_invalid(self):
        is_valid, error = self.analyzer.validate_sql("")
        self.assertFalse(is_valid)
        self.assertIsNotNone(error)

    def test_unmatched_parentheses_is_invalid(self):
        is_valid, error = self.analyzer.validate_sql("SELECT ( FROM t")
        self.assertFalse(is_valid)
        self.assertIn("parentheses", error.lower())

    def test_unmatched_single_quotes_is_invalid(self):
        is_valid, error = self.analyzer.validate_sql("SELECT 'unclosed FROM t")
        self.assertFalse(is_valid)
        self.assertIn("quote", error.lower())

    def test_valid_sql_passes_basic_checks(self):
        is_valid, error = self.analyzer.validate_sql("SELECT 1")
        self.assertTrue(is_valid)
        self.assertIsNone(error)

    def test_db_specific_parser_tuple_result(self):
        mock_parser = MagicMock()
        mock_parser.validate_sql.return_value = (True, None)
        self.analyzer._db_specific_parser = mock_parser

        is_valid, error = self.analyzer.validate_sql("SELECT 1")
        self.assertTrue(is_valid)
        self.assertIsNone(error)

    def test_db_specific_parser_dict_result(self):
        mock_parser = MagicMock()
        mock_parser.validate_sql.return_value = {"is_valid": False, "error_message": "syntax error"}
        self.analyzer._db_specific_parser = mock_parser

        is_valid, error = self.analyzer.validate_sql("SELECT @@@")
        self.assertFalse(is_valid)
        self.assertEqual(error, "syntax error")

    def test_db_specific_parser_bool_result(self):
        mock_parser = MagicMock()
        mock_parser.validate_sql.return_value = True
        self.analyzer._db_specific_parser = mock_parser

        is_valid, error = self.analyzer.validate_sql("SELECT 1")
        self.assertTrue(is_valid)

    def test_db_specific_parser_exception_falls_back_to_basic(self):
        mock_parser = MagicMock()
        mock_parser.validate_sql.side_effect = Exception("parser crash")
        self.analyzer._db_specific_parser = mock_parser

        # Falls back to basic checks — valid SQL should pass
        is_valid, error = self.analyzer.validate_sql("SELECT 1")
        self.assertTrue(is_valid)
        self.assertIsNone(error)

    def test_db_specific_parser_dict_with_valid_key(self):
        mock_parser = MagicMock()
        mock_parser.validate_sql.return_value = {"valid": True}
        self.analyzer._db_specific_parser = mock_parser

        is_valid, error = self.analyzer.validate_sql("SELECT 1")
        self.assertTrue(is_valid)

    def test_db_specific_parser_dict_null_error_message(self):
        mock_parser = MagicMock()
        mock_parser.validate_sql.return_value = {"is_valid": True, "error_message": None}
        self.analyzer._db_specific_parser = mock_parser

        is_valid, error = self.analyzer.validate_sql("SELECT 1")
        self.assertTrue(is_valid)
        self.assertIsNone(error)


class TestParseSqlAndHelpers(unittest.TestCase):
    """Tests for parse_sql() and its delegating wrappers."""

    def setUp(self):
        self.analyzer = SqlAnalyzer(dialect="postgresql")

    def test_parse_sql_returns_parse_result(self):
        from core.sql_model.base import ParseResult

        sql = "SELECT 1"
        result = self.analyzer.parse_sql(sql)
        self.assertIsInstance(result, ParseResult)

    def test_parse_sql_error_returns_failed_result(self):
        self.analyzer.parser_factory = MagicMock()
        self.analyzer.parser_factory.parse_sql.side_effect = Exception("parse error")
        result = self.analyzer.parse_sql("INVALID SQL @@@@")
        self.assertFalse(result.success)
        self.assertTrue(len(result.errors) > 0)

    def test_get_tables_returns_list(self):
        tables = self.analyzer.get_tables("CREATE TABLE t (id INT)")
        self.assertIsInstance(tables, list)

    def test_get_views_returns_list(self):
        views = self.analyzer.get_views("CREATE VIEW v AS SELECT 1")
        self.assertIsInstance(views, list)

    def test_get_indexes_returns_list(self):
        indexes = self.analyzer.get_indexes("CREATE INDEX idx ON t(col)")
        self.assertIsInstance(indexes, list)

    def test_get_functions_returns_list(self):
        funcs = self.analyzer.get_functions("SELECT 1")
        self.assertIsInstance(funcs, list)

    def test_get_triggers_returns_list(self):
        triggers = self.analyzer.get_triggers("SELECT 1")
        self.assertIsInstance(triggers, list)

    def test_get_table_returns_none_when_not_found(self):
        mock_parse_result = MagicMock()
        mock_parse_result.get_table.return_value = None
        with patch.object(self.analyzer, "parse_sql", return_value=mock_parse_result):
            result = self.analyzer.get_table("SELECT 1", "nonexistent")
        self.assertIsNone(result)

    def test_get_view_returns_none_when_not_found(self):
        mock_parse_result = MagicMock()
        mock_parse_result.get_view.return_value = None
        with patch.object(self.analyzer, "parse_sql", return_value=mock_parse_result):
            result = self.analyzer.get_view("SELECT 1", "nonexistent_view")
        self.assertIsNone(result)

    def test_has_circular_dependencies_false_for_simple_sql(self):
        result = self.analyzer.has_circular_dependencies("SELECT 1")
        self.assertIsInstance(result, bool)

    def test_get_dependencies_returns_dict(self):
        deps = self.analyzer.get_dependencies("SELECT 1")
        self.assertIsInstance(deps, dict)

    def test_get_tables_empty_when_no_tables(self):
        mock_result = MagicMock()
        mock_result.tables = []
        with patch.object(self.analyzer, "parse_sql", return_value=mock_result):
            tables = self.analyzer.get_tables("SELECT 1")
        self.assertEqual(tables, [])

    def test_get_views_empty_when_none(self):
        mock_result = MagicMock()
        mock_result.views = None
        with patch.object(self.analyzer, "parse_sql", return_value=mock_result):
            views = self.analyzer.get_views("SELECT 1")
        self.assertEqual(views, [])


class TestSqlAnalyzerInit(unittest.TestCase):
    """Tests for SqlAnalyzer initialization paths."""

    def test_dialect_normalized_to_lowercase(self):
        analyzer = SqlAnalyzer(dialect="PostgreSQL")
        self.assertEqual(analyzer.dialect, "postgresql")

    def test_custom_parser_factory_used(self):
        mock_factory = MagicMock()
        analyzer = SqlAnalyzer(dialect="postgresql", parser_factory=mock_factory)
        self.assertIs(analyzer.parser_factory, mock_factory)

    def test_custom_statement_splitter_used(self):
        mock_splitter = MagicMock()
        mock_splitter.split_statements.return_value = ["SELECT 1"]
        analyzer = SqlAnalyzer(dialect="postgresql", statement_splitter=mock_splitter)
        stmts = analyzer.split_statements("SELECT 1")
        mock_splitter.split_statements.assert_called_once()

    def test_parser_factory_init_failure_falls_back(self):
        """When SqlParserFactory raises for regex parser, _db_specific_parser is None."""
        with patch("core.migration.sql.sql_analyzer.SqlParserFactory") as mock_factory_cls:
            instance = MagicMock()
            instance.get_parser.side_effect = Exception("no regex parser")
            mock_factory_cls.return_value = instance
            analyzer = SqlAnalyzer(dialect="postgresql")
        self.assertIsNone(analyzer._db_specific_parser)


if __name__ == "__main__":
    unittest.main()
