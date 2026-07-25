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
        {"id": "doc-1", "script": "V1__x.sql", "success": False},
        {"id": "doc-2", "script": "V1__x.sql", "success": False},
    ]
    manager.history_container = container

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
    manager.history_container = container

    assert manager.delete_failed_migration_entry(None, "default", "V1__x.sql") == 0
    container.delete_item.assert_not_called()
