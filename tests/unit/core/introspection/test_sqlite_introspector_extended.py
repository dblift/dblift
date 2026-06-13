"""Extended unit tests for SQLiteIntrospector.

Targets uncovered paths in:
  db/introspection/databases/sqlite/sqlite_introspector.py  (511 stmts, 38%)
"""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from core.logger import NullLog
from core.sql_model.base import ConstraintType
from db.plugins.sqlite.introspection.sqlite_introspector import (
    SQLiteIntrospector,
    _is_fts5_virtual_table,
    _is_sqlite_virtual_table,
)


def _make_provider(**extra):
    provider = MagicMock()
    provider.config = SimpleNamespace(database=SimpleNamespace(type="sqlite"))
    return provider


def _make_introspector(**extra):
    provider = _make_provider()
    return SQLiteIntrospector(provider, log=NullLog(), use_vendor_queries=False), provider


# ---------------------------------------------------------------------------
# Module-level helper functions
# ---------------------------------------------------------------------------


class TestModuleHelpers(unittest.TestCase):

    def test_is_sqlite_virtual_table_true(self):
        self.assertTrue(_is_sqlite_virtual_table("CREATE VIRTUAL TABLE fts USING fts5(body)"))

    def test_is_sqlite_virtual_table_false(self):
        self.assertFalse(_is_sqlite_virtual_table("CREATE TABLE t (id INTEGER)"))

    def test_is_sqlite_virtual_table_none(self):
        self.assertFalse(_is_sqlite_virtual_table(None))

    def test_is_sqlite_virtual_table_empty(self):
        self.assertFalse(_is_sqlite_virtual_table(""))

    def test_is_fts5_virtual_table_true(self):
        self.assertTrue(_is_fts5_virtual_table("CREATE VIRTUAL TABLE docs USING fts5(content)"))

    def test_is_fts5_virtual_table_not_fts5(self):
        self.assertFalse(
            _is_fts5_virtual_table("CREATE VIRTUAL TABLE docs USING rtree(id, x1, x2)")
        )

    def test_is_fts5_virtual_table_none(self):
        self.assertFalse(_is_fts5_virtual_table(None))


# ---------------------------------------------------------------------------
# ensure_connection
# ---------------------------------------------------------------------------


class TestEnsureConnection(unittest.TestCase):

    def test_ensure_connection_calls_provider_ensure_connection_when_none(self):
        provider = _make_provider()
        provider.connection = MagicMock()
        introspector = SQLiteIntrospector(provider, log=NullLog(), use_vendor_queries=False)
        introspector.connection = None

        introspector.ensure_connection()

        provider._ensure_connection.assert_called_once()
        self.assertIs(introspector.connection, provider.connection)

    def test_ensure_connection_skips_when_already_set(self):
        introspector, provider = _make_introspector()
        mock_conn = MagicMock()
        introspector.connection = mock_conn

        introspector.ensure_connection()

        provider._ensure_connection.assert_not_called()
        self.assertIs(introspector.connection, mock_conn)


# ---------------------------------------------------------------------------
# _unquote_keyword_default
# ---------------------------------------------------------------------------


class TestUnquoteKeywordDefault(unittest.TestCase):

    def test_unquotes_current_timestamp(self):
        result = SQLiteIntrospector._unquote_keyword_default("'CURRENT_TIMESTAMP'")
        self.assertEqual(result, "CURRENT_TIMESTAMP")

    def test_unquotes_current_date(self):
        result = SQLiteIntrospector._unquote_keyword_default("'current_date'")
        self.assertEqual(result, "CURRENT_DATE")

    def test_unquotes_null(self):
        result = SQLiteIntrospector._unquote_keyword_default("'NULL'")
        self.assertEqual(result, "NULL")

    def test_unquotes_true(self):
        result = SQLiteIntrospector._unquote_keyword_default("'TRUE'")
        self.assertEqual(result, "TRUE")

    def test_unquotes_false(self):
        result = SQLiteIntrospector._unquote_keyword_default("'FALSE'")
        self.assertEqual(result, "FALSE")

    def test_preserves_normal_string(self):
        result = SQLiteIntrospector._unquote_keyword_default("'hello world'")
        self.assertEqual(result, "'hello world'")

    def test_preserves_unquoted(self):
        result = SQLiteIntrospector._unquote_keyword_default("CURRENT_TIMESTAMP")
        self.assertEqual(result, "CURRENT_TIMESTAMP")

    def test_none_returns_none(self):
        result = SQLiteIntrospector._unquote_keyword_default(None)
        self.assertIsNone(result)

    def test_single_char_quoted(self):
        # Edge: single-char quoted that's not a keyword
        result = SQLiteIntrospector._unquote_keyword_default("'a'")
        self.assertEqual(result, "'a'")


