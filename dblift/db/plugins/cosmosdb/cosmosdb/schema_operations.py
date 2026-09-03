"""
Cosmos DB schema operations.

This module handles Cosmos DB container and database operations.
"""

import time
from typing import Any, List, Optional

from dblift.core.logger import Log, NullLog
from dblift.core.migration.clean_summary import CleanExecutionSummary
from dblift.db.plugins.base_schema_operations import BaseSchemaOperations

from .query_executor import CosmosDbQueryExecutor


class CosmosDbSchemaOperations(BaseSchemaOperations):
    """Manages Cosmos DB containers and schema operations."""

    def __init__(self, query_executor: CosmosDbQueryExecutor, log: Optional[Log] = None):
        """Initialize schema operations.

        Args:
            query_executor: Cosmos DB query executor
            log: Optional logger
        """
        self.query_executor = query_executor
        self.connection_manager = query_executor.connection_manager
        self.log = log if log is not None else NullLog()

    def create_schema_if_not_exists(self, connection: Any, schema: str) -> None:
        """Create database if it doesn't exist (Cosmos DB doesn't have schemas).

        Args:
            schema: Schema name (treated as database name in Cosmos DB)
        """
        # Cosmos DB doesn't have schemas, but we ensure the database exists
        # The database is already created/accessed in connection_manager
        self.log.debug(f"Schema concept not applicable to Cosmos DB, using database: {schema}")

    def set_current_schema(self, connection: Any, schema: str) -> None:
        """Set current schema (not applicable to Cosmos DB).

        Args:
            schema: Schema name
        """
        # Cosmos DB doesn't have schemas
        self.log.debug("Schema setting not applicable to Cosmos DB")

    def container_exists(self, container_name: str) -> bool:
        """Check if a container exists.

        Args:
            container_name: Container name

        Returns:
            True if container exists, False otherwise
        """
        database = self.connection_manager.database
        if database is None:
            self.connection_manager.create_connection()
            database = self.connection_manager.database

        if database is None:
            # Cannot reach Cosmos DB. Returning False keeps the bool
            # contract callers depend on (provider.py wraps this in a
            # plain ``if`` check), but log loudly so transient infra
            # failures surface in operator output rather than being
            # silently treated as "container does not exist". Earlier
            # attempt to ``raise RuntimeError`` here broke
            # ``provider.create_container_if_not_exists`` and the
            # ``if container_exists(...):`` predicates in
            # ``provider.py:324/335``. (PR #241 Bugbot.)
            self.log.error(
                f"Cannot check existence of container {container_name!r}: "
                "Cosmos DB connection is unavailable."
            )
            return False

        # Try reading first (fastest method)
        try:
            container_client = database.get_container_client(container_name)
            container_client.read()
            # If read succeeds, container exists
            return True
        except Exception as read_error:
            error_str = str(read_error).lower()
            if "not found" in error_str or "notfound" in error_str or "404" in error_str:
                # Container might not exist, but try listing as double-check
                # Sometimes emulator has timing issues where read fails but container exists
                try:
                    time.sleep(0.5)  # Wait a bit longer for propagation
                    if database is not None:
                        containers = list(database.list_containers())
                    else:
                        containers = []
                    for container in containers:
                        # Case-sensitive comparison (Cosmos DB is case-sensitive)
                        container_id = container.get("id")
                        if container_id == container_name:
                            self.log.debug(
                                f"Container {container_name} found via list (read failed)"
                            )
                            return True
                    return False
                except Exception as list_error:
                    self.log.debug(f"Error listing containers: {str(list_error)}")
                    return False

            # For timeout or other errors, try listing containers as fallback
            # This is more reliable for emulator which might have timing issues
            try:
                # Small delay before listing (container might be propagating)
                time.sleep(0.5)
                containers = list(database.list_containers())
                for container in containers:
                    # Case-sensitive comparison (Cosmos DB container names are case-sensitive)
                    container_id = container.get("id")
                    if container_id == container_name:
                        self.log.debug(
                            f"Container {container_name} found via list (read error: {str(read_error)})"
                        )
                        return True
                return False
            except Exception as list_error:
                # If listing also fails, log and return False
                self.log.debug(
                    f"Error checking container existence (read: {str(read_error)}, list: {str(list_error)})"
                )
                return False

    def table_exists(self, connection: Any, schema: str, table_name: str) -> bool:
        """Check if a container (table) exists. Delegates to container_exists."""
        return self.container_exists(table_name)

    def get_database_version(self, connection: Any) -> str:
        """Get Cosmos DB account information.

        Returns:
            Database version string with account name and consistency level
        """
        try:
            database = self.connection_manager.database
            if not database:
                self.connection_manager.create_connection()
                database = self.connection_manager.database

            # Get account information
            if self.connection_manager.client is None:
                raise RuntimeError("Client not initialized")
            account_info = self.connection_manager.client.get_database_account()

            # Extract account name from endpoint URL
            import urllib.parse

            endpoint = (
                getattr(self.connection_manager.config.database, "account_endpoint", None)
                or self.connection_manager.config.database.url
            )
            account_name = "Unknown"
            if endpoint:
                try:
                    parsed = urllib.parse.urlparse(endpoint)
                    hostname = parsed.hostname or ""
                    if "documents.azure.com" in hostname:
                        # Extract account name from Azure endpoint: account.documents.azure.com
                        account_name = hostname.split(".")[0]
                    elif "localhost" in hostname or "127.0.0.1" in hostname:
                        account_name = "Cosmos DB Emulator"
                    else:
                        # Use hostname as account name for other endpoints
                        account_name = hostname.split(":")[0]  # Remove port if present
                except Exception as e:
                    self.log.debug(f"Could not extract Cosmos DB account name from endpoint: {e}")

            # Try to get consistency level from ConsistencyPolicy
            consistency_level = None
            try:
                consistency_policy = getattr(account_info, "ConsistencyPolicy", None)
                if consistency_policy:
                    # ConsistencyPolicy can be a dict or an object
                    if isinstance(consistency_policy, dict):
                        consistency_level = consistency_policy.get(
                            "defaultConsistencyLevel"
                        ) or consistency_policy.get("default_consistency_level")
                    else:
                        # Try as object attributes
                        consistency_level = getattr(
                            consistency_policy, "default_consistency_level", None
                        )
                        if not consistency_level:
                            consistency_level = getattr(
                                consistency_policy, "defaultConsistencyLevel", None
                            )
            except Exception as e:
                self.log.debug(f"Could not get Cosmos DB consistency level: {e}")

            # Build version string
            version_parts = [f"Cosmos DB Account: {account_name}"]
            if consistency_level:
                version_parts.append(f"Consistency: {consistency_level}")

            return ", ".join(version_parts)

        except Exception as e:
            self.log.warning(f"Could not get Cosmos DB version: {str(e)}")
            return "Cosmos DB (version unknown)"

    def create_container_if_not_exists(
        self, container_name: str, partition_key: str = "/id"
    ) -> None:
        """Create container if it doesn't exist.

        Args:
            container_name: Container name
            partition_key: Partition key path (default: '/id')
        """
        if self.container_exists(container_name):
            self.log.debug(f"Container {container_name} already exists")
            return

        try:
            from azure.cosmos import PartitionKey

            database = self.connection_manager.database
            if not database:
                self.connection_manager.create_connection()
                database = self.connection_manager.database

            if database is None:
                raise RuntimeError("Database not initialized")
            database.create_container(
                id=container_name,
                partition_key=PartitionKey(path=partition_key),
            )

            self.log.debug(f"Created Cosmos DB container: {container_name}")

        except Exception as e:
            error_msg = f"Error creating container {container_name}: {str(e)}"
            self.log.error(error_msg)
            raise

    def list_containers(self) -> List[str]:
        """
        List all container names in the database.

        Returns:
            List of container names
        """
        database = self.connection_manager.database
        if not database:
            self.connection_manager.create_connection()
            database = self.connection_manager.database

        if database is None:
            raise RuntimeError("Database not initialized")

        try:
            containers = list(database.list_containers())
            container_names = [
                container.get("id", "") for container in containers if container.get("id")
            ]
            return container_names
        except Exception as e:
            error_msg = f"Error listing containers: {str(e)}"
            self.log.error(error_msg)
            raise RuntimeError(error_msg) from e

    def delete_container(self, container_name: str) -> bool:
        """
        Delete a container.

        Args:
            container_name: Container name to delete

        Returns:
            True if deleted successfully, False otherwise
        """
        database = self.connection_manager.database
        if not database:
            self.connection_manager.create_connection()
            database = self.connection_manager.database

        if database is None:
            raise RuntimeError("Database not initialized")

        try:
            # Use database.delete_container() instead of container_client.delete_container()
            database.delete_container(container=container_name)
            self.log.debug(f"Deleted container: {container_name}")
            return True
        except Exception as e:
            error_str = str(e).lower()
            if "not found" in error_str or "notfound" in error_str or "404" in error_str:
                self.log.debug(f"Container {container_name} does not exist (already deleted)")
                return False
            error_msg = f"Error deleting container {container_name}: {str(e)}"
            self.log.error(error_msg)
            raise RuntimeError(error_msg) from e

    def clean_schema(self, connection: Any, schema: str) -> CleanExecutionSummary:
        """Clean all containers from the Cosmos DB database.

        Args:
            schema: Schema name (not used in Cosmos DB)

        Returns:
            CleanExecutionSummary with dropped containers and any errors
        """
        summary = CleanExecutionSummary()

        try:
            container_names = self.list_containers()
            self.log.debug(f"Found {len(container_names)} containers to check for cleaning")

            # Delete every container, including dblift-managed internal containers.
            for container_name in container_names:
                try:
                    if self.delete_container(container_name):
                        drop_sql = f"database.delete_container({container_name!r})"
                        summary.record_drop(
                            sql=drop_sql,
                            object_type="CONTAINER",
                            name=container_name,
                            schema=None,
                        )
                        self.log.debug(f"Deleted container: {container_name}")
                        # Small delay to ensure deletion is propagated
                        time.sleep(0.2)
                    else:
                        self.log.warning(f"Failed to delete container: {container_name}")
                except Exception as delete_error:
                    self.log.error(
                        f"Error deleting container {container_name}: {str(delete_error)}"
                    )
                    # Continue with other containers
            # Additional wait after all deletions to ensure they're propagated
            if container_names:
                time.sleep(0.5)
        except Exception as e:
            self.log.error(f"Error during schema cleaning: {str(e)}")

        return summary

    def get_clean_preview(self, schema: str) -> CleanExecutionSummary:
        """Return the containers a CosmosDB clean would remove without deleting them."""
        summary = CleanExecutionSummary()

        container_names = self.list_containers()

        for container_name in container_names:
            summary.record_drop(
                sql=f"database.delete_container({container_name!r})",
                object_type="CONTAINER",
                name=container_name,
                schema=None,
            )

        return summary

    def get_schemas(self, connection: Any) -> List[str]:
        """Get list of schemas (not applicable to Cosmos DB).

        Returns:
            Empty list (Cosmos DB doesn't have schemas)
        """
        return []

    def get_tables(self, connection: Any, schema: str) -> List[str]:
        """Get list of containers (tables) in the database.

        Args:
            schema: Schema name (not used in Cosmos DB)

        Returns:
            List of container names
        """
        return self.list_containers()

    def get_columns_query(self, schema: str, table: str) -> str:
        """Get a Cosmos DB-specific query to retrieve column information.

        Args:
            schema: Schema name (not used)
            table: Container name

        Returns:
            Query to sample documents from the container
        """
        return f"SELECT TOP 1 * FROM {table}"

    def get_add_column_sql(self, schema: str, table: str, column: str, type_def: str) -> str:
        """Generate Cosmos DB-specific SQL for adding a column.

        Args:
            schema: Schema name (not used)
            table: Container name
            column: Column name
            type_def: Column type definition

        Returns:
            SQL comment (Cosmos DB is schema-less)
        """
        return f"-- Cosmos DB is schema-less, no ALTER TABLE needed for {table}.{column}"

    def get_parameter_placeholders(self, count: int) -> str:
        """Get positional placeholders for dblift SQL execution paths.

        Args:
            count: Number of placeholders needed

        Returns:
            Comma-separated parameter placeholders
        """
        return ", ".join(["?" for _ in range(count)])
