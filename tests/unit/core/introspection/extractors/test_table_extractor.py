"""
Unit tests for TableExtractor.
Covers: get_tables(), _should_skip_table(), _verify_schema_match(),
_is_temporary_table(), _enrich_postgresql_table(), _supplement_partitioned_tables(),
error handling.
"""

import unittest
from unittest.mock import MagicMock, patch

import pytest

from core.introspection.extractors.table_extractor import TableExtractor

pytestmark = [pytest.mark.unit]


def _make_extractor(
    dialect="postgresql", vendor_queries=None, col_extractor=None, con_extractor=None
):
    provider = MagicMock()
    provider.query_executor = MagicMock()
    if vendor_queries is None:
        vendor_queries = MagicMock()
        vendor_queries.get_tables_query.return_value = ("SELECT tables", [])
        vendor_queries.get_view_names_query.return_value = None
    extractor = TableExtractor(
        provider=provider,
        dialect=dialect,
        vendor_queries=vendor_queries,
        column_extractor=col_extractor,
        constraint_extractor=con_extractor,
    )
    extractor.ensure_metadata = MagicMock()
    return extractor


def _make_full_extractor(dialect="postgresql", vendor_queries=None, table_rows=None):
    """Build extractor with vendor-query rows and col/con extractors."""
    col_ext = MagicMock()
    col_ext.get_columns.return_value = []
    con_ext = MagicMock()
    con_ext.get_constraints.return_value = []

    extractor = _make_extractor(
        dialect=dialect,
        vendor_queries=vendor_queries,
        col_extractor=col_ext,
        con_extractor=con_ext,
    )

    extractor.provider.query_executor.execute_query.return_value = table_rows or []

    return extractor


# --- _should_skip_table ---


class TestShouldSkipTable(unittest.TestCase):
    def test_skips_dblift_schema_history(self):
        e = _make_extractor()
        self.assertTrue(e._should_skip_table("DBLIFT_SCHEMA_HISTORY", "public", set()))

    def test_skips_schema_version(self):
        e = _make_extractor()
        self.assertTrue(e._should_skip_table("SCHEMA_VERSION", "public", set()))

    def test_does_not_skip_regular_table(self):
        e = _make_extractor()
        self.assertFalse(e._should_skip_table("users", "public", set()))

    def test_oracle_skips_mlog_prefix(self):
        e = _make_extractor(dialect="oracle")
        self.assertTrue(e._should_skip_table("MLOG$_ORDERS", "MYSCHEMA", set()))

    def test_oracle_skips_rupd_prefix(self):
        e = _make_extractor(dialect="oracle")
        self.assertTrue(e._should_skip_table("RUPD$_EMPLOYEES", "MYSCHEMA", set()))

    def test_oracle_skips_snap_prefix(self):
        e = _make_extractor(dialect="oracle")
        self.assertTrue(e._should_skip_table("SNAP$_CATALOG", "MYSCHEMA", set()))

    def test_oracle_skips_aq_prefix(self):
        e = _make_extractor(dialect="oracle")
        self.assertTrue(e._should_skip_table("AQ$_QUEUE_TABLE", "MYSCHEMA", set()))

    def test_oracle_skips_materialized_view_names(self):
        e = _make_extractor(dialect="oracle")
        mv_names = {"MV_SALES", "MV_ORDERS"}
        self.assertTrue(e._should_skip_table("MV_SALES", "MYSCHEMA", mv_names))

    def test_oracle_regular_table_not_skipped(self):
        e = _make_extractor(dialect="oracle")
        self.assertFalse(e._should_skip_table("EMPLOYEES", "MYSCHEMA", set()))

    def test_non_oracle_does_not_filter_mlog(self):
        e = _make_extractor(dialect="postgresql")
        self.assertFalse(e._should_skip_table("MLOG$_ORDERS", "public", set()))

    def test_case_insensitive_dblift_history(self):
        e = _make_extractor()
        self.assertTrue(e._should_skip_table("dblift_schema_history", "public", set()))


# --- _verify_schema_match ---


