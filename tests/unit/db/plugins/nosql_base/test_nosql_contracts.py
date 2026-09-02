"""The NoSQL foundation names what a document-store plugin must provide.

CosmosDB is currently the only implementation. These tests pin the
contract so the second one (MongoDB) inherits a known surface instead of
inventing its own — and, crucially, so it cannot satisfy the surface with
a SQL-shaped front-end.
"""

import inspect

import pytest

from dblift.db.plugins.cosmosdb.cosmosdb.history_manager import CosmosDbHistoryManager
from dblift.db.plugins.cosmosdb.cosmosdb.locking_manager import CosmosDbLockingManager
from dblift.db.plugins.nosql_base import (
    DocumentHistoryManager,
    DocumentLockingManager,
    SamplingIntrospector,
)


def test_cosmos_managers_implement_the_document_contracts():
    assert issubclass(CosmosDbHistoryManager, DocumentHistoryManager)
    assert issubclass(CosmosDbLockingManager, DocumentLockingManager)


def test_cosmos_managers_leave_no_abstract_method_unimplemented():
    assert CosmosDbHistoryManager.__abstractmethods__ == frozenset()
    assert CosmosDbLockingManager.__abstractmethods__ == frozenset()


@pytest.mark.parametrize(
    "contract, required",
    [
        (DocumentHistoryManager, {"delete_failed_migration_entry"}),
        (
            DocumentLockingManager,
            {
                "create_migration_lock_container_if_not_exists",
                "acquire_migration_lock",
                "release_migration_lock",
            },
        ),
        (
            SamplingIntrospector,
            {"list_collections", "sample_documents", "infer_fields"},
        ),
    ],
)
def test_contract_declares_its_required_operations(contract, required):
    assert required <= set(contract.__abstractmethods__)


def test_history_create_table_returns_a_description_not_ddl():
    """A document store has no DDL; the string is for logs, not execution."""
    sql = DocumentHistoryManager.create_history_table(
        object.__new__(CosmosDbHistoryManager), "any", "dblift_schema_history"
    )
    assert "CREATE TABLE" not in sql.upper()
    assert sql.lstrip().startswith("--")


def test_foundation_carries_no_sql_generation():
    """Nothing in the foundation may compose SQL for a document store."""
    import dblift.db.plugins.nosql_base.history as history_mod
    import dblift.db.plugins.nosql_base.introspection as introspection_mod
    import dblift.db.plugins.nosql_base.locking as locking_mod

    for module in (history_mod, locking_mod, introspection_mod):
        source = inspect.getsource(module).upper()
        for verb in ("INSERT INTO", "DELETE FROM", "UPDATE ", "CREATE TABLE", "DROP CONTAINER"):
            assert verb not in source, f"{module.__name__} composes SQL ({verb})"


def test_cosmos_locking_uses_the_shared_constructor():
    """The base __init__ must actually run, not be shadowed by a copy.

    ``CosmosDbLockingManager`` used to duplicate the base's assignments,
    leaving ``DocumentLockingManager.__init__`` dead — so a second document
    store inheriting it would have been relying on untested code.
    """
    from unittest.mock import MagicMock

    executor = MagicMock()
    executor.connection_manager = "connection-manager"

    manager = CosmosDbLockingManager(executor)

    assert manager.query_executor is executor
    assert manager.connection_manager == "connection-manager"
    assert manager.log is not None
    assert manager.lock_container is None


def test_locking_base_tolerates_an_executor_without_a_connection_manager():
    """A driver that exposes no connection manager must not break construction."""

    class _Impl(DocumentLockingManager):
        def create_migration_lock_container_if_not_exists(self, schema):
            raise NotImplementedError

        def acquire_migration_lock(self, schema, wait_timeout_seconds=60):
            raise NotImplementedError

        def release_migration_lock(self, schema):
            raise NotImplementedError

    manager = _Impl(object())

    assert manager.connection_manager is None
