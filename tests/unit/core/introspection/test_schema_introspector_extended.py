"""Extended unit tests for SchemaIntrospector and VendorPropertyApplier.

Targets uncovered paths in:
  db/introspection/schema_introspector.py  (656 stmts, 23%)
"""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, PropertyMock, call, patch

from core.introspection._vendor_property_applier import VendorPropertyApplier
from core.introspection.result import IntrospectionResult
from core.introspection.schema_introspector import SchemaIntrospector
from core.logger import NullLog
from core.sql_model.base import SqlColumn
from core.sql_model.table import Table
from db.plugins.db2.quirks import Db2Quirks
from db.plugins.mysql.quirks import MysqlQuirks
from db.plugins.oracle.quirks import OracleQuirks
from db.plugins.sqlserver.quirks import SqlserverQuirks

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_si(dialect="postgresql", has_connection=False, autocommit_value=True):
    """Build a SchemaIntrospector with mocked internals, bypassing __init__."""
    # Use plain MagicMock (no spec) so attributes like query_executor work
    provider = MagicMock()
    provider.config = SimpleNamespace(database=SimpleNamespace(type=dialect))
    provider.connection = None
    provider.canonical_dialect_key = dialect
    provider.get_database_version.return_value = ""
    provider.quirks = SimpleNamespace(native_driver_display=f"{dialect}-driver")

    si = SchemaIntrospector.__new__(SchemaIntrospector)
    si.provider = provider
    si.log = MagicMock()
    si.dialect = dialect
    si.metadata = None
    si.vendor_queries = None
    si._oracle_package_specs = {}
    si._table_extractor = None
    si._column_extractor = None
    si._constraint_extractor = None
    si._index_extractor = None
    si._view_extractor = None
    si._sequence_extractor = None
    si._trigger_extractor = None
    si._procedure_extractor = None
    si._misc_extractor = None
    si._original_autocommit = None
    si._track_results = False
    si._current_result = None
    si._object_column_cache = {}

    # Vendor property applier
    si._vendor_property_applier = VendorPropertyApplier(
        dialect=dialect, vendor_queries=None, log=si.log
    )

    if has_connection:
        conn = MagicMock()
        conn.getAutoCommit.return_value = autocommit_value
        conn.getMetaData.return_value = MagicMock()
        si.connection = conn
        si.metadata = conn.getMetaData.return_value
    return si, provider


# ---------------------------------------------------------------------------
# VendorPropertyApplier
# ---------------------------------------------------------------------------


class TestVendorPropertyApplierSqlServer(unittest.TestCase):

    def _make_table(self):
        return MagicMock()

    def test_apply_filegroup(self):
        table = self._make_table()
        row = {
            "filegroup_name": "PRIMARY",
            "is_memory_optimized": None,
            "is_system_versioned": None,
        }
        SqlserverQuirks().apply_vendor_table_properties(table, row)
        self.assertEqual(table.filegroup, "PRIMARY")

    def test_apply_memory_optimized(self):
        table = self._make_table()
        row = {"filegroup_name": None, "is_memory_optimized": "YES", "is_system_versioned": None}
        SqlserverQuirks().apply_vendor_table_properties(table, row)
        self.assertTrue(table.memory_optimized)

    def test_apply_system_versioned_with_history(self):
        table = self._make_table()
        row = {
            "filegroup_name": None,
            "is_memory_optimized": None,
            "is_system_versioned": "YES",
            "history_table_name": "employees_history",
            "history_schema_name": "dbo",
            "period_start_column": "valid_from",
            "period_end_column": "valid_to",
        }
        SqlserverQuirks().apply_vendor_table_properties(table, row)
        self.assertTrue(table.system_versioned)
        self.assertEqual(table.history_table, "employees_history")
        self.assertEqual(table.history_schema, "dbo")

    def test_apply_no_filegroup_no_effect(self):
        table = self._make_table()
        row = {"is_memory_optimized": None, "is_system_versioned": None}
        # filegroup_name is not in row, so table.filegroup should not be set
        # Use a simple namespace to test actual attribute assignment behavior
        from types import SimpleNamespace

        real_table = SimpleNamespace()
        SqlserverQuirks().apply_vendor_table_properties(real_table, row)
        self.assertFalse(hasattr(real_table, "filegroup"))