class TestVerifySchemaMatch(unittest.TestCase):
    def test_none_table_schema_passes(self):
        e = _make_extractor()
        self.assertTrue(e._verify_schema_match(None, "public", "users"))

    def test_matching_schema_passes(self):
        e = _make_extractor()
        self.assertTrue(e._verify_schema_match("public", "public", "users"))

    def test_mismatched_schema_fails(self):
        e = _make_extractor()
        self.assertFalse(e._verify_schema_match("private", "public", "users"))

    def test_case_insensitive_match(self):
        e = _make_extractor()
        self.assertTrue(e._verify_schema_match("PUBLIC", "public", "users"))

    def test_oracle_mismatched_schema_fails(self):
        e = _make_extractor(dialect="oracle")
        self.assertFalse(e._verify_schema_match("OTHER_SCHEMA", "MYSCHEMA", "EMPLOYEES"))

    def test_oracle_matching_schema_passes(self):
        e = _make_extractor(dialect="oracle")
        self.assertTrue(e._verify_schema_match("MYSCHEMA", "myschema", "EMPLOYEES"))


# --- _is_temporary_table ---


class TestIsTemporaryTable(unittest.TestCase):
    def test_none_type_returns_false(self):
        e = _make_extractor()
        self.assertFalse(e._is_temporary_table(None, "t"))

    def test_temporary_type(self):
        e = _make_extractor()
        self.assertTrue(e._is_temporary_table("TEMPORARY", "tmp_t"))

    def test_global_temporary_type(self):
        e = _make_extractor()
        self.assertTrue(e._is_temporary_table("GLOBAL TEMPORARY", "tmp_t"))

    def test_local_temporary_type(self):
        e = _make_extractor()
        self.assertTrue(e._is_temporary_table("LOCAL TEMPORARY", "tmp_t"))

    def test_temp_type(self):
        e = _make_extractor()
        self.assertTrue(e._is_temporary_table("TEMP", "tmp_t"))

    def test_regular_table_type(self):
        e = _make_extractor()
        self.assertFalse(e._is_temporary_table("TABLE", "regular"))

    def test_view_type_not_temporary(self):
        e = _make_extractor()
        self.assertFalse(e._is_temporary_table("VIEW", "v"))


# --- get_tables() ---


