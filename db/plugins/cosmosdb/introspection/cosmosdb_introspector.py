"""
Cosmos DB schema introspection using Azure SDK.

This module provides Cosmos DB-specific metadata extraction by leveraging
the Azure Cosmos DB SDK to list containers and infer schema from documents.
"""

import logging
import re
from typing import Any, Dict, List, Optional, Set

from core.introspection.base_introspector import BaseIntrospector
from core.logger import NullLog
from core.sql_model.base import ConstraintType, SqlColumn, SqlConstraint
from core.sql_model.index import Index
from core.sql_model.table import Table

logger = logging.getLogger(__name__)


class CosmosDbIntrospector(BaseIntrospector):
    """
    Introspect Cosmos DB containers and infer schema from documents.

    This class provides Cosmos DB-specific metadata extraction by:
    1. Listing all containers in the database
    2. Sampling documents from each container to infer schema
    3. Extracting partition keys and indexing policies
    4. Building SQL Model objects compatible with DBLift's schema model

    Example:
        >>> introspector = CosmosDbIntrospector(provider)
        >>> tables = introspector.get_tables("default")
        >>> for table in tables:
        ...     print(f"Container: {table.name}, Columns: {len(table.columns)}")
    """

    # System containers that should be excluded from introspection
    SYSTEM_CONTAINERS = {
        "dblift_schema_history",
        "dblift_migration_lock",
    }

    def __init__(self, provider: Any, log: Any = None, use_vendor_queries: bool = True) -> None:
        """
        Initialize the Cosmos DB introspector.

        Args:
            provider: Cosmos DB provider (must be CosmosDbProvider)
            log: Optional logger instance
            use_vendor_queries: Whether to use vendor-specific queries (not used for Cosmos DB, but kept for compatibility)
        """
        self.provider = provider
        self.log = log if log is not None else NullLog()
        self.dialect = "cosmosdb"
        # Cosmos DB doesn't use vendor-specific queries, but we accept the parameter for compatibility

        # Validate provider type
        if not hasattr(provider, "connection_manager") or not hasattr(
            provider.connection_manager, "database"
        ):
            raise ValueError("Provider must be a CosmosDbProvider with connection_manager.database")

    def _ensure_connection(self) -> None:
        """Ensure database connection is established."""
        if not self.provider.connection_manager.database:
            self.provider.create_connection()

    def get_tables(
        self, schema: str, include_views: bool = False, table_pattern: str = "%"
    ) -> List[Table]:
        """
        Get all containers (tables) in the Cosmos DB database.

        Args:
            schema: Schema name (not used in Cosmos DB, but kept for compatibility)
            include_views: Whether to include views (not applicable to Cosmos DB)
            table_pattern: Container name pattern (% = wildcard)

        Returns:
            List of Table objects representing Cosmos DB containers
        """
        self._ensure_connection()
        database = self.provider.connection_manager.database

        self.log.debug(f"Getting containers from Cosmos DB: pattern={table_pattern}")

        tables = []

        try:
            # List all containers
            containers = list(database.list_containers())

            # Filter by pattern
            if table_pattern != "%":
                # Simple pattern matching (supports % wildcard)
                pattern = table_pattern.replace("%", ".*").replace("_", ".")
                pattern_re = re.compile(f"^{pattern}$", re.IGNORECASE)
                containers = [c for c in containers if pattern_re.match(c.get("id", ""))]

            for container_props in containers:
                container_id = container_props.get("id", "")
                if not container_id:
                    continue

                # Skip system containers
                if container_id in self.SYSTEM_CONTAINERS:
                    self.log.debug(f"Skipping system container: {container_id}")
                    continue

                # Build Table object from container
                table = self._build_table_from_container(container_id, container_props)
                if table:
                    tables.append(table)

            self.log.debug(f"Found {len(tables)} containers")

        except Exception as e:
            error_msg = f"Error listing Cosmos DB containers: {str(e)}"
            self.log.error(error_msg)
            raise RuntimeError(error_msg) from e

        return tables

    def _build_table_from_container(
        self, container_name: str, container_props: Dict[str, Any]
    ) -> Optional[Table]:
        """
        Build a Table object from a Cosmos DB container.

        Args:
            container_name: Container name
            container_props: Container properties from Azure SDK

        Returns:
            Table object with inferred columns and constraints
        """
        try:
            # Get partition key from container properties
            partition_key_def = container_props.get("partitionKey", {})
            partition_key_path = (
                partition_key_def.get("paths", ["/id"])[0] if partition_key_def else "/id"
            )
            partition_key_field = partition_key_path.lstrip("/")

            # Sample documents to infer schema
            columns = self._infer_columns_from_container(container_name, partition_key_field)

            # Build constraints
            constraints = []

            # Add primary key constraint (id field is always primary key in Cosmos DB)
            if any(col.name == "id" for col in columns):
                constraints.append(
                    SqlConstraint(
                        constraint_type=ConstraintType.PRIMARY_KEY,
                        name=f"PK_{container_name}",
                        column_names=["id"],
                        dialect="cosmosdb",
                    )
                )

            # Create Table object
            table = Table(
                name=container_name,
                columns=columns,
                schema=None,  # Cosmos DB doesn't have schemas
                constraints=constraints,
                dialect="cosmosdb",
                comment=f"Cosmos DB container with partition key: {partition_key_path}",
            )
            table.metadata = {"partition_key": partition_key_path}

            return table

        except Exception as e:
            self.log.warning(f"Error building table from container {container_name}: {str(e)}")
            return None

    def _infer_columns_from_container(
        self, container_name: str, partition_key_field: str
    ) -> List[SqlColumn]:
        """
        Infer column structure by sampling documents from a container.

        Args:
            container_name: Container name
            partition_key_field: Partition key field name

        Returns:
            List of SqlColumn objects representing inferred schema
        """
        columns = []
        seen_fields: Set[str] = set()

        try:
            container_client = self.provider.connection_manager.get_container_client(container_name)

            # Sample up to 100 documents to infer schema
            query = "SELECT TOP 100 * FROM c"
            items = container_client.query_items(query=query, enable_cross_partition_query=True)

            # Collect all unique field names and types
            field_types: Dict[str, Set[str]] = {}

            sample_count = 0
            for item in items:
                sample_count += 1
                if sample_count > 100:  # Limit sampling
                    break

                self._analyze_document(item, field_types, seen_fields)

            # Build columns from inferred schema
            # Always include 'id' field first (required in Cosmos DB)
            # Check if id was seen in documents (it should be, but handle both cases)
            id_seen = "id" in seen_fields
            if id_seen:
                # id was seen in documents, use its inferred type (should be STRING)
                id_types = field_types.get("id", set())
                id_data_type = self._infer_data_type(id_types) if id_types else "STRING"
                columns.append(
                    SqlColumn(
                        name="id",
                        data_type=id_data_type,
                        is_nullable=False,
                        dialect="cosmosdb",
                    )
                )
            else:
                # id not seen (shouldn't happen, but handle gracefully)
                columns.append(
                    SqlColumn(
                        name="id",
                        data_type="STRING",
                        is_nullable=False,
                        dialect="cosmosdb",
                    )
                )

            # Add partition key field if different from id
            if (
                partition_key_field
                and partition_key_field != "id"
                and partition_key_field not in seen_fields
            ):
                columns.append(
                    SqlColumn(
                        name=partition_key_field,
                        data_type="STRING",  # Default to string, could be inferred
                        is_nullable=True,
                        dialect="cosmosdb",
                    )
                )

            # Add other fields (excluding id since we already added it)
            for field_name in sorted(seen_fields):
                if field_name in ("id", "_rid", "_self", "_etag", "_attachments", "_ts"):
                    continue  # Skip system fields (id already added above)

                # Determine data type from samples
                types = field_types.get(field_name, set())
                data_type = self._infer_data_type(types)

                columns.append(
                    SqlColumn(
                        name=field_name,
                        data_type=data_type,
                        is_nullable=True,  # Cosmos DB is schema-less, so fields are nullable
                        dialect="cosmosdb",
                    )
                )

        except Exception as e:
            self.log.warning(f"Error sampling documents from container {container_name}: {str(e)}")
            # Return at least the id column
            columns.append(
                SqlColumn(
                    name="id",
                    data_type="STRING",
                    is_nullable=False,
                    dialect="cosmosdb",
                )
            )

        return columns

    def _analyze_document(
        self, document: Dict[str, Any], field_types: Dict[str, Set[str]], seen_fields: Set[str]
    ) -> None:
        """
        Analyze a document to extract field names and types.

        Args:
            document: JSON document from Cosmos DB
            field_types: Dictionary mapping field names to sets of observed types
            seen_fields: Set of all field names seen so far
        """
        if not isinstance(document, dict):
            return

        for key, value in document.items():
            # Skip system fields
            if key.startswith("_"):
                continue

            seen_fields.add(key)

            # Determine type
            if value is None:
                field_types.setdefault(key, set()).add("NULL")
            elif isinstance(value, bool):
                field_types.setdefault(key, set()).add("BOOLEAN")
            elif isinstance(value, int):
                field_types.setdefault(key, set()).add("NUMBER")
            elif isinstance(value, float):
                field_types.setdefault(key, set()).add("NUMBER")
            elif isinstance(value, str):
                field_types.setdefault(key, set()).add("STRING")
            elif isinstance(value, list):
                field_types.setdefault(key, set()).add("ARRAY")
            elif isinstance(value, dict):
                field_types.setdefault(key, set()).add("OBJECT")
                # Recursively analyze nested objects (limited depth)
                self._analyze_document(value, field_types, seen_fields)

    def _infer_data_type(self, types: Set[str]) -> str:
        """
        Infer the most appropriate data type from observed types.

        Args:
            types: Set of observed type strings

        Returns:
            Data type string
        """
        # Remove NULL from consideration
        types = types - {"NULL"}

        if not types:
            return "STRING"  # Default

        # Prefer more specific types
        if "NUMBER" in types:
            return "NUMBER"
        elif "BOOLEAN" in types:
            return "BOOLEAN"
        elif "ARRAY" in types:
            return "ARRAY"
        elif "OBJECT" in types:
            return "OBJECT"
        elif "STRING" in types:
            return "STRING"

        return "STRING"  # Default fallback

    def get_indexes(self, schema: str, table: str) -> List[Index]:
        """
        Get indexes for a Cosmos DB container.

        Args:
            schema: Schema name (not used)
            table: Container name

        Returns:
            List of Index objects representing Cosmos DB indexing policies
        """
        self._ensure_connection()

        indexes = []

        try:
            container_client = self.provider.connection_manager.get_container_client(table)
            container_props = container_client.read()

            # Get indexing policy
            indexing_policy = container_props.get("indexingPolicy", {})
            included_paths = indexing_policy.get("includedPaths", [])
            excluded_paths = indexing_policy.get("excludedPaths", [])

            # Cosmos DB automatically indexes all paths by default
            # We can represent this as an index
            if included_paths or not excluded_paths:
                indexes.append(
                    Index(
                        name=f"auto_index_{table}",
                        table_name=table,
                        columns=["*"],  # All paths indexed
                        unique=False,
                        dialect="cosmosdb",
                    )
                )

        except Exception as e:
            self.log.warning(f"Error getting indexes for container {table}: {str(e)}")

        return indexes

    def get_views(self, schema: str) -> List[Any]:
        """Get views (not applicable to Cosmos DB)."""
        return []

    def get_materialized_views(self, schema: str) -> List[Any]:
        """Get materialized views (not applicable to Cosmos DB)."""
        return []

    def get_sequences(self, schema: str) -> List[Any]:
        """Get sequences (not applicable to Cosmos DB)."""
        return []

    def get_triggers(self, schema: str, table: Optional[str] = None) -> List[Any]:
        """Get triggers (not applicable to Cosmos DB SQL API)."""
        return []

    def get_procedures(self, schema: str) -> List[Any]:
        """Get stored procedures (Cosmos DB has stored procedures but not via SQL API)."""
        return []

    def get_functions(self, schema: str) -> List[Any]:
        """Get functions (not applicable to Cosmos DB)."""
        return []

    def get_packages(self, schema: str) -> List[Any]:
        """Get packages (not applicable to Cosmos DB)."""
        return []

    def get_synonyms(self, schema: str) -> List[Any]:
        """Get synonyms (not applicable to Cosmos DB)."""
        return []

    def get_user_defined_types(self, schema: str) -> List[Any]:
        """Get user-defined types (not applicable to Cosmos DB)."""
        return []

    def get_extensions(self) -> List[Any]:
        """Get extensions (not applicable to Cosmos DB)."""
        return []

    def get_foreign_data_wrappers(self) -> List[Any]:
        """Get foreign data wrappers (not applicable to Cosmos DB)."""
        return []

    def get_foreign_servers(self) -> List[Any]:
        """Get foreign servers (not applicable to Cosmos DB)."""
        return []

    def get_database_links(self, schema: str) -> List[Any]:
        """Get database links (not applicable to Cosmos DB)."""
        return []

    def get_events(self, schema: str) -> List[Any]:
        """Get events (not applicable to Cosmos DB)."""
        return []

    def get_check_constraints(self, schema: str, table: str) -> List[SqlConstraint]:
        """Get check constraints (not applicable to Cosmos DB)."""
        return []

    def introspect_schema(self, schema: str, **kwargs: Any) -> Dict[str, Any]:
        """
        Introspect an entire schema and return all objects.

        Args:
            schema: Schema name (not used in Cosmos DB, but kept for compatibility)
            **kwargs: Additional options (include_views, include_sequences, etc.)

        Returns:
            Dictionary with keys: tables, views, indexes, sequences, etc.
        """
        self._ensure_connection()

        result: Dict[str, Any] = {
            "tables": [],
            "views": [],
            "indexes": [],
            "sequences": [],
            "procedures": [],
            "functions": [],
            "triggers": [],
        }

        try:
            # Get all tables (containers)
            include_views = kwargs.get("include_views", False)
            table_pattern = kwargs.get("table_pattern", "%")
            result["tables"] = self.get_tables(
                schema, include_views=include_views, table_pattern=table_pattern
            )

            # Get indexes for each table
            for table in result["tables"]:
                indexes = self.get_indexes(schema, table.name)
                result["indexes"].extend(indexes)

            # Cosmos DB doesn't have views, sequences, procedures, functions, or triggers
            # via SQL API, so these remain empty

            self.log.debug(
                f"Introspected Cosmos DB schema: {len(result['tables'])} containers, "
                f"{len(result['indexes'])} indexes"
            )

        except Exception as e:
            error_msg = f"Error introspecting Cosmos DB schema: {str(e)}"
            self.log.error(error_msg)
            raise RuntimeError(error_msg) from e

        return result

    def get_database_info(self) -> Dict[str, str]:
        """
        Get Cosmos DB database information.

        Returns:
            Dictionary with database metadata
        """
        self._ensure_connection()

        try:
            account_info = self.provider.connection_manager.client.get_database_account()
            database = self.provider.connection_manager.database

            # DatabaseAccount is an object, not a dict - access attributes directly
            account_id = (
                getattr(account_info, "id", None) or getattr(account_info, "Id", None) or "unknown"
            )
            consistency_level = (
                getattr(account_info, "consistency_level", None)
                or getattr(account_info, "ConsistencyLevel", None)
                or "unknown"
            )

            return {
                "database_name": database.id if hasattr(database, "id") else "unknown",
                "account_id": account_id,
                "consistency_level": consistency_level,
            }
        except Exception as e:
            self.log.warning(f"Error getting database info: {str(e)}")
            return {}

    def close(self) -> None:
        """Close the introspector (no-op for Cosmos DB)."""

    def __enter__(self) -> "CosmosDbIntrospector":
        """Context manager entry."""
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Context manager exit."""
        self.close()