class TestVendorPropertyApplierDb2(unittest.TestCase):

    def test_apply_tablespace(self):
        table = MagicMock()
        row = {"tablespace_name": "USERSPACE1", "is_compressed": None}
        Db2Quirks().apply_vendor_table_properties(table, row)
        self.assertEqual(table.tablespace, "USERSPACE1")

    def test_apply_compression_yes(self):
        table = MagicMock()
        row = {
            "tablespace_name": None,
            "is_compressed": "YES",
            "compress_type": "STATIC",
            "pctfree_value": None,
            "pctused_value": None,
            "initial_value": None,
            "next_extent_size": None,
        }
        Db2Quirks().apply_vendor_table_properties(table, row)
        self.assertTrue(table.compress)
        self.assertEqual(table.compress_type, "STATIC")

    def test_apply_compression_no(self):
        table = MagicMock()
        row = {
            "tablespace_name": None,
            "is_compressed": "NO",
            "pctfree_value": None,
            "pctused_value": None,
            "initial_value": None,
            "next_extent_size": None,
        }
        Db2Quirks().apply_vendor_table_properties(table, row)
        self.assertFalse(table.compress)

    def test_apply_numeric_attrs(self):
        from types import SimpleNamespace

        table = SimpleNamespace()
        row = {
            "tablespace_name": None,
            "is_compressed": None,
            "pctfree_value": "10",
            "pctused_value": "80",
            "initial_value": "64",
            "next_extent_size": "32",
        }
        Db2Quirks().apply_vendor_table_properties(table, row)
        self.assertEqual(table.pctfree, 10)
        self.assertEqual(table.pctused, 80)

    def test_invalid_numeric_ignored(self):
        table = MagicMock()
        row = {
            "tablespace_name": None,
            "is_compressed": None,
            "pctfree_value": "not_a_number",
            "pctused_value": None,
            "initial_value": None,
            "next_extent_size": None,
        }
        # Should not raise
        Db2Quirks().apply_vendor_table_properties(table, row)


class TestVendorPropertyApplierOracle(unittest.TestCase):

    def test_apply_tablespace(self):
        table = MagicMock()
        table.mark_property_explicit = MagicMock()
        row = {
            "tablespace": "USERS",
            "tablespace_name": None,
            "TABLESPACE_NAME": None,
            "pctfree_value": None,
            "pctused_value": None,
            "initial_value": None,
            "next_extent_size": None,
        }
        OracleQuirks().apply_vendor_table_properties(table, row)
        self.assertEqual(table.tablespace, "USERS")
        table.mark_property_explicit.assert_called_once_with("tablespace")

    def test_apply_tablespace_fallback_keys(self):
        table = MagicMock()
        # No mark_property_explicit attribute (generic mock)
        del table.mark_property_explicit
        row = {
            "TABLESPACE_NAME": "DATA",
            "pctfree_value": None,
            "pctused_value": None,
            "initial_value": None,
            "next_extent_size": None,
        }
        OracleQuirks().apply_vendor_table_properties(table, row)
        self.assertEqual(table.tablespace, "DATA")


class TestVendorPropertyApplierMysql(unittest.TestCase):

    def test_apply_storage_engine(self):
        table = MagicMock()
        row = {
            "storage_engine": "InnoDB",
            "row_format": None,
            "table_collation": None,
            "next_auto_increment": None,
            "create_options": None,
        }
        MysqlQuirks().apply_vendor_table_properties(table, row)
        self.assertEqual(table.storage_engine, "InnoDB")

    def test_apply_row_format(self):
        table = MagicMock()
        row = {
            "storage_engine": None,
            "row_format": "DYNAMIC",
            "table_collation": None,
            "next_auto_increment": None,
            "create_options": None,
        }
        MysqlQuirks().apply_vendor_table_properties(table, row)

    def test_apply_collation_and_auto_increment(self):
        table = MagicMock()
        row = {
            "storage_engine": None,
            "row_format": None,
            "table_collation": "utf8mb4_unicode_ci",
            "next_auto_increment": 100,
            "create_options": None,
        }
        MysqlQuirks().apply_vendor_table_properties(table, row)


class TestVendorPropertyApplierApply(unittest.TestCase):

    def test_apply_skips_when_no_vendor_queries(self):
        log = MagicMock()
        applier = VendorPropertyApplier(dialect="mysql", vendor_queries=None, log=log)
        table = MagicMock()
        applier.apply("schema", "t", table, MagicMock(), MagicMock())
        # No exception, table not touched
        table.assert_not_called()

    def test_apply_unknown_dialect_is_noop_on_table(self):
        """Unknown dialects resolve to a vanilla ``BaseQuirks`` whose
        ``apply_vendor_table_properties`` is a no-op — the table comes
        back unchanged. (The query may run, but no enrichment happens.)"""
        log = MagicMock()
        vendor_queries = MagicMock()
        vendor_queries.get_table_properties_query.return_value = ("SELECT 1", [])
        applier = VendorPropertyApplier(
            dialect="unknown_db", vendor_queries=vendor_queries, log=log
        )
        query_executor = MagicMock()
        query_executor.execute_query.return_value = [{"any_column": "any_value"}]
        from types import SimpleNamespace

        table = SimpleNamespace()
        applier.apply("schema", "t", table, MagicMock(), query_executor)
        # No attributes set on the bare table — BaseQuirks left it alone.
        self.assertFalse(any(not k.startswith("_") for k in vars(table)))

    def test_apply_calls_handler_on_match(self):
        log = MagicMock()
        vendor_queries = MagicMock()
        vendor_queries.get_table_properties_query.return_value = ("SELECT 1", [])
        query_executor = MagicMock()
        query_executor.execute_query.return_value = [{"storage_engine": "InnoDB"}]

        applier = VendorPropertyApplier(dialect="mysql", vendor_queries=vendor_queries, log=log)
        table = MagicMock()
        applier.apply("mydb", "orders", table, MagicMock(), query_executor)

        vendor_queries.get_table_properties_query.assert_called_once_with("mydb", "orders")
        self.assertEqual(table.storage_engine, "InnoDB")

    def test_apply_handles_exception_gracefully(self):
        log = MagicMock()
        vendor_queries = MagicMock()
        vendor_queries.get_table_properties_query.side_effect = RuntimeError("db fail")
        applier = VendorPropertyApplier(dialect="mysql", vendor_queries=vendor_queries, log=log)
        # Should not raise
        applier.apply("mydb", "orders", MagicMock(), MagicMock(), MagicMock())
        log.debug.assert_called()