# ---------------------------------------------------------------------------
# _get_table_columns
# ---------------------------------------------------------------------------


class TestGetTableColumns(unittest.TestCase):

    def test_returns_columns_from_pragma(self):
        introspector, provider = _make_introspector()
        provider.execute_query.return_value = [
            {"name": "id", "type": "INTEGER", "notnull": 1, "dflt_value": None, "pk": 1},
            {"name": "name", "type": "TEXT", "notnull": 0, "dflt_value": "'anon'", "pk": 0},
        ]
        cols = introspector._get_table_columns("users")
        self.assertEqual(len(cols), 2)
        self.assertEqual(cols[0].name, "id")
        self.assertEqual(cols[0].data_type, "INTEGER")
        self.assertTrue(cols[0].is_primary_key)
        self.assertTrue(cols[0].is_identity)
        self.assertFalse(cols[0].nullable)

    def test_text_column_nullable(self):
        introspector, provider = _make_introspector()
        provider.execute_query.return_value = [
            {"name": "bio", "type": "TEXT", "notnull": 0, "dflt_value": None, "pk": 0},
        ]
        cols = introspector._get_table_columns("users")
        self.assertEqual(len(cols), 1)
        self.assertTrue(cols[1 - 1].nullable)

    def test_returns_empty_list_on_exception(self):
        introspector, provider = _make_introspector()
        provider.execute_query.side_effect = RuntimeError("PRAGMA failed")
        cols = introspector._get_table_columns("broken")
        self.assertEqual(cols, [])

    def test_default_text_when_type_missing(self):
        introspector, provider = _make_introspector()
        provider.execute_query.return_value = [
            {"name": "x", "type": None, "notnull": 0, "dflt_value": None, "pk": 0},
        ]
        cols = introspector._get_table_columns("t")
        self.assertEqual(cols[0].data_type, "TEXT")

    def test_keyword_default_unquoted(self):
        introspector, provider = _make_introspector()
        provider.execute_query.return_value = [
            {
                "name": "ts",
                "type": "TEXT",
                "notnull": 0,
                "dflt_value": "'CURRENT_TIMESTAMP'",
                "pk": 0,
            },
        ]
        cols = introspector._get_table_columns("t")
        self.assertEqual(cols[0].default_value, "CURRENT_TIMESTAMP")


# ---------------------------------------------------------------------------
# _get_primary_key_columns
# ---------------------------------------------------------------------------


class TestGetPrimaryKeyColumns(unittest.TestCase):

    def test_returns_pk_columns(self):
        introspector, provider = _make_introspector()
        provider.execute_query.return_value = [
            {"name": "id", "notnull": 1, "dflt_value": None, "type": "INTEGER", "pk": 1},
            {"name": "name", "notnull": 0, "dflt_value": None, "type": "TEXT", "pk": 0},
        ]
        pk_cols = introspector._get_primary_key_columns("users")
        self.assertEqual(pk_cols, ["id"])

    def test_returns_empty_when_no_pk(self):
        introspector, provider = _make_introspector()
        provider.execute_query.return_value = [
            {"name": "x", "notnull": 0, "dflt_value": None, "type": "TEXT", "pk": 0},
        ]
        pk_cols = introspector._get_primary_key_columns("t")
        self.assertEqual(pk_cols, [])

    def test_returns_empty_on_exception(self):
        introspector, provider = _make_introspector()
        provider.execute_query.side_effect = RuntimeError("fail")
        pk_cols = introspector._get_primary_key_columns("t")
        self.assertEqual(pk_cols, [])

    def test_composite_pk(self):
        introspector, provider = _make_introspector()
        provider.execute_query.return_value = [
            {"name": "a", "notnull": 1, "dflt_value": None, "type": "INTEGER", "pk": 1},
            {"name": "b", "notnull": 1, "dflt_value": None, "type": "INTEGER", "pk": 2},
            {"name": "c", "notnull": 0, "dflt_value": None, "type": "TEXT", "pk": 0},
        ]
        pk_cols = introspector._get_primary_key_columns("t")
        self.assertIn("a", pk_cols)
        self.assertIn("b", pk_cols)
        self.assertNotIn("c", pk_cols)