class TestGetTablesBasic(unittest.TestCase):
    def _patch_si(self):
        """Patch SchemaIntrospector to avoid circular imports."""
        return patch("core.introspection.schema_introspector.SchemaIntrospector")

    def test_single_table(self):
        with self._patch_si() as mock_si:
            mock_inst = MagicMock()
            mock_inst.enrich_columns_with_computed = MagicMock()
            mock_inst._apply_vendor_table_properties = MagicMock()
            mock_inst.enrich_table_with_partition_scheme = MagicMock()
            mock_si.return_value = mock_inst

            extractor = _make_full_extractor(
                dialect="postgresql",
                table_rows=[
                    {
                        "TABLE_NAME": "users",
                        "TABLE_TYPE": "TABLE",
                        "REMARKS": None,
                        "TABLE_SCHEM": "public",
                    }
                ],
            )
            tables = extractor.get_tables("public")
            self.assertEqual(len(tables), 1)
            self.assertEqual(tables[0].name, "users")
            self.assertEqual(tables[0].schema, "public")

    def test_empty_resultset_returns_empty_list(self):
        with self._patch_si() as mock_si:
            mock_inst = MagicMock()
            mock_si.return_value = mock_inst

            extractor = _make_full_extractor(dialect="postgresql", table_rows=[])
            tables = extractor.get_tables("public")
            self.assertEqual(tables, [])

    def test_skips_dblift_history_table(self):
        with self._patch_si() as mock_si:
            mock_inst = MagicMock()
            mock_inst.enrich_columns_with_computed = MagicMock()
            mock_inst._apply_vendor_table_properties = MagicMock()
            mock_inst.enrich_table_with_partition_scheme = MagicMock()
            mock_si.return_value = mock_inst

            extractor = _make_full_extractor(
                dialect="postgresql",
                table_rows=[
                    {
                        "TABLE_NAME": "dblift_schema_history",
                        "TABLE_TYPE": "TABLE",
                        "REMARKS": None,
                        "TABLE_SCHEM": "public",
                    },
                    {
                        "TABLE_NAME": "users",
                        "TABLE_TYPE": "TABLE",
                        "REMARKS": None,
                        "TABLE_SCHEM": "public",
                    },
                ],
            )
            tables = extractor.get_tables("public")
            self.assertEqual(len(tables), 1)
            self.assertEqual(tables[0].name, "users")

    def test_skips_none_table_name(self):
        with self._patch_si() as mock_si:
            mock_inst = MagicMock()
            mock_inst.enrich_columns_with_computed = MagicMock()
            mock_inst._apply_vendor_table_properties = MagicMock()
            mock_inst.enrich_table_with_partition_scheme = MagicMock()
            mock_si.return_value = mock_inst

            extractor = _make_full_extractor(
                dialect="postgresql",
                table_rows=[
                    {
                        "TABLE_NAME": None,
                        "TABLE_TYPE": "TABLE",
                        "REMARKS": None,
                        "TABLE_SCHEM": "public",
                    },
                ],
            )
            tables = extractor.get_tables("public")
            self.assertEqual(tables, [])

    def test_temporary_table_detected(self):
        with self._patch_si() as mock_si:
            mock_inst = MagicMock()
            mock_inst.enrich_columns_with_computed = MagicMock()
            mock_inst._apply_vendor_table_properties = MagicMock()
            mock_inst.enrich_table_with_partition_scheme = MagicMock()
            mock_si.return_value = mock_inst

            extractor = _make_full_extractor(
                dialect="postgresql",
                table_rows=[
                    {
                        "TABLE_NAME": "tmp_work",
                        "TABLE_TYPE": "TEMPORARY",
                        "REMARKS": None,
                        "TABLE_SCHEM": "public",
                    },
                ],
            )
            tables = extractor.get_tables("public")
            self.assertEqual(len(tables), 1)
            self.assertTrue(tables[0].temporary)

    def test_table_with_comment(self):
        with self._patch_si() as mock_si:
            mock_inst = MagicMock()
            mock_inst.enrich_columns_with_computed = MagicMock()
            mock_inst._apply_vendor_table_properties = MagicMock()
            mock_inst.enrich_table_with_partition_scheme = MagicMock()
            mock_si.return_value = mock_inst

            extractor = _make_full_extractor(
                dialect="postgresql",
                table_rows=[
                    {
                        "TABLE_NAME": "users",
                        "TABLE_TYPE": "TABLE",
                        "REMARKS": "User accounts",
                        "TABLE_SCHEM": "public",
                    },
                ],
            )
            tables = extractor.get_tables("public")
            self.assertEqual(tables[0].comment, "User accounts")

    def test_metadata_not_available_raises(self):
        extractor = _make_extractor()
        extractor.vendor_queries.get_tables_query.return_value = None
        extractor.ensure_metadata = MagicMock()
        with self.assertRaises(RuntimeError):
            extractor.get_tables("public")

    def test_column_extractor_called(self):
        with self._patch_si() as mock_si:
            mock_inst = MagicMock()
            mock_inst.enrich_columns_with_computed = MagicMock()
            mock_inst._apply_vendor_table_properties = MagicMock()
            mock_inst.enrich_table_with_partition_scheme = MagicMock()
            mock_si.return_value = mock_inst

            extractor = _make_full_extractor(
                dialect="postgresql",
                table_rows=[
                    {
                        "TABLE_NAME": "orders",
                        "TABLE_TYPE": "TABLE",
                        "REMARKS": None,
                        "TABLE_SCHEM": "public",
                    }
                ],
            )
            extractor.get_tables("public")
            extractor.column_extractor.get_columns.assert_called_once_with("public", "orders")

    def test_constraint_extractor_called(self):
        with self._patch_si() as mock_si:
            mock_inst = MagicMock()
            mock_inst.enrich_columns_with_computed = MagicMock()
            mock_inst._apply_vendor_table_properties = MagicMock()
            mock_inst.enrich_table_with_partition_scheme = MagicMock()
            mock_si.return_value = mock_inst

            extractor = _make_full_extractor(
                dialect="postgresql",
                table_rows=[
                    {
                        "TABLE_NAME": "orders",
                        "TABLE_TYPE": "TABLE",
                        "REMARKS": None,
                        "TABLE_SCHEM": "public",
                    }
                ],
            )
            extractor.get_tables("public")
            extractor.constraint_extractor.get_constraints.assert_called_once_with(
                "public", "orders"
            )

    def test_column_extractor_failure_sets_empty_columns(self):
        with self._patch_si() as mock_si:
            mock_inst = MagicMock()
            mock_inst.enrich_columns_with_computed = MagicMock()
            mock_inst._apply_vendor_table_properties = MagicMock()
            mock_inst.enrich_table_with_partition_scheme = MagicMock()
            mock_si.return_value = mock_inst

            extractor = _make_full_extractor(
                dialect="postgresql",
                table_rows=[
                    {
                        "TABLE_NAME": "broken",
                        "TABLE_TYPE": "TABLE",
                        "REMARKS": None,
                        "TABLE_SCHEM": "public",
                    }
                ],
            )
            extractor.column_extractor.get_columns.side_effect = Exception("column error")
            tables = extractor.get_tables("public")
            self.assertEqual(tables[0].columns, [])

    def test_schema_mismatch_skips_table(self):
        with self._patch_si() as mock_si:
            mock_inst = MagicMock()
            mock_si.return_value = mock_inst

            extractor = _make_full_extractor(
                dialect="postgresql",
                table_rows=[
                    {
                        "TABLE_NAME": "orders",
                        "TABLE_TYPE": "TABLE",
                        "REMARKS": None,
                        "TABLE_SCHEM": "other_schema",
                    },
                ],
            )
            tables = extractor.get_tables("public")
            self.assertEqual(tables, [])