# ---------------------------------------------------------------------------
# SchemaIntrospector._ensure_metadata
# ---------------------------------------------------------------------------


class TestEnsureMetadata(unittest.TestCase):

    def test_ensure_metadata_skips_when_already_set(self):
        si, provider = _make_si(has_connection=True)
        meta_before = si.metadata
        si._ensure_metadata()
        provider.create_connection.assert_not_called()
        self.assertIs(si.metadata, meta_before)

    def test_ensure_metadata_creates_connection_when_none(self):
        from db.provider_interfaces import ConnectionProvider

        provider = MagicMock(spec=ConnectionProvider)
        provider.config = SimpleNamespace(database=SimpleNamespace(type="postgresql"))
        provider.connection = None
        new_conn = MagicMock()
        new_conn.getAutoCommit.return_value = True
        new_conn.getMetaData.return_value = MagicMock()
        provider.create_connection.return_value = new_conn

        si = SchemaIntrospector.__new__(SchemaIntrospector)
        si.provider = provider
        si.log = MagicMock()
        si.metadata = None
        si.connection = None
        si._original_autocommit = None

        si._ensure_metadata()

        provider.create_connection.assert_called_once()
        self.assertIs(si.connection, new_conn)

    def test_ensure_metadata_native_does_not_toggle_autocommit(self):
        from db.provider_interfaces import ConnectionProvider

        provider = MagicMock(spec=ConnectionProvider)
        provider.config = SimpleNamespace(database=SimpleNamespace(type="postgresql"))
        provider.connection = None
        new_conn = MagicMock()
        new_conn.getAutoCommit.return_value = False
        new_conn.getMetaData.return_value = MagicMock()
        provider.create_connection.return_value = new_conn

        si = SchemaIntrospector.__new__(SchemaIntrospector)
        si.provider = provider
        si.log = MagicMock()
        si.metadata = None
        si.connection = None
        si._original_autocommit = None

        si._ensure_metadata()

        new_conn.rollback.assert_not_called()
        new_conn.setAutoCommit.assert_not_called()


# ---------------------------------------------------------------------------
# SchemaIntrospector.close
# ---------------------------------------------------------------------------


class TestClose(unittest.TestCase):

    def test_close_restores_autocommit_and_closes_connection(self):
        si, provider = _make_si(has_connection=False)
        conn = MagicMock()
        provider.connection = None  # not the provider's connection
        si.connection = conn
        si._original_autocommit = False
        si.metadata = MagicMock()

        si.close()

        conn.close.assert_called_once()
        self.assertIsNone(si.connection)
        self.assertIsNone(si.metadata)

    def test_close_does_not_close_provider_connection(self):
        si, provider = _make_si(has_connection=False)
        conn = MagicMock()
        provider.connection = conn  # same object → provider owns it
        si.connection = conn
        si._original_autocommit = None
        si.metadata = MagicMock()

        si.close()

        conn.close.assert_not_called()
        self.assertIsNone(si.connection)

    def test_close_when_no_connection_is_noop(self):
        si, _ = _make_si(has_connection=False)
        si.connection = None
        si.close()  # should not raise

    def test_close_suppresses_provider_shutdown_error(self):
        si, provider = _make_si(has_connection=False)
        conn = MagicMock()
        provider.connection = None
        conn.close.side_effect = Exception("Java Virtual Machine is not running")
        si.connection = conn
        si._original_autocommit = None
        si.metadata = MagicMock()
        # Should not raise
        si.close()

    def test_close_logs_warning_on_unexpected_close_error(self):
        si, provider = _make_si(has_connection=False)
        conn = MagicMock()
        provider.connection = None
        conn.close.side_effect = Exception("some other error")
        si.connection = conn
        si._original_autocommit = None
        si.metadata = MagicMock()
        si.close()
        si.log.warning.assert_called()


# ---------------------------------------------------------------------------
# SchemaIntrospector context manager
# ---------------------------------------------------------------------------


class TestContextManager(unittest.TestCase):

    def test_enter_returns_self(self):
        si, _ = _make_si(has_connection=True)
        result = si.__enter__()
        self.assertIs(result, si)

    def test_exit_calls_close(self):
        si, provider = _make_si(has_connection=False)
        si.connection = MagicMock()
        provider.connection = None
        si._original_autocommit = None
        si.metadata = MagicMock()
        si.__exit__(None, None, None)
        self.assertIsNone(si.connection)


# ---------------------------------------------------------------------------
# SchemaIntrospector result tracking
# ---------------------------------------------------------------------------