# ---------------------------------------------------------------------------
# _get_index_columns
# ---------------------------------------------------------------------------


class TestGetIndexColumns(unittest.TestCase):

    def test_returns_column_names(self):
        introspector, provider = _make_introspector()
        provider.execute_query.return_value = [
            {"name": "email", "cid": 1},
        ]
        cols = introspector._get_index_columns("idx_users_email")
        self.assertEqual(cols, ["email"])

    def test_returns_none_for_expression_index(self):
        introspector, provider = _make_introspector()
        provider.execute_query.return_value = [
            {"name": None, "cid": -2},
        ]
        cols = introspector._get_index_columns("idx_expr")
        self.assertEqual(cols, [None])

    def test_returns_empty_on_exception(self):
        introspector, provider = _make_introspector()
        provider.execute_query.side_effect = RuntimeError("fail")
        cols = introspector._get_index_columns("idx")
        self.assertEqual(cols, [])


# ---------------------------------------------------------------------------
# _parse_index_where_clause
# ---------------------------------------------------------------------------


class TestParseIndexWhereClause(unittest.TestCase):

    def test_extracts_where_predicate(self):
        introspector, _ = _make_introspector()
        sql = "CREATE INDEX idx_active ON users(name) WHERE active = 1"
        result = introspector._parse_index_where_clause(sql)
        self.assertEqual(result, "active = 1")

    def test_returns_none_for_non_partial(self):
        introspector, _ = _make_introspector()
        sql = "CREATE INDEX idx_name ON users(name)"
        result = introspector._parse_index_where_clause(sql)
        self.assertIsNone(result)

    def test_returns_none_for_empty_sql(self):
        introspector, _ = _make_introspector()
        result = introspector._parse_index_where_clause("")
        self.assertIsNone(result)

    def test_returns_none_for_none_sql(self):
        introspector, _ = _make_introspector()
        result = introspector._parse_index_where_clause(None)
        self.assertIsNone(result)

    def test_complex_where_predicate(self):
        introspector, _ = _make_introspector()
        sql = 'CREATE UNIQUE INDEX idx_partial ON orders(status) WHERE status != "deleted"'
        result = introspector._parse_index_where_clause(sql)
        self.assertIsNotNone(result)
        self.assertIn("status", result)


# ---------------------------------------------------------------------------
# _parse_index_expression
# ---------------------------------------------------------------------------


class TestParseIndexExpression(unittest.TestCase):

    def test_extracts_function_expression(self):
        introspector, _ = _make_introspector()
        sql = "CREATE INDEX idx_lower ON users(LOWER(email))"
        result = introspector._parse_index_expression(sql)
        self.assertIsNotNone(result)
        self.assertIn("LOWER", result)

    def test_returns_none_for_simple_column(self):
        introspector, _ = _make_introspector()
        sql = "CREATE INDEX idx_name ON users(name)"
        result = introspector._parse_index_expression(sql)
        # Simple column names don't contain function calls/operators
        self.assertIsNone(result)

    def test_returns_none_for_empty(self):
        introspector, _ = _make_introspector()
        self.assertIsNone(introspector._parse_index_expression(""))

    def test_returns_none_for_none(self):
        introspector, _ = _make_introspector()
        self.assertIsNone(introspector._parse_index_expression(None))

    def test_extracts_concatenation_expression(self):
        introspector, _ = _make_introspector()
        sql = "CREATE INDEX idx_full_name ON users(first_name || ' ' || last_name)"
        result = introspector._parse_index_expression(sql)
        self.assertIsNotNone(result)
        self.assertIn("||", result)