# --- _should_preload_materialized_views ---


class TestShouldPreloadMaterializedViews(unittest.TestCase):
    def test_returns_false_for_postgresql(self):
        e = _make_extractor(dialect="postgresql")
        self.assertFalse(e._should_preload_materialized_views("public"))

    def test_returns_false_for_mysql(self):
        e = _make_extractor(dialect="mysql")
        self.assertFalse(e._should_preload_materialized_views("mydb"))

    def test_returns_true_for_oracle_with_mv_support(self):
        vq = MagicMock()
        vq.supports_materialized_views.return_value = True
        e = _make_extractor(dialect="oracle", vendor_queries=vq)
        self.assertTrue(e._should_preload_materialized_views("MYSCHEMA"))

    def test_returns_false_for_oracle_without_vendor_queries(self):
        e = _make_extractor(dialect="oracle", vendor_queries=None)
        e.vendor_queries = None
        self.assertFalse(e._should_preload_materialized_views("MYSCHEMA"))


# --- _enrich_postgresql_table ---


class TestEnrichPostgresqlTable(unittest.TestCase):
    """PostgreSQL row-security / inheritance / policies enrichment is now a
    quirks hook (:meth:`PostgresqlQuirks.enrich_table_extra`); tests call
    it directly."""

    @staticmethod
    def _pg_quirks():
        from db.provider_registry import ProviderRegistry

        return ProviderRegistry.get_quirks("postgresql")

    def test_row_security_flags_set(self):
        vq = MagicMock()
        vq.get_table_row_security_query.return_value = ("SELECT 1", [])
        vq.get_table_inheritance_query.return_value = (None, [])
        vq.get_policies_query.return_value = (None, [])

        extractor = _make_extractor(dialect="postgresql", vendor_queries=vq)
        extractor.provider.query_executor.execute_query.return_value = [
            {"row_security": "YES", "force_row_security": "NO"}
        ]

        from core.sql_model.table import Table

        table = Table(name="users", schema="public", dialect="postgresql")
        self._pg_quirks().enrich_table_extra(extractor, "public", "users", table)

        self.assertTrue(table.get_dialect_option("postgresql", "row_security", default=False))
        self.assertFalse(
            table.get_dialect_option("postgresql", "force_row_security", default=False)
        )

    def test_table_inheritance_set(self):
        vq = MagicMock()
        vq.get_table_row_security_query.return_value = (None, [])
        vq.get_table_inheritance_query.return_value = ("SELECT 1", [])
        vq.get_policies_query.return_value = (None, [])

        extractor = _make_extractor(dialect="postgresql", vendor_queries=vq)
        extractor.provider.query_executor.execute_query.return_value = [
            {"parent_schema": "public", "parent_table": "base_table"}
        ]

        from core.sql_model.table import Table

        table = Table(name="child_table", schema="public", dialect="postgresql")
        self._pg_quirks().enrich_table_extra(extractor, "public", "child_table", table)

        self.assertIn("base_table", table.get_dialect_option("postgresql", "inherits", default=[]))

    def test_table_inheritance_cross_schema(self):
        vq = MagicMock()
        vq.get_table_row_security_query.return_value = (None, [])
        vq.get_table_inheritance_query.return_value = ("SELECT 1", [])
        vq.get_policies_query.return_value = (None, [])

        extractor = _make_extractor(dialect="postgresql", vendor_queries=vq)
        extractor.provider.query_executor.execute_query.return_value = [
            {"parent_schema": "other_schema", "parent_table": "base_table"}
        ]

        from core.sql_model.table import Table

        table = Table(name="child_table", schema="public", dialect="postgresql")
        self._pg_quirks().enrich_table_extra(extractor, "public", "child_table", table)

        self.assertIn(
            "other_schema.base_table",
            table.get_dialect_option("postgresql", "inherits", default=[]),
        )

    def test_policies_set(self):
        vq = MagicMock()
        vq.get_table_row_security_query.return_value = (None, [])
        vq.get_table_inheritance_query.return_value = (None, [])
        vq.get_policies_query.return_value = ("SELECT 1", [])

        extractor = _make_extractor(dialect="postgresql", vendor_queries=vq)
        extractor.provider.query_executor.execute_query.return_value = [
            {
                "policy_name": "usr_policy",
                "policy_command": "SELECT",
                "is_permissive": "YES",
                "roles": '["admin"]',
                "policy_qual": "user_id = current_user_id()",
                "policy_with_check": None,
            }
        ]

        from core.sql_model.table import Table

        table = Table(name="secure_data", schema="public", dialect="postgresql")
        self._pg_quirks().enrich_table_extra(extractor, "public", "secure_data", table)

        self.assertEqual(len(table.get_dialect_option("postgresql", "policies", default=[])), 1)
        self.assertEqual(
            table.get_dialect_option("postgresql", "policies", default=[])[0]["name"], "usr_policy"
        )

    def test_no_vendor_queries_early_return(self):
        extractor = _make_extractor(dialect="postgresql", vendor_queries=None)
        from core.sql_model.table import Table

        table = Table(name="users", schema="public", dialect="postgresql")
        # Should not raise
        self._pg_quirks().enrich_table_extra(extractor, "public", "users", table)


