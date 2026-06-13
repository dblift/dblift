"""Tests for SchemaIntrospector exception paths (lines 153-156, 470-476, 504-505)."""

import unittest
from unittest.mock import MagicMock


def _make_introspector(dialect="postgresql"):
    from core.introspection.schema_introspector import SchemaIntrospector
    from db.provider_interfaces import ConnectionProvider

    provider = MagicMock(spec=ConnectionProvider)
    from types import SimpleNamespace

    provider.config = SimpleNamespace(database=SimpleNamespace(type=dialect))
    provider.connection = None
    log = MagicMock()
    intr = SchemaIntrospector(provider=provider, log=log, use_vendor_queries=False)
    return intr, provider, log


class TestApplyDb2PropertiesIntConversion(unittest.TestCase):
    def test_int_conversion_error_suppressed(self):
        from db.plugins.db2.quirks import Db2Quirks

        table = MagicMock()
        row = {"data_capture": "invalid_int"}
        # Should not raise — ValueError/TypeError caught
        try:
            Db2Quirks().apply_vendor_table_properties(table, row)
        except Exception as e:
            self.fail(f"Should not raise: {e}")


class TestAutoCommitExceptionPaths(unittest.TestCase):
    def test_connection_creation_exception_propagates(self):
        intr, provider, log = _make_introspector()
        intr.connection = None  # force ensure_metadata to run
        provider.create_connection.side_effect = RuntimeError("connect failed")
        with self.assertRaises(RuntimeError):
            intr._ensure_metadata()

    def test_existing_connection_skips_connection_creation(self):
        intr, provider, log = _make_introspector()
        conn = MagicMock()
        conn.closed = False
        intr.connection = conn
        intr._ensure_metadata()
        provider.create_connection.assert_not_called()


class TestCloseExceptionPaths(unittest.TestCase):
    def test_close_exception_warns(self):
        intr, provider, log = _make_introspector()
        conn = MagicMock()
        conn.close.side_effect = Exception("Cannot close")
        intr.connection = conn
        intr.close()
        log.warning.assert_called()

    def test_close_clears_connection(self):
        intr, provider, log = _make_introspector()
        conn = MagicMock()
        intr.connection = conn
        intr.close()
        self.assertIsNone(intr.connection)


class TestExtractorGetterMethods(unittest.TestCase):
    def _make(self):
        intr, provider, log = _make_introspector()
        intr.connection = MagicMock()
        intr.metadata = MagicMock()
        return intr

    def test_get_column_extractor(self):
        intr = self._make()
        extractor = intr._get_column_extractor()
        self.assertIsNotNone(extractor)

    def test_get_constraint_extractor(self):
        intr = self._make()
        extractor = intr._get_constraint_extractor()
        self.assertIsNotNone(extractor)

    def test_get_index_extractor(self):
        intr = self._make()
        extractor = intr._get_index_extractor()
        self.assertIsNotNone(extractor)

    def test_get_view_extractor(self):
        intr = self._make()
        extractor = intr._get_view_extractor()
        self.assertIsNotNone(extractor)

    def test_get_sequence_extractor(self):
        intr = self._make()
        extractor = intr._get_sequence_extractor()
        self.assertIsNotNone(extractor)

    def test_get_trigger_extractor(self):
        intr = self._make()
        extractor = intr._get_trigger_extractor()
        self.assertIsNotNone(extractor)

    def test_get_table_extractor(self):
        intr = self._make()
        extractor = intr._get_table_extractor()
        self.assertIsNotNone(extractor)

    def test_get_procedure_extractor(self):
        intr = self._make()
        extractor = intr._get_procedure_extractor()
        self.assertIsNotNone(extractor)
