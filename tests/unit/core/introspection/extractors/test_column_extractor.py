"""
Unit tests for ColumnExtractor.
Covers: get_columns(), _build_data_type_string(), _detect_identity(),
_detect_computed_column(), _enhance_with_vendor_queries(), dialect-specific
type handling, error handling.
"""

import unittest
from unittest.mock import MagicMock, patch

import pytest

from core.introspection.extractors.column_extractor import ColumnExtractor

pytestmark = [pytest.mark.unit]


def _make_extractor(dialect="postgresql", vendor_queries=None):
    provider = MagicMock()
    provider.query_executor = MagicMock()
    if vendor_queries is None:
        vendor_queries = MagicMock()
        vendor_queries.get_columns_query.return_value = ("SELECT columns", [])
    extractor = ColumnExtractor(
        provider=provider,
        dialect=dialect,
        vendor_queries=vendor_queries,
    )
    extractor.ensure_metadata = MagicMock()
    return extractor


def _simple_col(
    name="id",
    type_name="int4",
    table_name="users",
    size=0,
    digits=0,
    nullable=0,
    col_def=None,
    ordinal=1,
    remarks=None,
    autoincrement="NO",
    generated="NO",
):
    return {
        "COLUMN_NAME": name,
        "TYPE_NAME": type_name,
        "TABLE_NAME": table_name,
        "COLUMN_SIZE": size,
        "DECIMAL_DIGITS": digits,
        "NULLABLE": nullable,
        "COLUMN_DEF": col_def,
        "ORDINAL_POSITION": ordinal,
        "REMARKS": remarks,
        "IS_AUTOINCREMENT": autoincrement,
        "IS_GENERATEDCOLUMN": generated,
    }


# --- _build_data_type_string ---


class TestBuildDataTypeString(unittest.TestCase):
    def _e(self, dialect="postgresql"):
        return _make_extractor(dialect=dialect)

    def test_simple_type_no_size(self):
        e = self._e()
        result = e._build_data_type_string("int4", 0, 0)
        self.assertEqual(result, "int4")

    def test_varchar_with_size(self):
        e = self._e()
        result = e._build_data_type_string("VARCHAR", 255, 0)
        self.assertEqual(result, "VARCHAR(255)")

    def test_decimal_with_precision_and_scale(self):
        e = self._e()
        result = e._build_data_type_string("DECIMAL", 10, 2)
        self.assertEqual(result, "DECIMAL(10, 2)")

    def test_type_already_has_precision_not_added(self):
        e = self._e()
        result = e._build_data_type_string("TIMESTAMP(6)", 10, 6)
        self.assertEqual(result, "TIMESTAMP(6)")

    def test_sqlserver_varchar_max(self):
        # SQL Server uses 2147483647 for VARCHAR(MAX) — column_size must be > 0 to enter the branch
        e = self._e(dialect="sqlserver")
        result = e._build_data_type_string("VARCHAR", 2147483647, 0)
        self.assertEqual(result, "VARCHAR(MAX)")

    def test_sqlserver_nvarchar_max_large_size(self):
        e = self._e(dialect="sqlserver")
        result = e._build_data_type_string("NVARCHAR", 2147483647, 0)
        self.assertEqual(result, "NVARCHAR(MAX)")

    def test_postgresql_timestamp_with_scale(self):
        e = self._e(dialect="postgresql")
        result = e._build_data_type_string("TIMESTAMP", 10, 6)
        self.assertEqual(result, "TIMESTAMP(6)")

    def test_postgresql_time_with_scale(self):
        e = self._e(dialect="postgresql")
        result = e._build_data_type_string("TIME", 10, 3)
        self.assertEqual(result, "TIME(3)")

    def test_oracle_timestamp_with_scale(self):
        e = self._e(dialect="oracle")
        result = e._build_data_type_string("TIMESTAMP", 10, 6)
        self.assertEqual(result, "TIMESTAMP(6)")

    def test_db2_timestamp_with_scale(self):
        e = self._e(dialect="db2")
        result = e._build_data_type_string("TIMESTAMP", 26, 6)
        self.assertEqual(result, "TIMESTAMP(6)")

    def test_sqlserver_datetime2_with_scale(self):
        e = self._e(dialect="sqlserver")
        result = e._build_data_type_string("DATETIME2", 10, 7)
        self.assertEqual(result, "DATETIME2(7)")

    def test_non_char_type_size_not_appended_without_digits(self):
        """INTEGER with size=10, digits=0 — no parens appended."""
        e = self._e()
        result = e._build_data_type_string("INTEGER", 10, 0)
        self.assertEqual(result, "INTEGER")

    def test_char_with_size(self):
        e = self._e()
        result = e._build_data_type_string("CHAR", 10, 0)
        self.assertEqual(result, "CHAR(10)")

    def test_nvarchar_with_size(self):
        e = self._e()
        result = e._build_data_type_string("NVARCHAR", 100, 0)
        self.assertEqual(result, "NVARCHAR(100)")


