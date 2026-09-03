"""Tests for db/plugins/cosmosdb/cosmosdb/schema_operations.py."""

import unittest
from unittest.mock import MagicMock


def _make_ops():
    from dblift.db.plugins.cosmosdb.cosmosdb.schema_operations import CosmosDbSchemaOperations

    qe = MagicMock()
    qe.connection_manager = MagicMock()
    qe.connection_manager.database = MagicMock()
    log = MagicMock()
    return CosmosDbSchemaOperations(query_executor=qe, log=log), qe, log


class TestCosmosDbSchemaOpsInit(unittest.TestCase):
    def test_stores_executor(self):
        ops, qe, _ = _make_ops()
        self.assertIs(ops.query_executor, qe)

    def test_null_log_default(self):
        from dblift.core.logger import NullLog
        from dblift.db.plugins.cosmosdb.cosmosdb.schema_operations import CosmosDbSchemaOperations

        qe = MagicMock()
        qe.connection_manager = MagicMock()
        ops = CosmosDbSchemaOperations(query_executor=qe, log=None)
        self.assertIsInstance(ops.log, NullLog)


class TestCreateSchemaIfNotExists(unittest.TestCase):
    def test_noop_for_cosmosdb(self):
        ops, *_ = _make_ops()
        ops.create_schema_if_not_exists(MagicMock(), "mydb")
        # Should not raise, CosmosDB doesn't have schemas

    def test_sets_current_schema_noop(self):
        ops, *_ = _make_ops()
        ops.set_current_schema(MagicMock(), "mydb")


class TestContainerExists(unittest.TestCase):
    def test_returns_true_when_container_found(self):
        ops, qe, _ = _make_ops()
        qe.connection_manager.database.list_containers.return_value = [
            {"id": "users"},
            {"id": "orders"},
        ]
        result = ops.container_exists("users")
        self.assertTrue(result)

    def test_returns_false_when_not_found(self):
        ops, qe, _ = _make_ops()
        db = qe.connection_manager.database
        db.get_container_client.return_value.read.side_effect = Exception("404 Not Found")
        db.list_containers.return_value = [{"id": "users"}]
        result = ops.container_exists("nonexistent")
        self.assertFalse(result)

    def test_returns_false_and_logs_when_no_database(self):
        # Connection failure returns False (preserves the ``-> bool``
        # contract callers depend on) but logs at error level so the
        # infra failure surfaces. Earlier ``raise RuntimeError`` broke
        # ``provider.create_container_if_not_exists`` which calls this
        # in a plain ``if`` predicate. (PR #241 Bugbot.)
        ops, qe, log = _make_ops()
        qe.connection_manager.database = None
        qe.connection_manager.create_connection.return_value = None
        result = ops.container_exists("users")
        self.assertFalse(result)
        log.error.assert_called()

    def test_returns_false_on_exception(self):
        ops, qe, _ = _make_ops()
        db = qe.connection_manager.database
        db.get_container_client.return_value.read.side_effect = Exception("SDK error")
        db.list_containers.side_effect = Exception("SDK error")
        result = ops.container_exists("users")
        self.assertFalse(result)


class TestTableExists(unittest.TestCase):
    def test_delegates_to_container_exists(self):
        ops, qe, _ = _make_ops()
        qe.connection_manager.database.list_containers.return_value = [{"id": "users"}]
        result = ops.table_exists(MagicMock(), "mydb", "users")
        self.assertTrue(result)


class TestGetTables(unittest.TestCase):
    def test_returns_container_list(self):
        ops, qe, _ = _make_ops()
        qe.connection_manager.database.list_containers.return_value = [
            {"id": "users"},
            {"id": "orders"},
        ]
        tables = ops.get_tables(MagicMock(), "mydb")
        self.assertEqual(len(tables), 2)

    def test_empty_database(self):
        ops, qe, _ = _make_ops()
        qe.connection_manager.database.list_containers.return_value = []
        tables = ops.get_tables(MagicMock(), "mydb")
        self.assertEqual(tables, [])


class TestGetDatabaseVersion(unittest.TestCase):
    def test_returns_version_string(self):
        ops, *_ = _make_ops()
        version = ops.get_database_version(MagicMock())
        self.assertIsInstance(version, str)


class TestCleanSchema(unittest.TestCase):
    def test_returns_summary(self):
        ops, qe, _ = _make_ops()
        qe.connection_manager.database.list_containers.return_value = []
        result = ops.clean_schema(MagicMock(), "mydb")
        self.assertIsNotNone(result)
