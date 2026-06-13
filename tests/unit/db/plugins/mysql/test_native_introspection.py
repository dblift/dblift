"""MySQL native introspection preserves plugin-owned vendor metadata."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from core.sql_model.base import ConstraintType, SqlColumn
from db.plugins.mysql.introspection.mysql_introspector import MySQLIntrospector


class _Provider:
    provider_transport = "native"
    engine = object()

    def __init__(self):
        self.config = SimpleNamespace(database=SimpleNamespace(type="mysql"))
        self.connection = MagicMock()
        self.query_executor = MagicMock()
        self._execute_map: dict = {}

    def create_connection(self):
        return self.connection

    def close(self):
        pass

    def is_connected(self):
        return True

    def connect(self):
        pass

    def execute_query(self, sql, params=None):
        """Return mock rows keyed by a substring of the query."""
        for key, rows in self._execute_map.items():
            if key in sql:
                return rows
        return []


def _make_introspector(execute_map=None):
    """Return a MySQLIntrospector with stubbed vendor queries and provider."""
    provider = _Provider()
    if execute_map:
        provider._execute_map = execute_map

    introspector = MySQLIntrospector(provider)

    # Stub vendor_queries with a MagicMock that returns proper (sql, params) tuples
    vq = MagicMock()
    vq.get_tables_query.return_value = ("SELECT table_name", ["app"])
    vq.get_view_names_query.return_value = ("SELECT view_name", ["app"])
    vq.get_columns_query.return_value = ("SELECT column_name", ["app", "orders"])
    vq.get_primary_key_query.return_value = ("SELECT pk", ["app", "orders"])
    vq.get_foreign_keys_query.return_value = ("SELECT fk", ["app", "orders"])
    vq.get_unique_constraints_query.return_value = (None, [])
    introspector.vendor_queries = vq

    return introspector, provider


def test_native_tables_use_vendor_enrichment_hooks(monkeypatch):
    """Enrichment hooks and _apply_vendor_table_properties are called for each table."""
    execute_map = {
        "table_name": [{"table_name": "orders"}],
        "view_name": [],
        "column_name": [
            {
                "column_name": "id",
                "data_type": "INTEGER",
                "is_nullable": 0,
                "column_default": None,
                "is_primary_key": 1,
            }
        ],
        "pk": [{"constraint_name": "PRIMARY", "column_name": "id"}],
        "fk": [],
    }
    introspector, _ = _make_introspector(execute_map)
    monkeypatch.setattr(introspector, "_ensure_metadata", lambda: None)

    applied_tables = []

    monkeypatch.setattr(
        introspector,
        "enrich_columns_with_computed",
        MagicMock(
            side_effect=lambda _schema, _table, columns: setattr(columns[0], "is_computed", True)
        ),
    )
    monkeypatch.setattr(
        introspector,
        "enrich_columns_with_identity",
        MagicMock(
            side_effect=lambda _schema, _table, columns: setattr(columns[0], "is_identity", True)
        ),
    )
    monkeypatch.setattr(
        introspector,
        "_apply_vendor_table_properties",
        MagicMock(side_effect=lambda _schema, _table, table: applied_tables.append(table)),
    )
    monkeypatch.setattr(introspector, "get_check_constraints", MagicMock(return_value=[]))

    tables = introspector.get_tables("app")

    assert len(tables) == 1
    assert tables[0].columns[0].is_computed is True
    assert tables[0].columns[0].is_identity is True
    assert applied_tables == tables
    introspector.enrich_columns_with_computed.assert_called_once_with(
        "app", "orders", tables[0].columns
    )
    introspector.enrich_columns_with_identity.assert_called_once_with(
        "app", "orders", tables[0].columns
    )
    introspector._apply_vendor_table_properties.assert_called_once_with("app", "orders", tables[0])


def test_native_tables_accept_uppercase_table_name_metadata(monkeypatch):
    """Native MySQL metadata rows may expose TABLE_NAME despite lowercase SQL aliases."""
    execute_map = {
        "table_name": [{"TABLE_NAME": "orders"}],
        "column_name": [
            {
                "COLUMN_NAME": "id",
                "data_type": "INTEGER",
                "is_nullable": 0,
                "COLUMN_DEFAULT": None,
                "is_primary_key": 1,
            }
        ],
        "pk": [{"CONSTRAINT_NAME": "PRIMARY", "COLUMN_NAME": "id"}],
        "fk": [],
    }
    introspector, _ = _make_introspector(execute_map)
    monkeypatch.setattr(introspector, "_ensure_metadata", lambda: None)
    monkeypatch.setattr(introspector, "enrich_columns_with_computed", MagicMock())
    monkeypatch.setattr(introspector, "enrich_columns_with_identity", MagicMock())
    monkeypatch.setattr(introspector, "_apply_vendor_table_properties", MagicMock())
    monkeypatch.setattr(introspector, "get_check_constraints", MagicMock(return_value=[]))

    tables = introspector.get_tables("app")

    assert [table.name for table in tables] == ["orders"]
    assert [column.name for column in tables[0].columns] == ["id"]
    assert tables[0].constraints[0].name == "PRIMARY"


def test_native_constraints_include_vendor_check_constraints(monkeypatch):
    """get_check_constraints result is appended to the constraint list."""
    execute_map = {
        "pk": [],
        "fk": [],
    }
    introspector, _ = _make_introspector(execute_map)

    check = MagicMock()
    check.constraint_type = ConstraintType.CHECK
    monkeypatch.setattr(introspector, "get_check_constraints", MagicMock(return_value=[check]))

    constraints = introspector.get_constraints("app", "orders")

    assert constraints[-1] is check
    introspector.get_check_constraints.assert_called_once_with("app", "orders")


def test_native_indexes_use_vendor_index_extractor():
    provider = _Provider()
    provider.query_executor.execute_query.return_value = [
        {
            "index_name": "idx_orders_payload",
            "column_name": "payload",
            "is_unique": "NO",
            "seq_in_index": 1,
            "index_type": "FULLTEXT",
            "collation": "D",
            "expression": "JSON_EXTRACT(payload, '$.customer')",
        }
    ]
    introspector = MySQLIntrospector(provider)

    indexes = introspector.get_indexes("app", "orders")

    assert len(indexes) == 1
    assert indexes[0].name == "idx_orders_payload"
    assert indexes[0].type == "FULLTEXT"
    assert indexes[0].columns
    provider.query_executor.execute_query.assert_called_once()