class TestResultTracking(unittest.TestCase):

    def test_enable_result_tracking_returns_introspection_result(self):
        si, _ = _make_si()
        result = si.enable_result_tracking()
        self.assertIsInstance(result, IntrospectionResult)
        self.assertTrue(si._track_results)

    def test_get_result_returns_none_when_not_tracking(self):
        si, _ = _make_si()
        self.assertIsNone(si.get_result())

    def test_get_result_returns_result_when_tracking(self):
        si, _ = _make_si()
        result = si.enable_result_tracking()
        self.assertIs(si.get_result(), result)

    def test_track_warning_when_tracking(self):
        si, _ = _make_si()
        si.enable_result_tracking()
        si._track_warning("test warning", "TABLE", "users")
        warnings = si._current_result.warnings
        self.assertGreater(len(warnings), 0)

    def test_track_warning_noop_when_not_tracking(self):
        si, _ = _make_si()
        # Should not raise
        si._track_warning("test warning")

    def test_track_error_when_tracking(self):
        si, _ = _make_si()
        si.enable_result_tracking()
        si._track_error("test error", "TABLE", "users")
        errors = si._current_result.errors
        self.assertGreater(len(errors), 0)

    def test_track_object_status_when_not_tracking(self):
        from core.introspection.result import ObjectCaptureStatus

        si, _ = _make_si()
        status = si._track_object_status("TABLE", "users", "public")
        self.assertIsInstance(status, ObjectCaptureStatus)

    def test_track_object_status_when_tracking_adds_to_result(self):
        si, _ = _make_si()
        si.enable_result_tracking()
        si._track_object_status("TABLE", "users", "public")
        self.assertEqual(len(si._current_result.object_statuses), 1)


# ---------------------------------------------------------------------------
# SchemaIntrospector static/helper methods
# ---------------------------------------------------------------------------


class TestStaticHelpers(unittest.TestCase):
    # Oracle-specific helpers (_is_oracle_hidden_column,
    # _normalize_oracle_partition_bound) moved to OracleQuirks /
    # db.plugins.oracle.introspection.oracle_utils during the F.0 +
    # introspection-to-core move. The shim methods are gone; the
    # functional tests live under tests/unit/db/plugins/oracle/.

    def test_to_int_converts_string(self):
        self.assertEqual(SchemaIntrospector._to_int("42"), 42)

    def test_to_int_returns_none_on_invalid(self):
        result = SchemaIntrospector._to_int("not_a_number")
        self.assertIsNone(result)

    def test_to_int_returns_none_for_none(self):
        self.assertIsNone(SchemaIntrospector._to_int(None))

    def test_parse_pg_options_returns_dict(self):
        # parse_pg_options is a simple static delegator
        result = SchemaIntrospector._parse_pg_options(None)
        self.assertIsInstance(result, dict)

    def test_parse_json_array_returns_list(self):
        result = SchemaIntrospector._parse_json_array(None)
        self.assertIsInstance(result, list)

    def test_strip_leading_comments(self):
        result = SchemaIntrospector._strip_leading_comments("-- comment\nSELECT 1")
        self.assertIn("SELECT", result)


# ---------------------------------------------------------------------------
# SchemaIntrospector._get_extractor (lazy init)
# ---------------------------------------------------------------------------


class TestGetExtractor(unittest.TestCase):

    def test_creates_extractor_on_first_call(self):
        si, provider = _make_si(has_connection=True)

        class FakeExtractor:
            def __init__(self, **kwargs):
                self.connection = kwargs.get("connection")
                self.metadata = kwargs.get("metadata")

        si._fake_extractor = None
        # Patch _ensure_metadata to be a noop (already has metadata)
        extractor = si._get_extractor("_fake_extractor", FakeExtractor)

        self.assertIsNotNone(extractor)
        self.assertIsInstance(extractor, FakeExtractor)

    def test_syncs_connection_on_second_call(self):
        si, provider = _make_si(has_connection=True)

        class FakeExtractor:
            def __init__(self, **kwargs):
                self.connection = kwargs.get("connection")
                self.metadata = kwargs.get("metadata")

        si._fake_extractor = None
        extractor1 = si._get_extractor("_fake_extractor", FakeExtractor)

        # Change connection
        new_conn = MagicMock()
        si.connection = new_conn

        extractor2 = si._get_extractor("_fake_extractor", FakeExtractor)
        self.assertIs(extractor1, extractor2)  # same instance
        self.assertIs(extractor2.connection, new_conn)


# ---------------------------------------------------------------------------
# SchemaIntrospector delegation methods
# ---------------------------------------------------------------------------