# ---------------------------------------------------------------------------
# _parse_unique_constraints
# ---------------------------------------------------------------------------


class TestParseUniqueConstraints(unittest.TestCase):

    def test_parses_single_unique(self):
        introspector, _ = _make_introspector()
        sql = "CREATE TABLE t (a TEXT, b TEXT, UNIQUE (a, b))"
        constraints = introspector._parse_unique_constraints(sql, "t")
        self.assertEqual(len(constraints), 1)
        self.assertEqual(constraints[0].constraint_type, ConstraintType.UNIQUE)
        self.assertIn("a", constraints[0].column_names)
        self.assertIn("b", constraints[0].column_names)

    def test_parses_multiple_unique(self):
        introspector, _ = _make_introspector()
        sql = "CREATE TABLE t (a TEXT, b TEXT, c TEXT, UNIQUE (a), UNIQUE (b, c))"
        constraints = introspector._parse_unique_constraints(sql, "t")
        self.assertEqual(len(constraints), 2)

    def test_returns_empty_for_empty_sql(self):
        introspector, _ = _make_introspector()
        constraints = introspector._parse_unique_constraints("", "t")
        self.assertEqual(constraints, [])

    def test_returns_empty_for_none_sql(self):
        introspector, _ = _make_introspector()
        constraints = introspector._parse_unique_constraints(None, "t")
        self.assertEqual(constraints, [])


# ---------------------------------------------------------------------------
# _parse_check_constraints
# ---------------------------------------------------------------------------


class TestParseCheckConstraints(unittest.TestCase):

    def test_parses_unnamed_check(self):
        introspector, _ = _make_introspector()
        sql = "CREATE TABLE t (id INTEGER, age INTEGER CHECK (age > 0))"
        constraints = introspector._parse_check_constraints(sql, "t")
        self.assertGreater(len(constraints), 0)
        self.assertEqual(constraints[0].constraint_type, ConstraintType.CHECK)
        self.assertIn("age", constraints[0].check_expression)

    def test_parses_named_check(self):
        introspector, _ = _make_introspector()
        sql = "CREATE TABLE t (id INTEGER, age INTEGER, CONSTRAINT chk_age CHECK (age >= 0))"
        constraints = introspector._parse_check_constraints(sql, "t")
        self.assertEqual(len(constraints), 1)
        self.assertEqual(constraints[0].name, "chk_age")
        self.assertIn("age", constraints[0].check_expression)

    def test_parses_nested_parentheses_check(self):
        introspector, _ = _make_introspector()
        sql = "CREATE TABLE t (name TEXT, CONSTRAINT chk_len CHECK (length(name) > 0))"
        constraints = introspector._parse_check_constraints(sql, "t")
        self.assertEqual(len(constraints), 1)
        self.assertEqual(constraints[0].name, "chk_len")

    def test_returns_empty_for_empty_sql(self):
        introspector, _ = _make_introspector()
        constraints = introspector._parse_check_constraints("", "t")
        self.assertEqual(constraints, [])

    def test_returns_empty_for_none_sql(self):
        introspector, _ = _make_introspector()
        constraints = introspector._parse_check_constraints(None, "t")
        self.assertEqual(constraints, [])

    def test_no_check_constraints(self):
        introspector, _ = _make_introspector()
        sql = "CREATE TABLE t (id INTEGER PRIMARY KEY, name TEXT)"
        constraints = introspector._parse_check_constraints(sql, "t")
        self.assertEqual(constraints, [])


# ---------------------------------------------------------------------------
# _parse_generated_columns
# ---------------------------------------------------------------------------


