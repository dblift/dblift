"""Tests for db/introspection/base_introspector.py."""

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock


def _make_concrete(dialect="postgresql"):
    """Create minimal concrete BaseIntrospector subclass."""
    from core.introspection.base_introspector import BaseIntrospector

    class ConcreteIntrospector(BaseIntrospector):
        def get_tables(self, schema, include_views=False, table_pattern="%"):
            return []

        def get_indexes(self, schema, table):
            return []

        def get_sequences(self, schema):
            return []

        def get_views(self, schema):
            return []

        def get_check_constraints(self, schema, table):
            return []

        def introspect_schema(self, schema, **kwargs):
            return {}

        def get_materialized_views(self, schema):
            return []

        def get_procedures(self, schema):
            return []

        def get_functions(self, schema):
            return []

        def get_triggers(self, schema):
            return []

        def get_all_indexes(self, schema):
            return []

    provider = MagicMock()
    provider.config.database.type = dialect
    log = MagicMock()
    intr = ConcreteIntrospector(provider=provider, log=log, use_vendor_queries=False)
    return intr, provider, log


class TestBaseIntrospectorInit(unittest.TestCase):
    def test_stores_provider(self):
        intr, provider, _ = _make_concrete()
        self.assertIs(intr.provider, provider)

    def test_dialect_from_provider(self):
        intr, *_ = _make_concrete("oracle")
        self.assertEqual(intr.dialect, "oracle")

    def test_dialect_unknown_when_no_config(self):
        from core.introspection.base_introspector import BaseIntrospector

        class Minimal(BaseIntrospector):
            def get_tables(self, s, iv=False, tp="%"):
                return []

            def get_indexes(self, s, t):
                return []

            def get_sequences(self, s):
                return []

            def get_views(self, s):
                return []

            def get_check_constraints(self, s, t):
                return []

            def introspect_schema(self, s, **kw):
                return {}

            def get_materialized_views(self, s):
                return []

            def get_procedures(self, s):
                return []

            def get_functions(self, s):
                return []

            def get_triggers(self, s):
                return []

            def get_all_indexes(self, s):
                return []

        provider = MagicMock(spec=[])  # no config attr
        intr = Minimal(provider=provider, use_vendor_queries=False)
        self.assertEqual(intr.dialect, "unknown")

    def test_null_log_default(self):
        from core.introspection.base_introspector import BaseIntrospector
        from core.logger import NullLog

        class Minimal(BaseIntrospector):
            def get_tables(self, s, iv=False, tp="%"):
                return []

            def get_indexes(self, s, t):
                return []

            def get_sequences(self, s):
                return []

            def get_views(self, s):
                return []

            def get_check_constraints(self, s, t):
                return []

            def introspect_schema(self, s, **kw):
                return {}

            def get_materialized_views(self, s):
                return []

            def get_procedures(self, s):
                return []

            def get_functions(self, s):
                return []

            def get_triggers(self, s):
                return []

            def get_all_indexes(self, s):
                return []

        provider = MagicMock()
        provider.config.database.type = "postgresql"
        intr = Minimal(provider=provider, log=None, use_vendor_queries=False)
        self.assertIsInstance(intr.log, NullLog)


class TestBaseIntrospectorResultTracking(unittest.TestCase):
    def test_enable_result_tracking(self):
        intr, *_ = _make_concrete()
        result = intr.enable_result_tracking()
        self.assertIsNotNone(result)

    def test_get_result_returns_none_by_default(self):
        intr, *_ = _make_concrete()
        self.assertIsNone(intr.get_result())

    def test_get_result_after_tracking(self):
        intr, *_ = _make_concrete()
        intr.enable_result_tracking()
        result = intr.get_result()
        self.assertIsNotNone(result)

    def test_track_warning(self):
        intr, *_ = _make_concrete()
        intr.enable_result_tracking()
        intr._track_warning("test warning")  # should not raise

    def test_track_error(self):
        intr, *_ = _make_concrete()
        intr.enable_result_tracking()
        intr._track_error("test error")

    def test_track_object_status(self):
        intr, *_ = _make_concrete()
        intr.enable_result_tracking()
        intr._track_object_status(
            object_type="table",
            object_name="users",
            captured=True,
        )


class TestBaseIntrospectorClose(unittest.TestCase):
    def test_close_no_connection(self):
        intr, *_ = _make_concrete()
        intr.close()  # should not raise

    def test_close_with_connection(self):
        intr, provider, _ = _make_concrete()
        intr.connection = MagicMock()
        intr.close()


class TestBaseIntrospectorContextManager(unittest.TestCase):
    def test_enter_returns_self(self):
        intr, *_ = _make_concrete()
        result = intr.__enter__()
        self.assertIs(result, intr)

    def test_exit_no_error(self):
        intr, *_ = _make_concrete()
        intr.__exit__(None, None, None)

    def test_context_manager_protocol(self):
        intr, provider, _ = _make_concrete()
        with intr as i:
            self.assertIs(i, intr)


class TestEnsureMetadata(unittest.TestCase):
    """F.3.h merged SchemaIntrospector into BaseIntrospector. The
    ``_ensure_metadata`` path now requires the provider to implement
    :class:`ConnectionProvider`; otherwise it raises ``AttributeError``.
    These tests verify that contract instead of the simpler abstract
    behaviour the old BaseIntrospector had."""

    def test_ensure_metadata_raises_for_non_connection_provider(self):
        class NotAProvider:
            config = SimpleNamespace(database=SimpleNamespace(type="postgresql"))

        intr, *_ = _make_concrete()
        intr.provider = NotAProvider()
        with self.assertRaises(AttributeError):
            intr._ensure_metadata()

    def test_ensure_metadata_short_circuits_when_connection_present(self):
        intr, *_ = _make_concrete()
        intr.connection = MagicMock(closed=False)
        intr.metadata = MagicMock()
        intr._ensure_metadata()
        self.assertIsNotNone(intr.metadata)