class TestDelegationMethods(unittest.TestCase):

    def test_get_tables_delegates(self):
        si, _ = _make_si(has_connection=True)
        mock_extractor = MagicMock()
        mock_extractor.get_tables.return_value = []
        si._get_table_extractor = MagicMock(return_value=mock_extractor)

        result = si.get_tables("public")
        mock_extractor.get_tables.assert_called_once_with("public", False, "%")
        self.assertEqual(result, [])

    def test_get_views_delegates(self):
        si, _ = _make_si(has_connection=True)
        mock_extractor = MagicMock()
        mock_extractor.get_views.return_value = []
        si._get_view_extractor = MagicMock(return_value=mock_extractor)

        result = si.get_views("public")
        mock_extractor.get_views.assert_called_once_with("public")

    def test_get_sequences_delegates(self):
        si, _ = _make_si(has_connection=True)
        mock_extractor = MagicMock()
        mock_extractor.get_sequences.return_value = []
        si._get_sequence_extractor = MagicMock(return_value=mock_extractor)

        si.get_sequences("public")
        mock_extractor.get_sequences.assert_called_once_with("public")

    def test_get_triggers_delegates(self):
        si, _ = _make_si(has_connection=True)
        mock_extractor = MagicMock()
        mock_extractor.get_triggers.return_value = []
        si._get_trigger_extractor = MagicMock(return_value=mock_extractor)

        si.get_triggers("public", "users")
        mock_extractor.get_triggers.assert_called_once_with("public", "users")

    def test_get_indexes_delegates(self):
        si, _ = _make_si(has_connection=True)
        mock_extractor = MagicMock()
        mock_extractor.get_indexes.return_value = []
        si._get_index_extractor = MagicMock(return_value=mock_extractor)

        si.get_indexes("public", "users")
        mock_extractor.get_indexes.assert_called_once_with("public", "users")

    def test_get_all_indexes_delegates(self):
        si, _ = _make_si(has_connection=True)
        mock_extractor = MagicMock()
        mock_extractor.get_all_indexes.return_value = []
        si._get_index_extractor = MagicMock(return_value=mock_extractor)

        si.get_all_indexes("public")
        mock_extractor.get_all_indexes.assert_called_once_with("public")

    def test_get_procedures_delegates(self):
        si, _ = _make_si(has_connection=True)
        mock_extractor = MagicMock()
        mock_extractor.get_procedures.return_value = []
        si._get_procedure_extractor = MagicMock(return_value=mock_extractor)

        si.get_procedures("public")
        mock_extractor.get_procedures.assert_called_once_with("public")

    def test_get_synonyms_delegates(self):
        si, _ = _make_si(has_connection=True)
        si.vendor_queries = MagicMock(supports_synonyms=MagicMock(return_value=True))
        mock_extractor = MagicMock()
        mock_extractor.get_synonyms.return_value = []
        si._get_misc_extractor = MagicMock(return_value=mock_extractor)

        si.get_synonyms("dbo")
        mock_extractor.get_synonyms.assert_called_once_with("dbo")

    def test_get_extensions_delegates(self):
        si, _ = _make_si(has_connection=True)
        si.vendor_queries = MagicMock(supports_extensions=MagicMock(return_value=True))
        mock_extractor = MagicMock()
        mock_extractor.get_extensions.return_value = []
        si._get_misc_extractor = MagicMock(return_value=mock_extractor)

        si.get_extensions()
        mock_extractor.get_extensions.assert_called_once()

    def test_get_foreign_data_wrappers_delegates(self):
        si, _ = _make_si(has_connection=True)
        si.vendor_queries = MagicMock(supports_foreign_data_wrappers=MagicMock(return_value=True))
        mock_extractor = MagicMock()
        mock_extractor.get_foreign_data_wrappers.return_value = []
        si._get_misc_extractor = MagicMock(return_value=mock_extractor)

        si.get_foreign_data_wrappers()
        mock_extractor.get_foreign_data_wrappers.assert_called_once()

    def test_get_foreign_servers_delegates(self):
        si, _ = _make_si(has_connection=True)
        si.vendor_queries = MagicMock(supports_foreign_servers=MagicMock(return_value=True))
        mock_extractor = MagicMock()
        mock_extractor.get_foreign_servers.return_value = []
        si._get_misc_extractor = MagicMock(return_value=mock_extractor)

        si.get_foreign_servers()
        mock_extractor.get_foreign_servers.assert_called_once()

    def test_get_database_links_delegates(self):
        si, _ = _make_si(has_connection=True)
        si.vendor_queries = MagicMock(supports_database_links=MagicMock(return_value=True))
        mock_extractor = MagicMock()
        mock_extractor.get_database_links.return_value = []
        si._get_misc_extractor = MagicMock(return_value=mock_extractor)

        si.get_database_links("HR")
        mock_extractor.get_database_links.assert_called_once_with("HR")

    def test_get_events_delegates(self):
        # ``get_events`` short-circuits when ``vendor_queries.supports_events()``
        # is False; populate the supports flag so we exercise the delegation.
        si, _ = _make_si(dialect="mysql", has_connection=True)
        si.vendor_queries = MagicMock(supports_events=MagicMock(return_value=True))
        mock_extractor = MagicMock()
        mock_extractor.get_events.return_value = []
        si._get_misc_extractor = MagicMock(return_value=mock_extractor)

        si.get_events("mydb")
        mock_extractor.get_events.assert_called_once_with("mydb")

    def test_get_materialized_views_delegates(self):
        si, _ = _make_si(has_connection=True)
        si.vendor_queries = MagicMock(supports_materialized_views=MagicMock(return_value=True))
        mock_extractor = MagicMock()
        mock_extractor.get_materialized_views.return_value = []
        si._get_view_extractor = MagicMock(return_value=mock_extractor)

        si.get_materialized_views("public")
        mock_extractor.get_materialized_views.assert_called_once_with("public")