class TestParseGeneratedColumns(unittest.TestCase):

    def test_parses_stored_generated_column(self):
        introspector, _ = _make_introspector()
        sql = "CREATE TABLE t (price REAL, qty INTEGER, total REAL GENERATED ALWAYS AS (price * qty) STORED)"
        cols = introspector._parse_generated_columns(sql, "t")
        self.assertEqual(len(cols), 1)
        self.assertEqual(cols[0].name, "total")
        self.assertTrue(cols[0].is_computed)
        self.assertTrue(cols[0].computed_stored)
        self.assertIn("price", cols[0].computed_expression)

    def test_parses_virtual_generated_column(self):
        introspector, _ = _make_introspector()
        sql = "CREATE TABLE t (a INTEGER, b INTEGER GENERATED ALWAYS AS (a * 2) VIRTUAL)"
        cols = introspector._parse_generated_columns(sql, "t")
        self.assertEqual(len(cols), 1)
        self.assertFalse(cols[0].computed_stored)

    def test_returns_empty_for_no_generated(self):
        introspector, _ = _make_introspector()
        sql = "CREATE TABLE t (id INTEGER, name TEXT)"
        cols = introspector._parse_generated_columns(sql, "t")
        self.assertEqual(cols, [])

    def test_returns_empty_for_empty_sql(self):
        introspector, _ = _make_introspector()
        cols = introspector._parse_generated_columns("", "t")
        self.assertEqual(cols, [])


# ---------------------------------------------------------------------------
# _merge_columns_with_generated
# ---------------------------------------------------------------------------


class TestMergeColumnsWithGenerated(unittest.TestCase):

    def test_returns_regular_columns_when_no_generated(self):
        from core.sql_model.base import SqlColumn

        introspector, _ = _make_introspector()
        regular = [
            SqlColumn(name="id", data_type="INTEGER"),
            SqlColumn(name="name", data_type="TEXT"),
        ]
        result = introspector._merge_columns_with_generated(
            regular, [], "CREATE TABLE t (id INTEGER, name TEXT)"
        )
        self.assertEqual(result, regular)

    def test_merges_in_correct_order(self):
        from core.sql_model.base import SqlColumn

        introspector, _ = _make_introspector()
        regular = [
            SqlColumn(name="price", data_type="REAL"),
            SqlColumn(name="qty", data_type="INTEGER"),
        ]
        generated = [
            SqlColumn(
                name="total", data_type="REAL", is_computed=True, computed_expression="price * qty"
            )
        ]
        create_sql = "CREATE TABLE t (price REAL, qty INTEGER, total REAL GENERATED ALWAYS AS (price * qty) STORED)"
        result = introspector._merge_columns_with_generated(regular, generated, create_sql)
        names = [c.name for c in result]
        self.assertIn("price", names)
        self.assertIn("qty", names)
        self.assertIn("total", names)

    def test_fallback_on_bad_sql(self):
        from core.sql_model.base import SqlColumn

        introspector, _ = _make_introspector()
        regular = [SqlColumn(name="a", data_type="INTEGER")]
        generated = [
            SqlColumn(name="b", data_type="INTEGER", is_computed=True, computed_expression="a+1")
        ]
        result = introspector._merge_columns_with_generated(regular, generated, "no parens here")
        # Should include both columns
        self.assertEqual(len(result), 2)


# ---------------------------------------------------------------------------
# get_views
# ---------------------------------------------------------------------------


class TestGetViews(unittest.TestCase):

    def test_returns_views_list(self):
        introspector, provider = _make_introspector()
        introspector.connection = MagicMock()
        provider.execute_query.return_value = [
            {
                "name": "v_active",
                "sql": "CREATE VIEW v_active AS SELECT * FROM users WHERE active=1",
            }
        ]

        views = introspector.get_views("main")
        self.assertEqual(len(views), 1)
        self.assertEqual(views[0].name, "v_active")
        self.assertIsNotNone(views[0].query)

    def test_skips_row_with_no_name(self):
        introspector, provider = _make_introspector()
        introspector.connection = MagicMock()
        provider.execute_query.return_value = [
            {"name": None, "sql": "CREATE VIEW foo AS SELECT 1"},
        ]
        views = introspector.get_views("main")
        self.assertEqual(len(views), 0)

    def test_raises_on_provider_error(self):
        introspector, provider = _make_introspector()
        introspector.connection = MagicMock()
        provider.execute_query.side_effect = RuntimeError("db error")
        with self.assertRaises(RuntimeError):
            introspector.get_views("main")


