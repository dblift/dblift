"""SQL Server native introspector unit tests."""

from types import SimpleNamespace
from unittest.mock import MagicMock

from db.plugins.sqlserver.introspection.sqlserver_introspector import SQLServerIntrospector
from db.plugins.sqlserver.introspection.sqlserver_queries import SQLServerMetadataQueries


class _Provider:
    provider_transport = "native"

    def __init__(self):
        self.config = SimpleNamespace(database=SimpleNamespace(type="sqlserver"))
        self.connection = MagicMock()
        self.query_executor = MagicMock()
        self._execute_map: dict = {}

    def create_connection(self):
        return self.connection

    def execute_query(self, sql, params=None):
        for key, rows in self._execute_map.items():
            if key in sql:
                return rows
        return []


def _make_introspector(execute_map=None):
    provider = _Provider()
    if execute_map:
        provider._execute_map = execute_map
    introspector = SQLServerIntrospector(provider)
    vq = MagicMock()
    vq.get_tables_query.return_value = ("SELECT table_name", ["dbo"])
    vq.get_view_names_query.return_value = ("SELECT view_name", ["dbo"])
    vq.get_columns_query.return_value = ("SELECT column_name", ["dbo", "t"])
    vq.get_primary_key_query.return_value = ("SELECT pk", ["dbo", "t"])
    vq.get_foreign_keys_query.return_value = ("SELECT fk", ["dbo", "t"])
    vq.get_unique_constraints_query.return_value = (None, [])
    introspector.vendor_queries = vq
    return introspector, provider


def test_native_get_tables_filters_internal(monkeypatch):
    execute_map = {
        "table_name": [{"table_name": "orders"}, {"table_name": "dblift_schema_history"}],
        "view_name": [],
        "column_name": [
            {
                "column_name": "id",
                "data_type": "INT",
                "is_nullable": 0,
                "column_default": None,
                "is_primary_key": 1,
            }
        ],
        "pk": [],
        "fk": [],
    }
    introspector, _ = _make_introspector(execute_map)
    monkeypatch.setattr(introspector, "_ensure_metadata", lambda: None)
    monkeypatch.setattr(introspector, "get_check_constraints", MagicMock(return_value=[]))
    monkeypatch.setattr(introspector, "_apply_vendor_table_properties", MagicMock())
    monkeypatch.setattr(introspector, "enrich_table_with_partition_scheme", MagicMock())
    tables = introspector.get_tables("dbo")
    assert [t.name for t in tables] == ["orders"]


def test_native_get_tables_applies_table_enrichment(monkeypatch):
    execute_map = {
        "table_name": [{"table_name": "orders"}],
        "view_name": [],
        "column_name": [
            {
                "column_name": "id",
                "data_type": "INT",
                "is_nullable": 0,
                "column_default": None,
                "is_primary_key": 1,
            }
        ],
        "pk": [],
        "fk": [],
    }
    introspector, _ = _make_introspector(execute_map)
    apply_properties = MagicMock()
    enrich_partition = MagicMock()
    monkeypatch.setattr(introspector, "_ensure_metadata", lambda: None)
    monkeypatch.setattr(introspector, "get_check_constraints", MagicMock(return_value=[]))
    monkeypatch.setattr(introspector, "_apply_vendor_table_properties", apply_properties)
    monkeypatch.setattr(introspector, "enrich_table_with_partition_scheme", enrich_partition)

    tables = introspector.get_tables("dbo")

    assert [t.name for t in tables] == ["orders"]
    apply_properties.assert_called_once_with("dbo", "orders", tables[0])
    enrich_partition.assert_called_once_with("dbo", "orders", tables[0])


def test_native_get_tables_include_views(monkeypatch):
    execute_map = {
        "table_name": [{"table_name": "orders"}],
        "view_name": [{"view_name": "order_view"}],
        "column_name": [],
        "pk": [],
        "fk": [],
    }
    introspector, _ = _make_introspector(execute_map)
    monkeypatch.setattr(introspector, "_ensure_metadata", lambda: None)
    monkeypatch.setattr(introspector, "get_check_constraints", MagicMock(return_value=[]))
    monkeypatch.setattr(introspector, "_apply_vendor_table_properties", MagicMock())
    monkeypatch.setattr(introspector, "enrich_table_with_partition_scheme", MagicMock())
    tables = introspector.get_tables("dbo", include_views=True)
    names = {t.name for t in tables}
    assert "orders" in names and "order_view" in names


def test_native_constraints_include_check_constraints(monkeypatch):
    execute_map = {"pk": [], "fk": []}
    introspector, _ = _make_introspector(execute_map)
    check = MagicMock()
    monkeypatch.setattr(introspector, "get_check_constraints", MagicMock(return_value=[check]))
    constraints = introspector.get_constraints("dbo", "orders")
    assert constraints[-1] is check
    introspector.get_check_constraints.assert_called_once_with("dbo", "orders")


def test_columns_query_reads_tables_and_views():
    sql, params = SQLServerMetadataQueries().get_columns_query("dbo", "order_view")
    assert "sys.objects" in sql
    assert "o.type IN ('U', 'V')" in sql
    assert "sys.tables t" not in sql
    assert params == ["dbo", "order_view"]
