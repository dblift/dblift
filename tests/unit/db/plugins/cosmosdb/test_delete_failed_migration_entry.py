"""Removing a failed history row is a history-manager responsibility.

``repair`` used to compose a raw ``DELETE FROM dblift_schema_history``
and hand it to ``provider.execute_statement`` — which on Cosmos DB meant
routing SQL through the pseudo-SQL DML emulator. The delete now belongs
to the history manager, so each backend expresses it natively: SQL for
relational dialects, ``delete_item`` for Cosmos.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

from db.plugins.base_history_manager import BaseHistoryManager
from db.plugins.cosmosdb.cosmosdb.history_manager import CosmosDbHistoryManager


class _QueryExecutor:
    def __init__(self, dialect="postgresql"):
        self.dialect_name = dialect
        self.connection_manager = SimpleNamespace(
            database=None,
            client=None,
            config=SimpleNamespace(database=SimpleNamespace(type=dialect)),
        )
        self.statements = []
        self.affected = 1

    def table_exists(self, connection, schema, table_name):
        return True

    def get_schema_qualified_name(self, schema, object_name):
        return f"{schema}.{object_name}" if schema else object_name

    def execute_statement(self, connection, sql, params=None):
        self.statements.append((sql, params))
        return self.affected


class _ConcreteHistoryManager(BaseHistoryManager):
    """Minimal concrete subclass — the abstract hooks are irrelevant here."""

    def create_migration_history_table_if_not_exists(self, *args, **kwargs):
        raise NotImplementedError

    def record_migration(self, *args, **kwargs):
        raise NotImplementedError

    def get_applied_migrations(self, *args, **kwargs):
        raise NotImplementedError

    def create_history_table(self, *args, **kwargs):
        raise NotImplementedError


def test_generic_history_manager_deletes_with_parameterised_sql():
    executor = _QueryExecutor()
    manager = _ConcreteHistoryManager(executor, None, None)

    removed = manager.delete_failed_migration_entry(None, "public", "V1__x.sql")

    assert removed == 1
    sql, params = executor.statements[0]
    assert "DELETE FROM public.dblift_schema_history" in " ".join(sql.split())
    assert "WHERE script = ?" in " ".join(sql.split())
    assert params == ["V1__x.sql"]


def test_generic_history_manager_reports_missing_row():
    executor = _QueryExecutor()
    executor.affected = 0
    manager = _ConcreteHistoryManager(executor, None, None)

    assert manager.delete_failed_migration_entry(None, "public", "V1__x.sql") == 0


def test_cosmos_history_manager_deletes_documents_via_sdk():
    executor = _QueryExecutor("cosmosdb")
    manager = CosmosDbHistoryManager(executor, None, None)
    container = MagicMock()
    container.query_items.return_value = [
        {"id": "doc-1", "script": "V1__x.sql", "success": False, "version": "1.0.0"},
        {"id": "doc-2", "script": "V1__x.sql", "success": False, "version": "1.0.1"},
    ]
    manager._history_containers["dblift_schema_history"] = container

    removed = manager.delete_failed_migration_entry(None, "default", "V1__x.sql")

    assert removed == 2
    assert container.delete_item.call_count == 2
    # No SQL reached the query executor — the SDK did the work.
    assert executor.statements == []


def test_cosmos_history_manager_returns_zero_when_no_failed_row():
    executor = _QueryExecutor("cosmosdb")
    manager = CosmosDbHistoryManager(executor, None, None)
    container = MagicMock()
    container.query_items.return_value = []
    manager._history_containers["dblift_schema_history"] = container

    assert manager.delete_failed_migration_entry(None, "default", "V1__x.sql") == 0
    container.delete_item.assert_not_called()


def test_delete_addresses_the_version_partition_key():
    """The container is partitioned on /version, not on the document id.

    Addressing a point delete with the wrong partition key returns 404,
    which the handler reads as "already deleted" — so the row would survive
    while repair reported nothing to remove.
    """
    executor = _QueryExecutor("cosmosdb")
    manager = CosmosDbHistoryManager(executor, None, None)
    container = MagicMock()
    container.query_items.return_value = [
        {"id": "V1__x.sql", "script": "V1__x.sql", "success": False, "version": "1.0.0"}
    ]
    manager._history_containers["dblift_schema_history"] = container

    assert manager.delete_failed_migration_entry(None, "default", "V1__x.sql") == 1

    kwargs = container.delete_item.call_args.kwargs
    assert kwargs["item"] == "V1__x.sql"
    assert kwargs["partition_key"] == "1.0.0"

    # The query must project the partition-key field, or it cannot be used.
    query = container.query_items.call_args.kwargs["query"]
    assert "c.version" in query


def test_repeatable_migration_uses_the_none_partition_sentinel():
    """R__ rows carry no version and live in the partition-keyless partition."""
    from db.plugins.cosmosdb.cosmosdb._sdk import NONE_PARTITION_KEY

    executor = _QueryExecutor("cosmosdb")
    manager = CosmosDbHistoryManager(executor, None, None)
    container = MagicMock()
    container.query_items.return_value = [
        {"id": "R__seed.sql", "script": "R__seed.sql", "success": False, "version": None}
    ]
    manager._history_containers["dblift_schema_history"] = container

    assert manager.delete_failed_migration_entry(None, "default", "R__seed.sql") == 1
    assert container.delete_item.call_args.kwargs["partition_key"] is NONE_PARTITION_KEY