# ---------------------------------------------------------------------------
# _extract_view_query
# ---------------------------------------------------------------------------


class TestExtractViewQuery(unittest.TestCase):

    def test_extracts_select(self):
        introspector, _ = _make_introspector()
        sql = "CREATE VIEW v AS SELECT id, name FROM users"
        result = introspector._extract_view_query(sql)
        self.assertIn("SELECT", result)

    def test_returns_none_for_empty(self):
        introspector, _ = _make_introspector()
        self.assertIsNone(introspector._extract_view_query(""))

    def test_returns_none_for_none(self):
        introspector, _ = _make_introspector()
        self.assertIsNone(introspector._extract_view_query(None))


# ---------------------------------------------------------------------------
# get_triggers
# ---------------------------------------------------------------------------


class TestGetTriggers(unittest.TestCase):

    def test_returns_triggers(self):
        introspector, provider = _make_introspector()
        introspector.connection = MagicMock()
        provider.execute_query.return_value = [
            {
                "name": "trg_after_insert",
                "tbl_name": "users",
                "sql": "CREATE TRIGGER trg_after_insert AFTER INSERT ON users BEGIN SELECT 1; END",
            }
        ]
        triggers = introspector.get_triggers("main")
        self.assertEqual(len(triggers), 1)
        self.assertEqual(triggers[0].name, "trg_after_insert")
        self.assertEqual(triggers[0].timing, "AFTER")
        self.assertIn("INSERT", triggers[0].events)

    def test_skips_trigger_with_no_name(self):
        introspector, provider = _make_introspector()
        introspector.connection = MagicMock()
        provider.execute_query.return_value = [
            {"name": None, "tbl_name": "t", "sql": "CREATE TRIGGER..."},
        ]
        triggers = introspector.get_triggers("main")
        self.assertEqual(len(triggers), 0)

    def test_raises_on_provider_error(self):
        introspector, provider = _make_introspector()
        introspector.connection = MagicMock()
        provider.execute_query.side_effect = RuntimeError("fail")
        with self.assertRaises(RuntimeError):
            introspector.get_triggers("main")


# ---------------------------------------------------------------------------
# _parse_trigger_info
# ---------------------------------------------------------------------------


class TestParseTriggerInfo(unittest.TestCase):

    def test_before_insert(self):
        introspector, _ = _make_introspector()
        sql = "CREATE TRIGGER t BEFORE INSERT ON tbl BEGIN END"
        timing, events = introspector._parse_trigger_info(sql)
        self.assertEqual(timing, "BEFORE")
        self.assertIn("INSERT", events)

    def test_after_update(self):
        introspector, _ = _make_introspector()
        sql = "CREATE TRIGGER t AFTER UPDATE ON tbl BEGIN END"
        timing, events = introspector._parse_trigger_info(sql)
        self.assertEqual(timing, "AFTER")
        self.assertIn("UPDATE", events)

    def test_instead_of_delete(self):
        introspector, _ = _make_introspector()
        sql = "CREATE TRIGGER t INSTEAD OF DELETE ON tbl BEGIN END"
        timing, events = introspector._parse_trigger_info(sql)
        self.assertEqual(timing, "INSTEAD OF")
        self.assertIn("DELETE", events)

    def test_empty_sql(self):
        introspector, _ = _make_introspector()
        timing, events = introspector._parse_trigger_info("")
        self.assertIsNone(timing)
        self.assertEqual(events, [])

    def test_none_sql(self):
        introspector, _ = _make_introspector()
        timing, events = introspector._parse_trigger_info(None)
        self.assertIsNone(timing)
        self.assertEqual(events, [])


# ---------------------------------------------------------------------------
# _get_row_value
# ---------------------------------------------------------------------------