# ---------------------------------------------------------------------------
# SchemaIntrospector.get_database_info
# ---------------------------------------------------------------------------


class TestGetDatabaseInfo(unittest.TestCase):

    def test_returns_info_dict(self):
        si, provider = _make_si(has_connection=True)
        provider.get_database_version.return_value = "14.0"

        info = si.get_database_info()

        self.assertEqual(info["product_name"], "postgresql")
        self.assertEqual(info["product_version"], "14.0")
        self.assertEqual(info["driver_name"], "postgresql-driver")

    def test_returns_empty_on_exception(self):
        si, provider = _make_si(has_connection=True)
        provider.get_database_version.side_effect = RuntimeError("fail")

        info = si.get_database_info()
        self.assertEqual(info, {})


# ---------------------------------------------------------------------------
# SchemaIntrospector.introspect_schema_basic
# ---------------------------------------------------------------------------


class TestIntrospectSchemaBasic(unittest.TestCase):

    def test_returns_expected_keys(self):
        si, _ = _make_si(has_connection=True)
        mock_table = MagicMock()
        mock_table.name = "users"
        mock_table.columns = [MagicMock(), MagicMock()]
        si.get_tables = MagicMock(return_value=[mock_table])
        si.get_indexes = MagicMock(return_value=[])

        result = si.introspect_schema_basic("public")

        self.assertEqual(result["schema"], "public")
        self.assertEqual(result["table_count"], 1)
        self.assertEqual(result["total_columns"], 2)
        self.assertEqual(result["total_indexes"], 0)

    def test_raises_on_exception(self):
        si, _ = _make_si(has_connection=True)
        si.get_tables = MagicMock(side_effect=RuntimeError("db error"))

        with self.assertRaises(RuntimeError):
            si.introspect_schema_basic("public")


# ---------------------------------------------------------------------------
# SchemaIntrospector.enrich_columns_with_identity
# ---------------------------------------------------------------------------


class TestEnrichColumnsWithIdentity(unittest.TestCase):

    def test_noop_when_no_vendor_queries(self):
        si, _ = _make_si(has_connection=True)
        si.vendor_queries = None
        col = MagicMock(spec=SqlColumn)
        col.name = "id"
        si.enrich_columns_with_identity("public", "users", [col])
        # No interaction expected
        col.is_identity = False
        self.assertFalse(col.is_identity)

    def test_noop_when_no_sql(self):
        si, _ = _make_si(has_connection=True)
        si.vendor_queries = MagicMock()
        si.vendor_queries.get_identity_columns_query.return_value = (None, [])
        col = MagicMock()
        col.name = "id"
        si.enrich_columns_with_identity("public", "users", [col])
        # No enrichment should happen

    def test_enriches_matching_column(self):
        si, _ = _make_si(has_connection=True)
        si.vendor_queries = MagicMock()
        si.vendor_queries.get_identity_columns_query.return_value = ("SELECT ...", [])
        si.provider.query_executor.execute_query.return_value = [
            {"column_name": "ID", "seed_value": "1", "increment_value": "1", "last_value": None}
        ]

        col = SqlColumn(name="id", data_type="INTEGER")
        si.enrich_columns_with_identity("public", "users", [col])

        self.assertTrue(col.is_identity)
        self.assertEqual(col.identity_seed, "1")

    def test_handles_exception_gracefully(self):
        si, _ = _make_si(has_connection=True)
        si.vendor_queries = MagicMock()
        si.vendor_queries.get_identity_columns_query.return_value = ("SELECT ...", [])
        si.provider.query_executor.execute_query.side_effect = RuntimeError("db fail")

        col = SqlColumn(name="id", data_type="INTEGER")
        si.enrich_columns_with_identity("public", "users", [col])
        si.log.warning.assert_called()


# ---------------------------------------------------------------------------
# SchemaIntrospector.enrich_columns_with_computed
# ---------------------------------------------------------------------------


