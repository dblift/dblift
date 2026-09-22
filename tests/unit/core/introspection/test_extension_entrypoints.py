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
    from dblift.core.seams import introspection as introspection_seam

    calls = []

    class RegisteredIntrospector:
        def __init__(self, *_args):
            pass

    def register():
        calls.append("registered")
        IntrospectorFactory.register("registered_db", RegisteredIntrospector)

    monkeypatch.setattr(
        introspection_seam,
        "entry_points",
        lambda group: (
            [_EntryPoint("registered", register)] if group == "dblift.introspection" else []
        ),
    )
    monkeypatch.setattr(introspection_seam, "_introspection_attached", False)
    monkeypatch.setattr(introspection_seam, "_pending_entry_points", None)
    monkeypatch.setattr(IntrospectorFactory, "_DIALECT_MAP", {})
    monkeypatch.setattr(IntrospectorFactory, "_DEFAULTS_REGISTERED", False)

    provider = MagicMock()
    provider.config.database.type = "registered_db"

    result = IntrospectorFactory.create(provider)

    assert isinstance(result, RegisteredIntrospector)
    assert calls == ["registered"]


def test_vendor_queries_factory_loads_registered_introspection_extensions(monkeypatch):
    from dblift.core.introspection import vendor_queries_factory
    from dblift.core.introspection.vendor_queries_base import VendorMetadataQueries
    from dblift.core.introspection.vendor_queries_factory import VendorQueriesFactory
    from dblift.core.seams import introspection as introspection_seam

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
        introspection_seam,
        "entry_points",
        lambda group: (
            [_EntryPoint("registered", register)] if group == "dblift.introspection" else []
        ),
    )
    monkeypatch.setattr(introspection_seam, "_introspection_attached", False)
    monkeypatch.setattr(introspection_seam, "_pending_entry_points", None)
    monkeypatch.setattr(vendor_queries_factory, "_VENDOR_QUERIES_REGISTRY", {})
    monkeypatch.setattr(vendor_queries_factory, "_DEFAULTS_REGISTERED", False)

    queries = VendorQueriesFactory.create("registered_db")

    assert isinstance(queries, RegisteredQueries)


def test_repeated_introspector_creation_scans_extensions_once(monkeypatch):
    from dblift.core.introspection import introspector_factory, vendor_queries_factory
    from dblift.core.introspection.introspector_factory import IntrospectorFactory
    from dblift.core.seams import introspection as introspection_seam
    from dblift.db.provider_registry import ProviderRegistry

    scans = 0

    def count_entry_points(group):
        nonlocal scans
        if group == "dblift.introspection":
            scans += 1
        return []

    monkeypatch.setattr(introspector_factory, "entry_points", count_entry_points, raising=False)
    monkeypatch.setattr(vendor_queries_factory, "entry_points", count_entry_points, raising=False)
    monkeypatch.setattr(introspection_seam, "entry_points", count_entry_points)
    monkeypatch.setattr(IntrospectorFactory, "_DIALECT_MAP", {})
    monkeypatch.setattr(IntrospectorFactory, "_DEFAULTS_REGISTERED", False, raising=False)
    monkeypatch.setattr(vendor_queries_factory, "_VENDOR_QUERIES_REGISTRY", {})
    monkeypatch.setattr(vendor_queries_factory, "_DEFAULTS_REGISTERED", False)
    monkeypatch.setattr(introspection_seam, "_introspection_attached", False, raising=False)
    monkeypatch.setattr(introspection_seam, "_pending_entry_points", None, raising=False)
    monkeypatch.setattr(ProviderRegistry, "list_plugins", classmethod(lambda cls: []))

    provider = MagicMock()
    provider.config.database.type = "unknown"

    for _ in range(3):
        IntrospectorFactory.create(provider)

    assert scans == 1