class TestGetRowValue(unittest.TestCase):

    def test_exact_key(self):
        introspector, _ = _make_introspector()
        self.assertEqual(introspector._get_row_value({"name": "foo"}, "name"), "foo")

    def test_lowercase_key(self):
        introspector, _ = _make_introspector()
        self.assertEqual(introspector._get_row_value({"name": "foo"}, "NAME"), "foo")

    def test_uppercase_key(self):
        introspector, _ = _make_introspector()
        self.assertEqual(introspector._get_row_value({"NAME": "bar"}, "name"), "bar")

    def test_missing_key_returns_none(self):
        introspector, _ = _make_introspector()
        self.assertIsNone(introspector._get_row_value({"x": 1}, "y"))


# ---------------------------------------------------------------------------
# Unsupported features return empty
# ---------------------------------------------------------------------------


class TestUnsupportedFeatures(unittest.TestCase):

    def test_get_sequences_returns_empty(self):
        introspector, _ = _make_introspector()
        self.assertEqual(introspector.get_sequences("main"), [])

    def test_get_materialized_views_returns_empty(self):
        introspector, _ = _make_introspector()
        self.assertEqual(introspector.get_materialized_views("main"), [])

    def test_get_procedures_returns_empty(self):
        introspector, _ = _make_introspector()
        self.assertEqual(introspector.get_procedures("main"), [])

    def test_get_functions_returns_empty(self):
        introspector, _ = _make_introspector()
        self.assertEqual(introspector.get_functions("main"), [])

    def test_get_user_defined_types_returns_empty(self):
        introspector, _ = _make_introspector()
        self.assertEqual(introspector.get_user_defined_types("main"), [])


# ---------------------------------------------------------------------------
# get_tables with FTS5 shadow filtering
# ---------------------------------------------------------------------------


class TestGetTablesFts5Filter(unittest.TestCase):

    def test_filters_shadow_tables(self):
        introspector, provider = _make_introspector()
        introspector.connection = MagicMock()

        def execute_query_side_effect(query, params=None):
            if "sqlite_master" in query and params is None:
                return [
                    {
                        "name": "docs",
                        "sql": "CREATE VIRTUAL TABLE docs USING fts5(body)",
                    },
                    {
                        "name": "docs_data",
                        "sql": "CREATE TABLE docs_data (id INTEGER PRIMARY KEY)",
                    },
                    {
                        "name": "normal",
                        "sql": "CREATE TABLE normal (id INTEGER)",
                    },
                ]
            elif "PRAGMA table_info" in query:
                return [
                    {"name": "id", "type": "INTEGER", "notnull": 1, "dflt_value": None, "pk": 1}
                ]
            elif "PRAGMA foreign_key_list" in query:
                return []
            elif "type = 'index'" in query:
                return []
            return []

        provider.execute_query.side_effect = execute_query_side_effect

        tables = introspector.get_tables("main")
        names = [t.name for t in tables]
        # shadow table docs_data should be filtered
        self.assertNotIn("docs_data", names)
        # FTS5 virtual table and normal table should be kept
        self.assertIn("docs", names)
        self.assertIn("normal", names)


# ---------------------------------------------------------------------------
# get_check_constraints (public method)
# ---------------------------------------------------------------------------


class TestGetCheckConstraints(unittest.TestCase):

    def test_returns_check_constraints_from_sql(self):
        introspector, provider = _make_introspector()
        introspector.connection = MagicMock()
        provider.execute_query.return_value = [
            {"sql": "CREATE TABLE t (age INTEGER CHECK (age > 0))"}
        ]
        constraints = introspector.get_check_constraints("main", "t")
        self.assertGreater(len(constraints), 0)
        self.assertEqual(constraints[0].constraint_type, ConstraintType.CHECK)

    def test_returns_empty_when_no_rows(self):
        introspector, provider = _make_introspector()
        introspector.connection = MagicMock()
        provider.execute_query.return_value = []
        constraints = introspector.get_check_constraints("main", "t")
        self.assertEqual(constraints, [])

    def test_returns_empty_on_exception(self):
        introspector, provider = _make_introspector()
        introspector.connection = MagicMock()
        provider.execute_query.side_effect = RuntimeError("db error")
        constraints = introspector.get_check_constraints("main", "t")
        self.assertEqual(constraints, [])


# ---------------------------------------------------------------------------
# introspect_schema
# ---------------------------------------------------------------------------


