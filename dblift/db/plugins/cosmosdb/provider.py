"""
Cosmos DB provider implementation.

This provider uses modular components to handle Cosmos DB-specific database operations.
"""

from typing import Any, Dict, List, Optional

from dblift.config import DbliftConfig
from dblift.core.logger import Log
from dblift.core.migration.clean_summary import CleanExecutionSummary
from dblift.db.base_provider import NativeProvider
from dblift.db.plugins.cosmosdb.cosmosdb import (
    CosmosDbConnectionManager,
    CosmosDbHistoryManager,
    CosmosDbLockingManager,
    CosmosDbQueryExecutor,
    CosmosDbSchemaOperations,
    CosmosDbSnapshotManager,
)
from dblift.db.provider_interfaces import DroppableObject


class CosmosDbProvider(NativeProvider):
    """Cosmos DB provider implementation using Azure SDK with modular components."""

    canonical_dialect_key = "cosmosdb"

    def __init__(self, config: DbliftConfig, log: Optional[Log] = None):
        """Initialize Cosmos DB provider with modular components.

        Args:
            config: Application configuration
            log: Optional logger
        """
        super().__init__(config, log)

        # Initialize modular components
        self.connection_manager = CosmosDbConnectionManager(config, log)
        self.query_executor = CosmosDbQueryExecutor(self.connection_manager, log)
        self.locking_manager = CosmosDbLockingManager(self.query_executor, log)
        self.schema_operations = CosmosDbSchemaOperations(self.query_executor, log)
        self.history_manager = CosmosDbHistoryManager(
            self.query_executor, self.schema_operations, config, log
        )
        self.snapshot_manager = CosmosDbSnapshotManager(self, log=self.log)

    def create_connection(self) -> Any:
        """Create a connection to Cosmos DB using Azure SDK."""
        self.connection = self.connection_manager.create_connection()
        return self.connection

    def _get_connection_or_raise(self) -> Any:
        """Return self.connection or raise RuntimeError if None/missing.

        Raises:
            RuntimeError: If create_connection() has not been called.
        """
        connection = getattr(self, "connection", None)
        if connection is None:
            raise RuntimeError(
                "CosmosDB provider has no active connection. "
                "Ensure create_connection() was called before executing queries."
            )
        return connection

    def execute_statement(
        self, sql: str, schema: Optional[str] = None, params: Optional[List[Any]] = None
    ) -> int:
        """Execute a SQL statement and return affected rows."""
        connection = self._get_connection_or_raise()
        return self.query_executor.execute_statement(connection, sql, params)

    def execute_query(self, sql: str, params: Optional[List[Any]] = None) -> List[Dict[str, Any]]:
        """Execute a SELECT query and return results."""
        connection = self._get_connection_or_raise()
        return self.query_executor.execute_query(connection, sql, params)

    def upsert_native_item(self, container_name: str, document: Dict[str, Any]) -> Dict[str, Any]:
        """Upsert a document straight through the Azure SDK, bypassing SQL.

        Thin forward to :meth:`CosmosDbQueryExecutor.upsert_native_item` —
        the same shape as :meth:`execute_statement` and :meth:`execute_query`
        above, which forward to the query executor's SQL-shaped methods. This
        one exists for callers (e.g. the schema-snapshot repository) that
        need to write a single document and hold a provider reference rather
        than a query-executor one; see
        :meth:`CosmosDbQueryExecutor.upsert_native_item` for why a native
        write path exists instead of routing an ``INSERT`` through
        ``execute_statement``.

        No connection guard here (unlike ``execute_statement`` /
        ``execute_query``): the query executor reaches the container through
        ``connection_manager.get_container_client`` rather than the
        ``connection`` object, the same reason
        ``create_snapshot_table_if_not_exists`` below calls into
        ``schema_operations`` directly without fetching one.
        """
        return self.query_executor.upsert_native_item(container_name, document)

    def delete_native_item(self, container_name: str, item_id: str, partition_key: Any) -> None:
        """Delete a document straight through the Azure SDK, bypassing SQL.

        Thin forward to :meth:`CosmosDbQueryExecutor.delete_native_item` --
        same shape as :meth:`upsert_native_item` above.
        """
        self.query_executor.delete_native_item(container_name, item_id, partition_key=partition_key)

    def list_native_items(self, container_name: str) -> List[Dict[str, Any]]:
        """List documents straight through the Azure SDK, bypassing SQL.

        Thin forward to :meth:`CosmosDbQueryExecutor.list_native_items` --
        same shape as :meth:`upsert_native_item` / :meth:`delete_native_item`
        above.
        """
        return self.query_executor.list_native_items(container_name)

    def create_schema_if_not_exists(self, schema: str) -> None:
        """Create schema if it doesn't exist (Cosmos DB doesn't have schemas)."""
        connection = self._get_connection_or_raise()
        self.schema_operations.create_schema_if_not_exists(connection, schema)

    def schema_exists(self, schema: str) -> bool:
        """Check if a schema exists.

        Note: CosmosDB is schema-less. Always returns True.

        Args:
            schema: Schema name (ignored)

        Returns:
            bool: Always True
        """
        self.log.debug("CosmosDB is schema-less, schema_exists always returns True")
        return True

    def table_exists(self, schema: str, table_name: str) -> bool:
        """Check if a container exists in Cosmos DB."""
        return self.schema_operations.container_exists(table_name)

    def get_database_url(self) -> str:
        """Return the Cosmos DB connection URL for display purposes."""
        url = self.connection_manager.get_database_url()
        return url if url is not None else ""

    def get_display_url(self) -> str:
        """Return the Cosmos DB endpoint/URL without requiring transport-specific semantics."""
        url = self.connection_manager.get_database_url()
        return url if url is not None else super().get_display_url()

    def get_database_version(self) -> str:
        """Get Cosmos DB database version information."""
        connection = self._get_connection_or_raise()
        return self.schema_operations.get_database_version(connection)

    def supports_transactions(self) -> bool:
        """CosmosDB ne supporte pas les transactions ACID traditionnelles.

        Cosmos DB utilise la concurrence optimiste par opération.
        Les callers doivent vérifier supports_transactions() avant d'appeler
        begin_transaction(), commit_transaction(), rollback_transaction().
        """
        return False

    def supports_transactional_ddl(self) -> bool:
        """CosmosDB is NoSQL; it has no DDL and therefore no transactional DDL.

        Overrides the ``TransactionalProvider`` default of ``True``.
        Kept aligned with ``DialectCapabilities`` for "cosmosdb" in
        ``core/sql_model/dialect.py`` — the conformance test in
        ``tests/unit/core/sql_model/test_dialect_capabilities.py`` asserts
        this pair stays in lockstep.
        """
        return False

    def begin_transaction(self) -> None:
        """Begin a database transaction (no-op: supports_transactions() returns False).

        Cosmos DB uses optimistic concurrency per-operation.
        """
        self.log.debug("Cosmos DB uses optimistic concurrency - transaction started")

    def commit_transaction(self) -> None:
        """Commit the current transaction (no-op: supports_transactions() returns False).

        Cosmos DB uses optimistic concurrency per-operation.
        """
        self.log.debug("Cosmos DB transaction committed")

    def rollback_transaction(self) -> None:
        """Rollback the current transaction (no-op: supports_transactions() returns False).

        Cosmos DB doesn't support traditional rollback — operations are committed immediately.
        """
        self.log.warning(
            "Cosmos DB doesn't support traditional rollback - operations are committed immediately"
        )

    def set_current_schema(self, schema: str) -> None:
        """Set the current schema (not applicable to Cosmos DB)."""
        connection = self._get_connection_or_raise()
        self.schema_operations.set_current_schema(connection, schema)

    def create_migration_lock_table_if_not_exists(self, schema: str) -> None:
        """Create the migration lock container if it doesn't exist."""
        self.locking_manager.create_migration_lock_container_if_not_exists(schema)

    def acquire_migration_lock(self, schema: str, wait_timeout_seconds: int = 60) -> bool:
        """Acquire an exclusive migration lock for the specified schema."""
        return self.locking_manager.acquire_migration_lock(schema, wait_timeout_seconds)

    def release_migration_lock(self, schema: str) -> bool:
        """Release the migration lock for the specified schema."""
        return self.locking_manager.release_migration_lock(schema)

    def clean_schema(self, schema: str) -> CleanExecutionSummary:
        """
        Clean all containers from the specified Cosmos DB database.

        This drops every container in the database, including dblift-managed
        internal containers. The next migrate operation recreates the history
        and lock containers as needed.

        Args:
            schema: Schema name (not used in Cosmos DB, but kept for compatibility)

        Returns:
            CleanExecutionSummary with dropped containers and any errors
        """
        self.log.info("Cleaning Cosmos DB database - removing all containers")

        summary = CleanExecutionSummary()

        try:
            # List all containers
            container_names = self.schema_operations.list_containers()

            self.log.debug(f"Found {len(container_names)} containers to check")

            # Delete every container, including dblift-managed internal containers.
            for container_name in container_names:
                try:
                    deleted = self.schema_operations.delete_container(container_name)
                    if deleted:
                        drop_sql = f"database.delete_container({container_name!r})"
                        summary.record_drop(
                            sql=drop_sql,
                            object_type="CONTAINER",
                            name=container_name,
                            schema=None,
                        )
                        self.log.info(f"Dropped container: {container_name}")
                    else:
                        self.log.warning(f"Failed to drop container: {container_name}")
                except Exception as e:
                    error_msg = f"Error dropping container {container_name}: {str(e)}"
                    self.log.error(error_msg)
                    # Note: CleanExecutionSummary doesn't have an errors field,
                    # but we can log the error

            self.log.info(f"Clean schema completed: {len(summary.objects)} container(s) dropped")

        except Exception as e:
            error_msg = f"Error during schema cleaning: {str(e)}"
            self.log.error(error_msg)

        return summary

    def list_droppable_objects(self, schema: str) -> List[DroppableObject]:
        """Return CosmosDB containers in the order clean would drop them.

        ``drop_sql`` records the SDK call clean will make; it is a
        human-readable audit line, not a statement anyone can execute.
        :meth:`drop_object` performs the deletion.
        """
        return [
            DroppableObject(
                name=container_name,
                object_type="CONTAINER",
                drop_sql=f"database.delete_container({container_name!r})",
            )
            for container_name in self.schema_operations.list_containers()
        ]

    def drop_object(self, obj: DroppableObject) -> None:
        """Delete the container through the Azure SDK.

        Cosmos containers are not droppable with SQL, so clean must not
        route ``drop_sql`` through ``execute_statement``.
        """
        if not self.schema_operations.delete_container(obj.name):
            raise RuntimeError(f"Failed to delete container {obj.name}")

    def get_clean_preview(self, schema: str) -> CleanExecutionSummary:
        """Return what a Cosmos DB clean would remove without deleting data."""
        return self.schema_operations.get_clean_preview(schema)

    def get_applied_migrations(
        self, schema: str, table_name: str = "dblift_schema_history"
    ) -> List[Dict[str, Any]]:
        """Get list of applied migrations from history container."""
        connection = self._get_connection_or_raise()
        return self.history_manager.get_applied_migrations(connection, schema, table_name)

    def get_schema_qualified_name(self, schema: str, object_name: str) -> str:
        """Get a properly formatted schema-qualified object name for Cosmos DB."""
        # Cosmos DB doesn't use schema qualification
        return object_name

    def get_columns_query(self, schema: str, table: str) -> str:
        """Get a Cosmos DB-specific query to retrieve column information."""
        # Cosmos DB doesn't have fixed columns, but we can query document structure
        return f"SELECT TOP 1 * FROM {table}"

    def get_add_column_sql(self, schema: str, table: str, column: str, type_def: str) -> str:
        """Generate Cosmos DB-specific SQL (not applicable - schema-less)."""
        # Cosmos DB is schema-less, so adding columns doesn't apply
        return "-- Cosmos DB is schema-less, no ALTER TABLE needed"

    def get_parameter_placeholders(self, count: int) -> str:
        """Get positional placeholders for dblift SQL execution paths.

        The Cosmos query executor inlines ``?`` parameters before translating
        generic SQL into SDK calls. Keeping the provider contract positional
        lets shared callers use the same INSERT and DELETE paths.
        """
        return ", ".join(["?" for _ in range(count)])

    def record_migration(
        self, schema: str, migration_info: Dict[str, Any], table_name: str = "dblift_schema_history"
    ) -> None:
        """Record a migration in the history container."""
        connection = self._get_connection_or_raise()
        self.history_manager.record_migration(connection, schema, migration_info, table_name)

    def repair_migration_history(
        self,
        schema: str,
        script_name: str,
        checksum: Any,
        table_name: str = "dblift_schema_history",
        success_value: Optional[Any] = None,
    ) -> bool:
        """Update checksum (and optionally success) of an existing history document."""
        connection = self._get_connection_or_raise()
        return self.history_manager.repair_migration_history(
            connection, schema, script_name, checksum, success_value, table_name
        )

    def create_history_table(self, schema: str, table_name: str) -> str:
        """Generate the SQL to create a migration history container."""
        return self.history_manager.create_history_table(schema, table_name)

    def create_migration_history_table_if_not_exists(
        self, schema: str, create_schema: bool = False, table_name: str = "dblift_schema_history"
    ) -> None:
        """Create migration history container if it doesn't exist."""
        self.history_manager.create_history_container_if_not_exists(schema, table_name)

    def create_snapshot_table_if_not_exists(
        self,
        schema: str,
        table_name: Optional[str] = None,
    ) -> None:
        """Create the snapshot container through the SDK.

        Provisioning lives on ``CosmosDbSnapshotManager`` so every document
        store implements the same contract instead of re-deriving it from
        this provider. See ``db/plugins/nosql_base/snapshot.py``.
        """
        # Guards providers built via __new__ (bypassing __init__, as some
        # tests do) rather than the normal constructor, where this would
        # already be set.
        if getattr(self, "snapshot_manager", None) is None:
            self.snapshot_manager = CosmosDbSnapshotManager(self, log=self.log)
        self.snapshot_manager.create_snapshot_table_if_not_exists(schema, table_name)

    def close(self) -> None:
        """Close the Cosmos DB connection."""
        if self.connection_manager:
            self.connection_manager.close()
        super().close()

    def is_connected(self) -> bool:
        """Check if the provider is connected to Cosmos DB."""
        return self.connection_manager.database is not None
