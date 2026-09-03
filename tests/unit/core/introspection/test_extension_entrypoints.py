"""Tests for neutral introspection extension entry points."""

from unittest.mock import MagicMock


class _EntryPoint:
    def __init__(self, name, func):
        self.name = name
        self._func = func

    def load(self):
        return self._func


def test_introspector_factory_loads_registered_introspection_extensions(monkeypatch):
    from dblift.core.introspection.introspector_factory import IntrospectorFactory

    calls = []

    class RegisteredIntrospector:
        def __init__(self, *_args):
            pass

    def register():
        calls.append("registered")
        IntrospectorFactory.register("registered_db", RegisteredIntrospector)

    monkeypatch.setattr(
        "dblift.core.introspection.introspector_factory.entry_points",
        lambda group: (
            [_EntryPoint("registered", register)] if group == "dblift.introspection" else []
        ),
    )
    IntrospectorFactory._DIALECT_MAP.clear()

    provider = MagicMock()
    provider.config.database.type = "registered_db"

    result = IntrospectorFactory.create(provider)

    assert isinstance(result, RegisteredIntrospector)
    assert calls == ["registered"]


def test_introspector_factory_logs_failed_introspection_extensions(monkeypatch, caplog):
    from dblift.core.introspection.introspector_factory import IntrospectorFactory

    def register():
        raise RuntimeError("extension failed")

    monkeypatch.setattr(
        "dblift.core.introspection.introspector_factory.entry_points",
        lambda group: [_EntryPoint("broken", register)] if group == "dblift.introspection" else [],
    )
    monkeypatch.setattr("dblift.db.provider_registry.ProviderRegistry.list_plugins", lambda: [])
    IntrospectorFactory._DIALECT_MAP.clear()

    IntrospectorFactory._register_defaults()

    assert "dblift.introspection 'broken' failed to register: extension failed" in caplog.text


def test_vendor_queries_factory_loads_registered_introspection_extensions(monkeypatch):
    from dblift.core.introspection import vendor_queries_factory
    from dblift.core.introspection.vendor_queries_base import VendorMetadataQueries
    from dblift.core.introspection.vendor_queries_factory import VendorQueriesFactory

    class RegisteredQueries(VendorMetadataQueries):
        def get_tables_query(self, schema, table_pattern="%"):
            return None

        def get_columns_query(self, schema, table):
            return None

        def get_indexes_query(self, schema, table=None):
            return None

        def get_views_query(self, schema):
            return None

        def get_view_definition_query(self, schema, view_name):
            return None

        def get_sequences_query(self, schema):
            return None

        def get_check_constraints_query(self, schema, table):
            return None

    def register():
        vendor_queries_factory.register_vendor_queries("registered_db", RegisteredQueries)

    monkeypatch.setattr(
        "dblift.core.introspection.vendor_queries_factory.entry_points",
        lambda group: (
            [_EntryPoint("registered", register)] if group == "dblift.introspection" else []
        ),
    )
    vendor_queries_factory._VENDOR_QUERIES_REGISTRY.clear()
    vendor_queries_factory._DEFAULTS_REGISTERED = False

    queries = VendorQueriesFactory.create("registered_db")

    assert isinstance(queries, RegisteredQueries)


def test_vendor_queries_factory_logs_failed_introspection_extensions(monkeypatch, caplog):
    from dblift.core.introspection import vendor_queries_factory

    def register():
        raise RuntimeError("extension failed")

    monkeypatch.setattr(
        "dblift.core.introspection.vendor_queries_factory.entry_points",
        lambda group: [_EntryPoint("broken", register)] if group == "dblift.introspection" else [],
    )
    monkeypatch.setattr("dblift.db.provider_registry.ProviderRegistry.list_plugins", lambda: [])
    vendor_queries_factory._VENDOR_QUERIES_REGISTRY.clear()
    vendor_queries_factory._DEFAULTS_REGISTERED = False

    vendor_queries_factory._register_defaults()

    assert "dblift.introspection 'broken' failed to register: extension failed" in caplog.text