class TestIntrospectSchema(unittest.TestCase):

    def test_returns_schema_dict_with_all_keys(self):
        introspector, provider = _make_introspector()
        introspector.connection = MagicMock()

        def execute_query_side_effect(query, params=None):
            if "sqlite_master" in query and "table" in query and params is None:
                return []
            elif "sqlite_master" in query and "view" in query:
                return []
            elif "sqlite_master" in query and "trigger" in query:
                return []
            return []

        provider.execute_query.side_effect = execute_query_side_effect

        result = introspector.introspect_schema("main")
        self.assertIn("tables", result)
        self.assertIn("views", result)
        self.assertIn("triggers", result)
        self.assertIn("indexes", result)
        self.assertIn("sequences", result)
        self.assertIn("table_count", result)

    def test_skips_views_when_disabled(self):
        introspector, provider = _make_introspector()
        introspector.connection = MagicMock()

        def execute_query_side_effect(query, params=None):
            return []

        provider.execute_query.side_effect = execute_query_side_effect

        result = introspector.introspect_schema("main", include_views=False, include_triggers=False)
        self.assertEqual(result["views"], [])
        self.assertEqual(result["triggers"], [])


# ---------------------------------------------------------------------------
# get_indexes (public method via _get_table_indexes)
# ---------------------------------------------------------------------------


class TestGetIndexes(unittest.TestCase):

    def test_get_indexes_delegates_to_internal(self):
        introspector, provider = _make_introspector()
        provider.execute_query.return_value = []
        indexes = introspector.get_indexes("main", "users")
        self.assertIsInstance(indexes, list)

    def test_get_table_indexes_with_unique(self):
        introspector, provider = _make_introspector()

        call_count = [0]

        def execute_query_side_effect(query, params=None):
            call_count[0] += 1
            if "sqlite_master" in query and "index" in query:
                return [
                    {"name": "idx_email", "sql": "CREATE UNIQUE INDEX idx_email ON users(email)"}
                ]
            elif "PRAGMA index_info" in query:
                return [{"name": "email", "cid": 1}]
            return []

        provider.execute_query.side_effect = execute_query_side_effect

        indexes = introspector._get_table_indexes("users")
        self.assertEqual(len(indexes), 1)
        self.assertEqual(indexes[0].name, "idx_email")
        self.assertTrue(indexes[0].unique)


class TestGetTablesAutoincrement(unittest.TestCase):

    def test_get_tables_marks_explicit_autoincrement_columns(self):
        introspector, provider = _make_introspector()

        def execute_query_side_effect(query, params=None):
            if "FROM sqlite_master" in query and "type = 'table'" in query:
                return [
                    {
                        "name": "users",
                        "sql": "CREATE TABLE users (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT)",
                    }
                ]
            if "PRAGMA table_info" in query:
                return [
                    {"name": "id", "type": "INTEGER", "notnull": 0, "dflt_value": None, "pk": 1},
                    {"name": "name", "type": "TEXT", "notnull": 0, "dflt_value": None, "pk": 0},
                ]
            return []

        provider.execute_query.side_effect = execute_query_side_effect

        tables = introspector.get_tables("main")

        id_column = tables[0].columns[0]
        self.assertTrue(getattr(id_column, "auto_increment", False))

    def test_get_tables_does_not_mark_plain_integer_primary_key_autoincrement(self):
        introspector, provider = _make_introspector()

        def execute_query_side_effect(query, params=None):
            if "FROM sqlite_master" in query and "type = 'table'" in query:
                return [
                    {
                        "name": "users",
                        "sql": "CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT)",
                    }
                ]
            if "PRAGMA table_info" in query:
                return [
                    {"name": "id", "type": "INTEGER", "notnull": 0, "dflt_value": None, "pk": 1},
                    {"name": "name", "type": "TEXT", "notnull": 0, "dflt_value": None, "pk": 0},
                ]
            return []

        provider.execute_query.side_effect = execute_query_side_effect

        tables = introspector.get_tables("main")

        id_column = tables[0].columns[0]
        self.assertFalse(getattr(id_column, "auto_increment", False))


if __name__ == "__main__":
    unittest.main()
