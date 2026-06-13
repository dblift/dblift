"""
Cosmos DB provider implementation.

This provider uses modular components to handle Cosmos DB-specific database operations.
"""

import time
from typing import Any, Dict, List, Optional

from config import DbliftConfig
from core.logger import Log
from core.migration.clean_summary import CleanExecutionSummary
from db.base_provider import NativeProvider
from db.plugins.cosmosdb.cosmosdb import (
    CosmosDbConnectionManager,
    CosmosDbHistoryManager,
    CosmosDbLockingManager,
    CosmosDbQueryExecutor,
    CosmosDbSchemaOperations,
)


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
        internal containers. The next migrate/snapshot operation recreates the
        history, lock, and snapshot containers as needed.

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
                        drop_sql = f"DROP CONTAINER {container_name}"
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
        lets shared callers such as the snapshot repository use the same INSERT
        and DELETE paths.
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

    def close(self) -> None:
        """Close the Cosmos DB connection."""
        if self.connection_manager:
            self.connection_manager.close()
        super().close()

    def is_connected(self) -> bool:
        """Check if the provider is connected to Cosmos DB."""
        return self.connection_manager.database is not None

    # BUG-04: emulator first-boot can return ServiceUnavailable / 503 for
    # several seconds while partitions warm up. Retry the container-create
    # with exponential backoff so the migration body's snapshot capture is
    # not surfaced as an error wall.
    _SNAPSHOT_CREATE_MAX_RETRIES = 5
    _SNAPSHOT_CREATE_BACKOFF_BASE = 2.0

    @staticmethod
    def _is_transient_snapshot_error(exc: Exception) -> bool:
        msg = str(exc).lower()
        return (
            "serviceunavailable" in msg
            or "service unavailable" in msg
            or "503" in msg
            or "timeout" in msg
            or "timed out" in msg
        )

    def create_snapshot_table_if_not_exists(
        self,
        schema: str,
        table_name: Optional[str] = None,
    ) -> None:
        """Create the schema snapshot storage container if it does not exist.

        Args:
            schema: Schema name (not used in Cosmos DB, but kept for compatibility)
            table_name: Container name for snapshots. Defaults to the
                canonical ``DBLIFT_SCHEMA_SNAPSHOTS_TABLE`` constant so the
                name is not hardcoded here.
        """
        from core.constants import DBLIFT_SCHEMA_SNAPSHOTS_TABLE

        # Cosmos DB container names are case-sensitive; resolve via the
        # dialect-aware helper so dblift objects use the case the rest of
        # the codebase expects.
        from db.object_naming import get_normalized_object_name

        raw_name = table_name or DBLIFT_SCHEMA_SNAPSHOTS_TABLE
        container_name = get_normalized_object_name(raw_name, "cosmosdb")

        # Check if container already exists
        if self.schema_operations.container_exists(container_name):
            self.log.debug(f"Snapshot container {container_name} already exists")
            return

        # Create container with partition key on 'id' field
        create_sql = f"CREATE CONTAINER {container_name} (id STRING) WITH (partitionKey='/id')"

        last_exc: Optional[Exception] = None
        for attempt in range(self._SNAPSHOT_CREATE_MAX_RETRIES):
            try:
                self.execute_statement(create_sql)
                self.log.debug(f"Created snapshot container: {container_name}")
                return
            except Exception as e:
                last_exc = e
                # Container might have been created concurrently.
                if self.schema_operations.container_exists(container_name):
                    self.log.debug(
                        f"Snapshot container {container_name} exists (created concurrently)"
                    )
                    return

                transient = self._is_transient_snapshot_error(e)
                if attempt < self._SNAPSHOT_CREATE_MAX_RETRIES - 1 and transient:
                    wait = self._SNAPSHOT_CREATE_BACKOFF_BASE**attempt
                    self.log.warning(
                        f"Snapshot container creation transient failure "
                        f"(attempt {attempt + 1}/{self._SNAPSHOT_CREATE_MAX_RETRIES}): "
                        f"{e}. Retrying in {wait:.1f}s…"
                    )
                    time.sleep(wait)
                    continue
                break

        error_msg = f"Failed to create snapshot container {container_name}: {str(last_exc)}"
        self.log.error(error_msg)
        raise RuntimeError(error_msg) from last_exc