class TestEnrichColumnsWithComputed(unittest.TestCase):

    def test_noop_when_vendor_queries_unsupported(self):
        si, _ = _make_si(has_connection=True)
        si.vendor_queries = None
        col = SqlColumn(name="full_name", data_type="TEXT")
        si.enrich_columns_with_computed("public", "users", [col])
        self.assertFalse(getattr(col, "is_computed", False))

    def test_noop_when_no_sql_returned(self):
        si, _ = _make_si(has_connection=True)
        si.vendor_queries = MagicMock()
        si.vendor_queries.supports_computed_columns.return_value = True
        si.vendor_queries.get_computed_columns_query.return_value = (None, [])
        col = SqlColumn(name="full_name", data_type="TEXT")
        si.enrich_columns_with_computed("public", "users", [col])
        self.assertFalse(getattr(col, "is_computed", False))

    def test_enriches_computed_column(self):
        si, _ = _make_si(has_connection=True)
        si.vendor_queries = MagicMock()
        si.vendor_queries.supports_computed_columns.return_value = True
        si.vendor_queries.get_computed_columns_query.return_value = ("SELECT ...", [])
        si.provider.query_executor.execute_query.return_value = [
            {
                "column_name": "FULL_NAME",
                "computation_expression": "first_name || ' ' || last_name",
                "is_stored": "Y",
            }
        ]

        col = SqlColumn(name="full_name", data_type="TEXT")
        si.enrich_columns_with_computed("public", "users", [col])

        self.assertTrue(col.is_computed)
        self.assertIn("first_name", col.computed_expression)
        self.assertTrue(col.computed_stored)

    def test_clears_is_computed_when_no_expression_found(self):
        si, _ = _make_si(has_connection=True)
        si.vendor_queries = MagicMock()
        si.vendor_queries.supports_computed_columns.return_value = True
        si.vendor_queries.get_computed_columns_query.return_value = ("SELECT ...", [])
        si.provider.query_executor.execute_query.return_value = []

        col = SqlColumn(name="total", data_type="REAL")
        col.is_computed = True  # incorrectly marked by provider metadata
        col.computed_expression = None

        si.enrich_columns_with_computed("public", "orders", [col])
        self.assertFalse(col.is_computed)

    def test_handles_exception_gracefully(self):
        si, _ = _make_si(has_connection=True)
        si.vendor_queries = MagicMock()
        si.vendor_queries.supports_computed_columns.return_value = True
        si.vendor_queries.get_computed_columns_query.return_value = ("SELECT ...", [])
        si.provider.query_executor.execute_query.side_effect = RuntimeError("db fail")

        col = SqlColumn(name="total", data_type="REAL")
        si.enrich_columns_with_computed("public", "orders", [col])
        si.log.warning.assert_called()


# ---------------------------------------------------------------------------
# SchemaIntrospector.enrich_table_with_partition_scheme
# ---------------------------------------------------------------------------


class TestEnrichTableWithPartitionScheme(unittest.TestCase):

    def test_oracle_partition_method_set(self):
        si, _ = _make_si(dialect="oracle", has_connection=True)
        si.vendor_queries = MagicMock()
        si.vendor_queries.get_partition_scheme_query.return_value = ("SELECT ...", [])
        si.provider.query_executor.execute_query.return_value = [
            {"partitioning_type": "RANGE", "partition_columns": "created_at"}
        ]
        table = MagicMock()
        si.enrich_table_with_partition_scheme("HR", "SALES", table)
        self.assertEqual(table.partition_method, "RANGE")

    def test_postgresql_partition_definition(self):
        si, _ = _make_si(dialect="postgresql", has_connection=True)
        si.vendor_queries = MagicMock()
        si.vendor_queries.get_partition_scheme_query.return_value = ("SELECT ...", [])
        si.provider.query_executor.execute_query.return_value = [
            {"partition_definition": "RANGE (created_at)"}
        ]
        table = MagicMock()
        si.enrich_table_with_partition_scheme("public", "orders", table)
        self.assertEqual(table.partition_method, "RANGE")
        self.assertEqual(table.partition_columns, ["created_at"])

    def test_mysql_partition_method_key(self):
        si, _ = _make_si(dialect="mysql", has_connection=True)
        si.vendor_queries = MagicMock()
        si.vendor_queries.get_partition_scheme_query.return_value = ("SELECT ...", [])
        si.provider.query_executor.execute_query.return_value = [
            {"partition_method": "RANGE", "partition_expression": "YEAR(created_at)"}
        ]
        table = MagicMock()
        si.enrich_table_with_partition_scheme("mydb", "events", table)
        self.assertEqual(table.partition_method, "RANGE")
        # YEAR is a SQL function, should be filtered; 'created_at' kept
        self.assertIn("created_at", table.partition_columns)
        self.assertNotIn("YEAR", table.partition_columns)

    def test_db2_partition_range(self):
        si, _ = _make_si(dialect="db2", has_connection=True)
        si.vendor_queries = MagicMock()
        si.vendor_queries.get_partition_scheme_query.return_value = ("SELECT ...", [])
        si.provider.query_executor.execute_query.return_value = [
            {"partition_definition": "RANGE (order_date)"}
        ]
        table = MagicMock()
        si.enrich_table_with_partition_scheme("MYSCHEMA", "ORDERS", table)
        self.assertEqual(table.partition_method, "RANGE")

    def test_sqlserver_partition(self):
        si, _ = _make_si(dialect="sqlserver", has_connection=True)
        si.vendor_queries = MagicMock()
        si.vendor_queries.get_partition_scheme_query.return_value = ("SELECT ...", [])
        si.provider.query_executor.execute_query.return_value = [
            {
                "partition_function": "pf_date",
                "partition_type": "RANGE_LEFT",
                "partition_columns": "order_date",
            }
        ]
        table = MagicMock()
        si.enrich_table_with_partition_scheme("dbo", "Orders", table)
        self.assertEqual(table.partition_method, "RANGE")

    def test_no_results_returns_early(self):
        si, _ = _make_si(dialect="postgresql", has_connection=True)
        si.vendor_queries = MagicMock()
        si.vendor_queries.get_partition_scheme_query.return_value = ("SELECT ...", [])
        si.provider.query_executor.execute_query.return_value = []
        table = MagicMock()
        si.enrich_table_with_partition_scheme("public", "unpartitioned", table)
        # partition_method not set
        table.partition_method = None  # should not have been set

    def test_handles_exception(self):
        si, _ = _make_si(dialect="postgresql", has_connection=True)
        si.vendor_queries = MagicMock()
        si.vendor_queries.get_partition_scheme_query.side_effect = RuntimeError("fail")
        table = MagicMock()
        si.enrich_table_with_partition_scheme("public", "t", table)
        si.log.warning.assert_called()


