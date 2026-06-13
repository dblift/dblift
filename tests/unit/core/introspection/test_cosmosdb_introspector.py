"""Tests for db/introspection/databases/cosmosdb/cosmosdb_introspector.py."""

import unittest
from unittest.mock import MagicMock


def _make_provider():
    provider = MagicMock()
    provider.connection_manager = MagicMock()
    provider.connection_manager.database = MagicMock()
    return provider


def _make_introspector():
    from db.plugins.cosmosdb.introspection.cosmosdb_introspector import CosmosDbIntrospector

    provider = _make_provider()
    log = MagicMock()
    return CosmosDbIntrospector(provider=provider, log=log), provider, log


class TestCosmosDbIntrospectorInit(unittest.TestCase):
    def test_init_stores_provider(self):
        intr, provider, _ = _make_introspector()
        self.assertIs(intr.provider, provider)
        self.assertEqual(intr.dialect, "cosmosdb")

    def test_raises_without_connection_manager(self):
        from db.plugins.cosmosdb.introspection.cosmosdb_introspector import CosmosDbIntrospector

        provider = MagicMock(spec=[])  # no connection_manager
        with self.assertRaises(ValueError):
            CosmosDbIntrospector(provider=provider)

    def test_raises_without_database(self):
        from db.plugins.cosmosdb.introspection.cosmosdb_introspector import CosmosDbIntrospector

        provider = MagicMock()
        del provider.connection_manager.database  # Remove database attribute
        with self.assertRaises(ValueError):
            CosmosDbIntrospector(provider=provider)


class TestEnsureConnection(unittest.TestCase):
    def test_creates_connection_when_not_connected(self):
        intr, provider, _ = _make_introspector()
        provider.connection_manager.database = None
        intr._ensure_connection()
        provider.create_connection.assert_called_once()

    def test_skips_when_already_connected(self):
        intr, provider, _ = _make_introspector()
        provider.connection_manager.database = MagicMock()
        intr._ensure_connection()
        provider.create_connection.assert_not_called()


class TestGetTables(unittest.TestCase):
    def test_returns_tables_from_containers(self):
        intr, provider, _ = _make_introspector()
        containers = [
            {"id": "users", "partitionKey": {"paths": ["/id"]}},
            {"id": "orders", "partitionKey": {"paths": ["/userId"]}},
        ]
        provider.connection_manager.database.list_containers.return_value = containers
        tables = intr.get_tables("default")
        self.assertEqual(len(tables), 2)

    def test_skips_system_containers(self):
        intr, provider, _ = _make_introspector()
        containers = [
            {"id": "dblift_schema_history"},
            {"id": "users", "partitionKey": {"paths": ["/id"]}},
        ]
        provider.connection_manager.database.list_containers.return_value = containers
        tables = intr.get_tables("default")
        # Only 'users', not 'dblift_schema_history'
        self.assertEqual(len(tables), 1)
        self.assertEqual(tables[0].name, "users")

    def test_filters_by_pattern(self):
        intr, provider, _ = _make_introspector()
        containers = [
            {"id": "users", "partitionKey": {"paths": ["/id"]}},
            {"id": "orders", "partitionKey": {"paths": ["/id"]}},
        ]
        provider.connection_manager.database.list_containers.return_value = containers
        tables = intr.get_tables("default", table_pattern="user%")
        self.assertEqual(len(tables), 1)

    def test_raises_on_list_error(self):
        intr, provider, _ = _make_introspector()
        provider.connection_manager.database.list_containers.side_effect = Exception("SDK error")
        with self.assertRaises(RuntimeError):
            intr.get_tables("default")

    def test_returns_empty_list_when_no_containers(self):
        intr, provider, _ = _make_introspector()
        provider.connection_manager.database.list_containers.return_value = []
        tables = intr.get_tables("default")
        self.assertEqual(tables, [])


class TestGetViews(unittest.TestCase):
    def test_returns_empty(self):
        intr, *_ = _make_introspector()
        self.assertEqual(intr.get_views("default"), [])


class TestGetIndexes(unittest.TestCase):
    def test_returns_list(self):
        intr, *_ = _make_introspector()
        # CosmosDB may return partition key as index
        result = intr.get_indexes("default", "users")
        self.assertIsInstance(result, list)


class TestGetSequences(unittest.TestCase):
    def test_returns_empty(self):
        intr, *_ = _make_introspector()
        self.assertEqual(intr.get_sequences("default"), [])


class TestBuildTableFromContainer(unittest.TestCase):
    def test_builds_table_with_partition_key(self):
        intr, *_ = _make_introspector()
        container_props = {
            "partitionKey": {"paths": ["/id"], "kind": "Hash"},
            "indexingPolicy": {},
        }
        table = intr._build_table_from_container("users", container_props)
        self.assertIsNotNone(table)
        self.assertEqual(table.name, "users")

    def test_partition_key_stored_in_metadata(self):
        intr, *_ = _make_introspector()
        container_props = {"partitionKey": {"paths": ["/userId"], "kind": "Hash"}}
        table = intr._build_table_from_container("users", container_props)
        self.assertIsNotNone(table)
        self.assertIsInstance(table.metadata, dict)
        self.assertEqual(table.metadata["partition_key"], "/userId")

    def test_non_default_partition_key_not_overridden_by_id(self):
        intr, *_ = _make_introspector()
        container_props = {"partitionKey": {"paths": ["/category"], "kind": "Hash"}}
        table = intr._build_table_from_container("products", container_props)
        self.assertIsNotNone(table)
        self.assertNotEqual(table.metadata.get("partition_key"), "/id")
        self.assertEqual(table.metadata["partition_key"], "/category")

    def test_returns_none_on_error(self):
        intr, *_ = _make_introspector()
        # Pass None props to cause an error
        table = intr._build_table_from_container("users", None)
        # Should return None on exception
        self.assertIsNone(table)