# --- _detect_identity ---


class TestDetectIdentity(unittest.TestCase):
    def _e(self, dialect="postgresql"):
        return _make_extractor(dialect=dialect)

    def test_yes_autoincrement_returns_true(self):
        e = self._e()
        self.assertTrue(e._detect_identity("YES", "id", None))

    def test_no_autoincrement_returns_false(self):
        e = self._e()
        self.assertFalse(e._detect_identity("NO", "id", None))

    def test_none_autoincrement_returns_false(self):
        e = self._e()
        self.assertFalse(e._detect_identity(None, "id", None))

    def test_db2_identity_from_catalog_set(self):
        e = self._e(dialect="db2")
        db2_identity_cols = {"ID", "USER_ID"}
        self.assertTrue(e._detect_identity("NO", "ID", db2_identity_cols))

    def test_db2_identity_case_insensitive(self):
        e = self._e(dialect="db2")
        db2_identity_cols = {"ID"}
        self.assertTrue(e._detect_identity("NO", "id", db2_identity_cols))

    def test_db2_not_in_catalog_returns_false(self):
        e = self._e(dialect="db2")
        db2_identity_cols = {"OTHER_COL"}
        self.assertFalse(e._detect_identity("NO", "id", db2_identity_cols))

    def test_db2_catalog_none_falls_back_to_jdbc_flag(self):
        e = self._e(dialect="db2")
        self.assertFalse(e._detect_identity("NO", "id", None))


# --- _detect_computed_column ---


class TestDetectComputedColumn(unittest.TestCase):
    def _e(self, dialect="postgresql"):
        return _make_extractor(dialect=dialect)

    def test_is_generated_yes_returns_true(self):
        e = self._e()
        self.assertTrue(e._detect_computed_column("YES", None, False))

    def test_is_generated_no_returns_false(self):
        e = self._e()
        self.assertFalse(e._detect_computed_column("NO", None, False))

    def test_mysql_default_timestamp_not_computed(self):
        """MySQL catalog rows can flag DEFAULT CURRENT_TIMESTAMP as generated."""
        e = self._e(dialect="mysql")
        result = e._detect_computed_column("YES", "CURRENT_TIMESTAMP", False)
        self.assertFalse(result)

    def test_mysql_generated_always_is_computed(self):
        """MySQL true computed column (GENERATED ALWAYS AS)."""
        e = self._e(dialect="mysql")
        result = e._detect_computed_column("YES", "GENERATED ALWAYS AS (col1 + col2)", False)
        self.assertTrue(result)

    def test_db2_identity_column_not_computed(self):
        """DB2 marks IDENTITY columns as generated — should not be computed."""
        e = self._e(dialect="db2")
        result = e._detect_computed_column("YES", None, True)
        self.assertFalse(result)

    def test_db2_non_identity_generated_is_computed(self):
        """DB2 non-identity generated column should remain computed."""
        e = self._e(dialect="db2")
        result = e._detect_computed_column("YES", None, False)
        self.assertTrue(result)


# --- get_columns() integration ---


