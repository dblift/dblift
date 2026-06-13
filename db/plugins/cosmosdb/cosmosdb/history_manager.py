"""
Cosmos DB migration history management.

This module handles migration history tracking in Cosmos DB containers.
"""

import datetime
import os
import socket
import time
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from config import DbliftConfig
from core.logger import Log
from db.plugins.base_history_manager import BaseHistoryManager

from .query_executor import CosmosDbQueryExecutor
from .schema_operations import CosmosDbSchemaOperations

if TYPE_CHECKING:
    from azure.cosmos import ContainerProxy


class CosmosDbHistoryManager(BaseHistoryManager):
    """Manages migration history in Cosmos DB."""

    # CosmosDB uses container names as-is (case-sensitive)
    DEFAULT_HISTORY_TABLE = "dblift_schema_history"
    HISTORY_CONTAINER_NAME = "dblift_schema_history"
    HISTORY_CREATE_MAX_RETRIES = 5
    HISTORY_CREATE_BACKOFF_BASE = 2.0

    def __init__(
        self,
        query_executor: CosmosDbQueryExecutor,
        schema_operations: CosmosDbSchemaOperations,
        config: DbliftConfig,
        log: Optional[Log] = None,
    ):
        """Initialize history manager.

        Args:
            query_executor: Cosmos DB query executor
            schema_operations: Cosmos DB schema operations
            config: Application configuration
            log: Optional logger
        """
        super().__init__(query_executor, schema_operations, config, log)
        self.connection_manager = query_executor.connection_manager
        self.history_container: Optional["ContainerProxy"] = None

    @staticmethod
    def _is_transient_history_error(exc: Exception) -> bool:
        msg = str(exc).lower()
        return (
            "serviceunavailable" in msg
            or "service unavailable" in msg
            or "503" in msg
            or "timeout" in msg
            or "timed out" in msg
        )

    def create_history_container_if_not_exists(
        self, schema: str, table_name: str = "dblift_schema_history"
    ) -> None:
        """Create history container if it doesn't exist.

        Args:
            schema: Schema name (not used in Cosmos DB, but kept for compatibility)
            table_name: Container name (default: dblift_schema_history)
        """
        container_name = table_name or self.HISTORY_CONTAINER_NAME

        try:
            from azure.cosmos import PartitionKey

            database = self.connection_manager.database
            if not database:
                self.connection_manager.create_connection()
                database = self.connection_manager.database

            # Check if container already exists first
            try:
                if database is None:
                    raise RuntimeError("Database not initialized")
                existing_container = database.get_container_client(container_name)
                existing_container.read()
                self.history_container = existing_container
                self.log.debug(f"History container {container_name} already exists")
                return
            except Exception as read_error:
                # Check if it's a "not found" error
                error_str = str(read_error).lower()
                if "not found" in error_str or "notfound" in error_str or "404" in error_str:
                    # Container doesn't exist, create it
                    pass
                else:
                    # Some other error - might be timing issue, try to get client anyway
                    self.log.debug(
                        f"Error reading history container (might be timing): {str(read_error)}"
                    )
                    # Continue to try creating

            # Create container if it doesn't exist. The local emulator can return
            # transient 503/ServiceUnavailable during partition warmup, so mirror
            # the snapshot-container retry behavior here.
            create_error: Optional[Exception] = None
            for attempt in range(self.HISTORY_CREATE_MAX_RETRIES):
                try:
                    if database is None:
                        raise RuntimeError("Database not initialized")
                    history_container = database.create_container_if_not_exists(
                        id=container_name,
                        partition_key=PartitionKey(path="/version"),
                    )
                    self.history_container = history_container

                    # Small delay to ensure container is ready
                    time.sleep(0.3)

                    self.log.debug(f"Created history container: {container_name}")
                    return
                except Exception as exc:
                    create_error = exc
                    if (
                        attempt < self.HISTORY_CREATE_MAX_RETRIES - 1
                        and self._is_transient_history_error(exc)
                    ):
                        wait = self.HISTORY_CREATE_BACKOFF_BASE**attempt
                        self.log.warning(
                            f"History container creation transient failure "
                            f"(attempt {attempt + 1}/{self.HISTORY_CREATE_MAX_RETRIES}): "
                            f"{exc}. Retrying in {wait:.1f}s"
                        )
                        time.sleep(wait)
                        continue
                    break

            if create_error is not None:
                # create_container_if_not_exists may raise Conflict even if container exists
                # Check the error type and message
                error_str = str(create_error).lower()
                error_type = type(create_error).__name__

                # Check if it's a CosmosResourceExistsError (import might fail if SDK not available)
                is_resource_exists_error = False
                try:
                    from azure.cosmos.exceptions import CosmosResourceExistsError

                    is_resource_exists_error = isinstance(create_error, CosmosResourceExistsError)
                except ImportError:
                    # SDK not available, check by error type name
                    is_resource_exists_error = (
                        "CosmosResourceExistsError" in error_type or "ResourceExists" in error_type
                    )

                if (
                    is_resource_exists_error
                    or "already exists" in error_str
                    or "conflict" in error_str
                ):
                    # Container exists (this is expected), get client for it
                    if database is None:
                        raise RuntimeError("Database not initialized")
                    history_container = database.get_container_client(container_name)
                    self.history_container = history_container
                    self.log.debug(
                        f"History container {container_name} already exists (handled conflict)"
                    )
                else:
                    # Some other error occurred - check if container exists via listing
                    try:
                        containers_list: List[Dict[str, Any]]
                        if database is not None:
                            containers_list = list(database.list_containers())
                        else:
                            containers_list = []
                        for container in containers_list:
                            if container.get("id") == container_name:
                                if database is None:
                                    raise RuntimeError("Database not initialized")
                                self.history_container = database.get_container_client(
                                    container_name
                                )
                                self.log.debug(
                                    f"History container {container_name} found via list after creation error"
                                )
                                return
                    except Exception as e:
                        self.log.debug(
                            f"Could not verify history container via list after creation error: {e}"
                        )
                    # Re-raise if we couldn't find it
                    raise create_error

        except Exception as e:
            error_msg = f"Error creating history container: {str(e)}"
            self.log.error(error_msg)
            raise

    def get_applied_migrations(
        self, connection: Any, schema: str, table_name: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Get list of applied migrations from history container.

        Args:
            schema: Schema name (not used in Cosmos DB)
            table_name: Container name (default: dblift_schema_history)

        Returns:
            List of dictionaries containing migration information
        """
        container_name = table_name or self.HISTORY_CONTAINER_NAME

        if not self.history_container:
            self.history_container = self.connection_manager.get_container_client(container_name)

        try:
            # Query all migration documents, ordered by installed_rank
            query = "SELECT * FROM c ORDER BY c.installed_rank"
            if self.history_container is None:
                raise RuntimeError("History container not initialized")
            items = self.history_container.query_items(
                query=query, enable_cross_partition_query=True
            )

            results = []
            for item in items:
                # Convert Cosmos DB document to migration record format
                migration_record = {
                    "script": item.get("script"),
                    "installed_rank": item.get("installed_rank"),
                    "version": item.get("version"),
                    "description": item.get("description"),
                    "type": item.get("type"),
                    "checksum": item.get("checksum"),
                    "installed_by": item.get("installed_by"),
                    "installed_on": item.get("installed_on"),
                    "execution_time": item.get("execution_time", 0),
                    "success": item.get("success", True),
                }
                results.append(migration_record)

            return results

        except Exception as e:
            error_str = str(e).lower()
            if "not found" in error_str or "notfound" in error_str or "404" in error_str:
                self.log.debug(f"History container not found (first run or post-clean): {e}")
            else:
                self.log.error(f"Error getting applied migrations: {e}")
            return []

    def record_migration(
        self,
        connection: Any,
        schema: str,
        migration_info: Dict[str, Any],
        table_name: Optional[str] = None,
    ) -> None:
        """Record a migration in the history container.

        Args:
            schema: Schema name (not used in Cosmos DB)
            migration_info: Dictionary containing migration information
            table_name: Container name (default: dblift_schema_history)
        """
        container_name = table_name or self.HISTORY_CONTAINER_NAME

        # Ensure history container exists
        self.create_history_container_if_not_exists(schema, container_name)

        if not self.history_container:
            self.history_container = self.connection_manager.get_container_client(container_name)

        try:
            # Get next installed_rank
            query = "SELECT VALUE MAX(c.installed_rank) FROM c"
            if self.history_container is None:
                raise RuntimeError("History container not initialized")
            items = list(
                self.history_container.query_items(query=query, enable_cross_partition_query=True)
            )
            # SELECT VALUE returns just the values, so items[0] is the max rank (int), not a dict
            max_rank_raw = items[0] if items and items[0] is not None else None
            # Handle case where result might be a dict or direct value
            if max_rank_raw is None:
                max_rank = None
            elif isinstance(max_rank_raw, dict):
                # If it's a dict, extract the value (shouldn't happen with SELECT VALUE, but handle it)
                max_rank = max_rank_raw.get("installed_rank") or max_rank_raw.get("value")
            else:
                max_rank = max_rank_raw
            next_rank = (int(max_rank) + 1) if max_rank is not None else 1

            # Create migration document
            username = os.environ.get("USER", os.environ.get("USERNAME", "unknown"))
            hostname = socket.gethostname()
            installed_by = migration_info.get("installed_by") or f"{username}@{hostname}"

            installed_on = migration_info.get("installed_on")
            if installed_on is None:
                installed_on = datetime.datetime.now(datetime.timezone.utc).isoformat()
            elif isinstance(installed_on, datetime.datetime):
                installed_on = installed_on.isoformat()

            migration_doc = {
                "id": migration_info.get("script"),  # Use script as document ID
                "version": migration_info.get("version"),
                "installed_rank": next_rank,
                "description": migration_info.get("description"),
                "type": migration_info.get("type"),
                "script": migration_info.get("script"),
                "checksum": migration_info.get("checksum"),
                "installed_by": installed_by,
                "installed_on": installed_on,
                "execution_time": migration_info.get("execution_time", 0),
                "success": migration_info.get("success", True),
            }

            # Insert or update migration document (use upsert to handle existing documents)
            if self.history_container is None:
                raise RuntimeError("History container not initialized")
            # Use upsert_item instead of create_item to handle existing documents gracefully
            self.history_container.upsert_item(body=migration_doc)

            self.log.debug(f"Migration recorded: {migration_info.get('script')}")

        except Exception as e:
            error_msg = f"Error recording migration: {str(e)}"
            self.log.error(error_msg)
            raise

    def repair_migration_history(
        self,
        connection: Any,
        schema: str,
        script_name: str,
        checksum: Any,
        success_value: Optional[Any] = None,
        table_name: Optional[str] = None,
    ) -> bool:
        """Update the checksum (and optionally the success flag) of an existing history document.

        Args:
            connection: Active connection (unused for CosmosDB SDK path)
            schema: Schema name (not used in Cosmos DB)
            script_name: Script name — matches the document ``id``
            checksum: New checksum value to store
            table_name: Container name (default: dblift_schema_history)
            success_value: If provided, also update the success field

        Returns:
            True if the document was found and updated, False otherwise
        """
        container_name = table_name or self.HISTORY_CONTAINER_NAME

        if not self.history_container:
            self.history_container = self.connection_manager.get_container_client(container_name)

        try:
            if self.history_container is None:
                raise RuntimeError("History container not initialized")

            # Document id == script_name; partition key is also /id
            existing = self.history_container.read_item(item=script_name, partition_key=script_name)
            existing["checksum"] = checksum
            if success_value is not None:
                existing["success"] = success_value
            self.history_container.upsert_item(body=existing)
            self.log.debug(f"Repaired history document for: {script_name}")
            return True

        except Exception as e:
            error_str = str(e).lower()
            if "not found" in error_str or "notfound" in error_str or "404" in error_str:
                self.log.warning(f"No history document found for {script_name}: {e}")
                return False
            self.log.error(f"Error repairing history document for {script_name}: {e}")
            return False

    def create_history_table(self, schema: str, table_name: str) -> str:
        """Generate SQL to create the migration history container.

        Args:
            schema: Schema name (not used in Cosmos DB)
            table_name: Container name

        Returns:
            SQL string to create the history container
        """
        # Return CREATE CONTAINER statement for Cosmos DB
        return f"CREATE CONTAINER {table_name} (id STRING) WITH (partitionKey='/version')"

    def create_migration_history_table_if_not_exists(
        self,
        connection: Any,
        schema: str,
        create_schema: bool = False,
        table_name: str = "dblift_schema_history",
    ) -> None:
        """Create migration history container if it doesn't exist.

        Args:
            schema: Schema name (not used in Cosmos DB, but kept for compatibility)
            create_schema: Whether to create schema (not applicable to Cosmos DB)
            table_name: Container name (default: dblift_schema_history)
        """
        # Baseline-non-empty safety: refuse if container already has documents.
        # Mirrors the relational vendors' check (issue #405). Done before container
        # creation so a baseline against an existing non-empty container
        # fails fast without side effects.
        if create_schema:
            try:
                database = self.connection_manager.database
                if database is not None:
                    existing_container = database.get_container_client(table_name)
                    existing_container.read()
                    self._check_baseline_safety(connection, schema, table_name)
            except RuntimeError:
                raise
            except Exception:
                # Container does not yet exist (typical "not found"); nothing to
                # refuse. ``create_history_container_if_not_exists`` will create
                # it below.
                pass
        self.create_history_container_if_not_exists(schema, table_name)