# --- _supplement_partitioned_tables ---


class TestSupplementPartitionedTables(unittest.TestCase):
    def test_non_postgresql_returns_unchanged(self):
        extractor = _make_extractor(dialect="mysql")
        from core.sql_model.table import Table

        tables = [Table(name="t", schema="s", dialect="mysql")]
        result = extractor._supplement_partitioned_tables("s", tables)
        self.assertEqual(result, tables)

    def test_postgresql_adds_missing_partitioned_tables(self):
        vq = MagicMock()
        vq.get_partitioned_tables_query.return_value = ("SELECT 1", [])
        extractor = _make_extractor(dialect="postgresql", vendor_queries=vq)

        col_ext = MagicMock()
        col_ext.get_columns.return_value = []
        con_ext = MagicMock()
        con_ext.get_constraints.return_value = []
        extractor.column_extractor = col_ext
        extractor.constraint_extractor = con_ext

        extractor.provider.query_executor.execute_query.return_value = [
            {"table_name": "orders_2024", "remarks": None}
        ]

        from core.sql_model.table import Table

        existing = [Table(name="users", schema="public", dialect="postgresql")]
        result = extractor._supplement_partitioned_tables("public", existing)

        names = [t.name for t in result]
        self.assertIn("orders_2024", names)
        self.assertIn("users", names)

    def test_postgresql_does_not_add_existing_table(self):
        vq = MagicMock()
        vq.get_partitioned_tables_query.return_value = ("SELECT 1", [])
        extractor = _make_extractor(dialect="postgresql", vendor_queries=vq)

        extractor.provider.query_executor.execute_query.return_value = [
            {"table_name": "users", "remarks": None}  # already exists
        ]

        from core.sql_model.table import Table

        existing = [Table(name="users", schema="public", dialect="postgresql")]
        result = extractor._supplement_partitioned_tables("public", existing)

        # Should not duplicate
        user_tables = [t for t in result if t.name == "users"]
        self.assertEqual(len(user_tables), 1)