class TestGetColumnsIntegration(unittest.TestCase):
    def _run(self, dialect, col_defs, vendor_queries=None):
        extractor = _make_extractor(dialect=dialect, vendor_queries=vendor_queries)
        extractor.provider.query_executor.execute_query.return_value = col_defs

        return extractor.get_columns("public", col_defs[0]["TABLE_NAME"] if col_defs else "t")

    def test_single_column_basic(self):
        cols = self._run("postgresql", [_simple_col()])
        self.assertEqual(len(cols), 1)
        self.assertEqual(cols[0].name, "id")
        self.assertEqual(cols[0].data_type, "int4")

    def test_empty_vendor_rows_returns_empty(self):
        extractor = _make_extractor(dialect="postgresql")
        extractor.provider.query_executor.execute_query.return_value = []
        cols = extractor.get_columns("public", "empty_table")
        self.assertEqual(cols, [])

    def test_nullable_column(self):
        extractor = _make_extractor(dialect="postgresql")
        col = {**_simple_col(name="email", type_name="VARCHAR", size=255), "NULLABLE": 1}
        extractor.provider.query_executor.execute_query.return_value = [col]
        extractor.ensure_metadata = MagicMock()
        cols = extractor.get_columns("public", "users")
        self.assertEqual(len(cols), 1)
        self.assertTrue(cols[0].nullable)

    def test_skips_column_from_different_table(self):
        """MySQL returns all columns; we must filter by table name."""
        extractor = _make_extractor(dialect="mysql")
        cols_data = [
            {**_simple_col(name="id", type_name="int", table_name="orders"), "ORDINAL_POSITION": 1},
            {
                **_simple_col(name="other", type_name="varchar", table_name="products"),
                "ORDINAL_POSITION": 1,
            },
        ]
        extractor.provider.query_executor.execute_query.return_value = cols_data
        extractor.ensure_metadata = MagicMock()
        cols = extractor.get_columns("mydb", "orders")
        # Should only include the 'orders' column
        self.assertEqual(len(cols), 1)
        self.assertEqual(cols[0].name, "id")

    def test_metadata_not_available_raises(self):
        extractor = _make_extractor(dialect="postgresql")
        extractor.vendor_queries.get_columns_query.return_value = None
        extractor.ensure_metadata = MagicMock()
        with self.assertRaises(RuntimeError):
            extractor.get_columns("public", "t")

    def test_identity_column(self):
        extractor = _make_extractor(dialect="postgresql")
        col = {**_simple_col(name="id", type_name="int4"), "IS_AUTOINCREMENT": "YES"}
        extractor.provider.query_executor.execute_query.return_value = [col]
        extractor.ensure_metadata = MagicMock()
        cols = extractor.get_columns("public", "users")
        self.assertTrue(cols[0].is_identity)

    def test_ordinal_sort(self):
        """Columns sorted by ordinal_position."""
        extractor = _make_extractor(dialect="postgresql")
        cols_data = [
            {**_simple_col(name="c2", type_name="int4"), "ORDINAL_POSITION": 2},
            {**_simple_col(name="c1", type_name="int4"), "ORDINAL_POSITION": 1},
        ]
        extractor.provider.query_executor.execute_query.return_value = cols_data
        extractor.ensure_metadata = MagicMock()
        cols = extractor.get_columns("public", "users")
        self.assertEqual(cols[0].name, "c1")
        self.assertEqual(cols[1].name, "c2")

    def test_column_with_comment(self):
        extractor = _make_extractor(dialect="postgresql")
        col = {**_simple_col(name="name", type_name="VARCHAR", size=100), "REMARKS": "User's name"}
        extractor.provider.query_executor.execute_query.return_value = [col]
        extractor.ensure_metadata = MagicMock()
        cols = extractor.get_columns("public", "users")
        self.assertEqual(cols[0].comment, "User's name")


# --- _enhance_with_vendor_queries ---


class TestEnhanceWithVendorQueries(unittest.TestCase):
    def test_sqlserver_enhances_default_values(self):
        vq = MagicMock()
        vq.get_column_defaults_query.return_value = ("SELECT 1", [])
        extractor = _make_extractor(dialect="sqlserver", vendor_queries=vq)

        # Create fake column with no default
        from core.sql_model.base import SqlColumn

        col = SqlColumn(
            name="created_at", data_type="DATETIME2", is_nullable=True, dialect="sqlserver"
        )

        extractor.provider.query_executor.execute_query.return_value = [
            {"column_name": "created_at", "default_value": "(getdate())"}
        ]
        result = extractor._enhance_with_vendor_queries("dbo", "orders", [col])
        self.assertEqual(result[0].default_value, "getdate()")

    def test_non_sqlserver_returns_columns_unchanged(self):
        extractor = _make_extractor(dialect="postgresql")
        from core.sql_model.base import SqlColumn

        col = SqlColumn(name="id", data_type="int4", is_nullable=False, dialect="postgresql")
        result = extractor._enhance_with_vendor_queries("public", "t", [col])
        self.assertEqual(result, [col])

    def test_sqlserver_no_vendor_queries_returns_unchanged(self):
        extractor = _make_extractor(dialect="sqlserver", vendor_queries=None)
        from core.sql_model.base import SqlColumn

        col = SqlColumn(name="id", data_type="int", is_nullable=False, dialect="sqlserver")
        result = extractor._enhance_with_vendor_queries("dbo", "t", [col])
        self.assertEqual(result, [col])

    def test_sqlserver_does_not_override_existing_default(self):
        vq = MagicMock()
        vq.get_column_defaults_query.return_value = ("SELECT 1", [])
        extractor = _make_extractor(dialect="sqlserver", vendor_queries=vq)
        from core.sql_model.base import SqlColumn

        col = SqlColumn(
            name="status",
            data_type="VARCHAR(10)",
            is_nullable=True,
            default_value="'active'",
            dialect="sqlserver",
        )
        extractor.provider.query_executor.execute_query.return_value = [
            {"column_name": "status", "default_value": "('pending')"}
        ]
        result = extractor._enhance_with_vendor_queries("dbo", "orders", [col])
        # Existing default preserved
        self.assertEqual(result[0].default_value, "'active'")
