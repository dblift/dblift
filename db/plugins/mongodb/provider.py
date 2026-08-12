"""MongoDB provider implementation.

Uses modular components to handle MongoDB-specific database operations.
"""

from typing import Any, Dict, List, Optional

from config import DbliftConfig
from core.logger import Log
from core.migration.clean_summary import CleanExecutionSummary
from db.base_provider import NativeProvider
from db.plugins.mongodb.mongodb import (
    MongoDbConnectionManager,
    MongoDbHistoryManager,
    MongoDbLockingManager,
    MongoDbQueryExecutor,
    MongoDbSchemaOperations,
    MongoDbSnapshotManager,
)
from db.provider_interfaces import DroppableObject


class MongoDbProvider(NativeProvider):
    """MongoDB provider implementation using pymongo with modular components."""

    canonical_dialect_key = "mongodb"

    def __init__(self, config: DbliftConfig, log: Optional[Log] = None) -> None:
        """Initialize the provider and its components."""
        super().__init__(config, log)
        self.connection_manager = MongoDbConnectionManager(config, log=self.log)
        self.query_executor = MongoDbQueryExecutor(self.connection_manager, log=self.log)
        self.schema_operations = MongoDbSchemaOperations(self.query_executor, log=self.log)
        self.history_manager = MongoDbHistoryManager(
            self.query_executor, self.schema_operations, config, log=self.log
        )
        self.locking_manager = MongoDbLockingManager(self.query_executor, log=self.log)
        self.snapshot_manager = MongoDbSnapshotManager(self, log=self.log)

    # --- connection -------------------------------------------------------

    def create_connection(self) -> Any:
        """Open the driver connection and return the database handle."""
        return self.connection_manager.create_connection()

    def is_connected(self) -> bool:
        """Whether a database handle is currently held."""
        return self.connection_manager.database is not None

    def close(self) -> None:
        """Close the driver connection."""
        self.connection_manager.close()

    def get_database_url(self) -> str:
        """Return the masked connection URI."""
        return self.connection_manager.get_database_url() or ""

    def get_display_url(self) -> str:
        """Return the URI shown to users — password masked."""
        return self.get_database_url()

    def get_database_version(self) -> str:
        """Return the MongoDB server version."""
        return self.schema_operations.get_database_version(None)

    # --- statements (rejected) -------------------------------------------

    def execute_statement(
        self, sql: str, schema: Optional[str] = None, params: Optional[List[Any]] = None
    ) -> int:
        """Always raises — MongoDB has no string statements."""
        return self.query_executor.execute_statement(sql, params=params, schema=schema)

    def execute_query(self, sql: str, params: Optional[List[Any]] = None) -> List[Dict[str, Any]]:
        """Always raises — MongoDB has no string queries."""
        return self.query_executor.execute_query(sql, params)

    # --- transactions (absent) -------------------------------------------

    def supports_transactions(self) -> bool:
        """False: dblift cannot own a transaction around a script's own calls.

        MongoDB does have multi-document transactions on a replica set, but
        pymongo requires an explicit ``session=`` on every operation. dblift
        never sees the driver calls a Python migration makes, so it cannot
        enrol them. A script that wants a transaction opens its own session.
        """
        return False

    def supports_transactional_ddl(self) -> bool:
        """False — see :meth:`supports_transactions`."""
        return False

    def begin_transaction(self) -> None:
        """No-op: the framework calls this unconditionally."""
        return None

    def commit_transaction(self) -> None:
        """No-op — see :meth:`begin_transaction`."""
        return None

    def rollback_transaction(self) -> None:
        """No-op — see :meth:`begin_transaction`."""
        return None

    # --- document store contract -----------------------------------------

    def upsert_native_item(self, collection: str, document: Dict[str, Any]) -> Dict[str, Any]:
        """Write *document* into *collection*, replacing any same-``_id`` document."""
        return self.query_executor.upsert_document(collection, document)

    def delete_native_item(self, collection: str, item_id: str, partition_key: Any) -> None:
        """Delete *item_id* from *collection*.

        ``partition_key`` is accepted and ignored: MongoDB has no
        partitioning, and the uniform signature is what lets callers treat
        every document store the same.
        """
        self.query_executor.delete_document(collection, item_id)

    def list_native_items(self, collection: str) -> List[Dict[str, Any]]:
        """Return every document in *collection*."""
        return self.query_executor.list_documents(collection)

    # --- schema / clean ---------------------------------------------------

    def clean_schema(self, schema: str) -> CleanExecutionSummary:
        """Drop every collection, dblift's own storage included."""
        return self.schema_operations.clean_schema(None, schema)

    def get_clean_preview(self, schema: str) -> CleanExecutionSummary:
        """Report what :meth:`clean_schema` would drop."""
        return self.schema_operations.get_clean_preview(schema)

    def list_droppable_objects(self, schema: str) -> List[DroppableObject]:
        """Return collections in the order clean would drop them.

        ``drop_sql`` records the driver call clean will make; it is a
        human-readable audit line, not a statement anyone can execute.
        :meth:`drop_object` performs the deletion.
        """
        return [
            DroppableObject(
                name=collection_name,
                object_type="COLLECTION",
                drop_sql=f"database.drop_collection({collection_name!r})",
            )
            for collection_name in self.schema_operations.list_collections()
        ]

    def drop_object(self, obj: DroppableObject) -> None:
        """Drop the collection through pymongo.

        Collections are not droppable with SQL, so clean must not route
        ``drop_sql`` through ``execute_statement``.
        """
        if not self.schema_operations.drop_collection(obj.name):
            raise RuntimeError(f"Failed to drop collection {obj.name}")

    def table_exists(self, schema: str, table_name: str) -> bool:
        """Whether *table_name* exists as a collection."""
        return self.schema_operations.collection_exists(table_name)

    def create_snapshot_table_if_not_exists(
        self, schema: str, table_name: Optional[str] = None
    ) -> None:
        """Create the snapshot collection through the driver, never via DDL."""
        self.snapshot_manager.create_snapshot_table_if_not_exists(schema, table_name)

    # --- schema (no schema layer) ------------------------------------------

    def create_schema_if_not_exists(self, schema: str) -> None:
        """No-op: MongoDB has no schema layer, only a selected database."""
        self.schema_operations.create_schema_if_not_exists(None, schema)

    def set_current_schema(self, schema: str) -> None:
        """No-op — see :meth:`create_schema_if_not_exists`."""
        self.schema_operations.set_current_schema(None, schema)

    def get_schema_qualified_name(self, schema: str, object_name: str) -> str:
        """Return *object_name* unchanged — MongoDB has no schema layer."""
        return self.query_executor.get_schema_qualified_name(schema, object_name)

    # --- migration history ---------------------------------------------------

    def record_migration(
        self,
        schema: str,
        migration_info: Dict[str, Any],
        table_name: str = "dblift_schema_history",
    ) -> None:
        """Record a migration in the history collection."""
        self.history_manager.record_migration(None, schema, migration_info, table_name)

    def repair_migration_history(
        self,
        schema: str,
        script_name: str,
        checksum: Any,
        table_name: str = "dblift_schema_history",
        success_value: Optional[Any] = None,
    ) -> bool:
        """Update checksum (and optionally success) of an existing history document."""
        return self.history_manager.repair_migration_history(
            None, schema, script_name, checksum, success_value, table_name
        )

    def get_applied_migrations(
        self, schema: str, table_name: str = "dblift_schema_history"
    ) -> List[Dict[str, Any]]:
        """Return every applied migration, oldest first."""
        return self.history_manager.get_applied_migrations(None, schema, table_name)

    def create_migration_history_table_if_not_exists(
        self,
        schema: str,
        create_schema: bool = False,
        table_name: str = "dblift_schema_history",
    ) -> None:
        """Create the history collection when missing."""
        self.history_manager.create_migration_history_table_if_not_exists(
            None, schema, create_schema, table_name
        )

    def create_history_table(self, schema: str, table_name: str) -> str:
        """Describe how history storage is created — not executable DDL."""
        return self.history_manager.create_history_table(schema, table_name)

    # --- migration lock -------------------------------------------------------

    def create_migration_lock_table_if_not_exists(self, schema: str) -> None:
        """Create the lock collection when missing."""
        self.locking_manager.create_migration_lock_container_if_not_exists(schema)

    def acquire_migration_lock(self, schema: str, wait_timeout_seconds: int = 60) -> bool:
        """Take the migration lease, waiting up to *wait_timeout_seconds*."""
        return self.locking_manager.acquire_migration_lock(schema, wait_timeout_seconds)

    def release_migration_lock(self, schema: str) -> bool:
        """Release the migration lease."""
        return self.locking_manager.release_migration_lock(schema)