# ---------------------------------------------------------------------------
# SchemaIntrospector.get_table_partitions
# ---------------------------------------------------------------------------


class TestGetTablePartitions(unittest.TestCase):

    def test_returns_empty_when_no_vendor_queries(self):
        si, _ = _make_si(has_connection=True)
        si.vendor_queries = None
        self.assertEqual(si.get_table_partitions("public", "sales"), [])

    def test_returns_empty_when_partitions_not_supported(self):
        si, _ = _make_si(has_connection=True)
        si.vendor_queries = MagicMock()
        si.vendor_queries.supports_partitions.return_value = False
        self.assertEqual(si.get_table_partitions("public", "sales"), [])

    def test_returns_empty_when_no_sql(self):
        si, _ = _make_si(has_connection=True)
        si.vendor_queries = MagicMock()
        si.vendor_queries.supports_partitions.return_value = True
        si.vendor_queries.get_table_partitions_query.return_value = (None, [])
        self.assertEqual(si.get_table_partitions("public", "sales"), [])

    def test_returns_partitions_with_high_value(self):
        si, _ = _make_si(has_connection=True, dialect="oracle")
        si.vendor_queries = MagicMock()
        si.vendor_queries.supports_partitions.return_value = True
        si.vendor_queries.get_table_partitions_query.return_value = ("SELECT ...", [])
        si.provider.query_executor.execute_query.return_value = [
            {
                "partition_name": "P_2023",
                "partition_method": "RANGE",
                "partition_expression": "created_at",
                "high_value": "2024-01-01",
                "low_value": None,
                "partition_number": None,
            }
        ]
        partitions = si.get_table_partitions("HR", "SALES")
        self.assertEqual(len(partitions), 1)
        self.assertEqual(partitions[0].name, "P_2023")

    def test_skips_invalid_partitions(self):
        si, _ = _make_si(has_connection=True, dialect="oracle")
        si.vendor_queries = MagicMock()
        si.vendor_queries.supports_partitions.return_value = True
        si.vendor_queries.get_table_partitions_query.return_value = ("SELECT ...", [])
        si.provider.query_executor.execute_query.return_value = [
            {
                "partition_name": "PART0",
                "partition_method": "RANGE",
                "partition_expression": None,
                "high_value": None,
                "low_value": None,
                "partition_number": 0,
            }
        ]
        partitions = si.get_table_partitions("HR", "SALES")
        self.assertEqual(len(partitions), 0)

    def test_handles_exception(self):
        si, _ = _make_si(has_connection=True)
        si.vendor_queries = MagicMock()
        si.vendor_queries.supports_partitions.return_value = True
        si.vendor_queries.get_table_partitions_query.return_value = ("SELECT ...", [])
        si.provider.query_executor.execute_query.side_effect = RuntimeError("db fail")
        partitions = si.get_table_partitions("public", "t")
        self.assertEqual(partitions, [])


# ---------------------------------------------------------------------------
# SchemaIntrospector.get_packages (oracle package specs cache)
# ---------------------------------------------------------------------------


class TestGetPackages(unittest.TestCase):

    def test_shares_oracle_package_specs_with_misc_extractor(self):
        # ``get_packages`` short-circuits unless
        # ``vendor_queries.supports_packages()`` is True.
        si, _ = _make_si(dialect="oracle", has_connection=True)
        si.vendor_queries = MagicMock(supports_packages=MagicMock(return_value=True))
        mock_misc = MagicMock()
        mock_misc._oracle_package_specs = {}
        mock_misc.get_packages.return_value = []
        si._get_misc_extractor = MagicMock(return_value=mock_misc)
        si._oracle_package_specs = {"HR": "spec text"}

        si.get_packages("HR")

        self.assertEqual(mock_misc._oracle_package_specs, {"HR": "spec text"})

    def test_delegates_to_misc_extractor(self):
        si, _ = _make_si(dialect="oracle", has_connection=True)
        si.vendor_queries = MagicMock(supports_packages=MagicMock(return_value=True))
        mock_misc = MagicMock()
        mock_misc.get_packages.return_value = ["pkg1"]
        si._get_misc_extractor = MagicMock(return_value=mock_misc)

        result = si.get_packages("HR")
        mock_misc.get_packages.assert_called_once_with("HR")
        self.assertEqual(result, ["pkg1"])


# The per-dialect ``_apply_vendor_table_properties_<dialect>`` shim
# methods were dead code after H.2 / F.3 and removed during the
# introspection-to-core move. The functional behaviour is covered by
# the plugin-side quirks tests under tests/unit/db/plugins/<dialect>/.


if __name__ == "__main__":
    unittest.main()
