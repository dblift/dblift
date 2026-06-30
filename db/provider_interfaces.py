"""
Interfaces focalisées pour les providers de base de données (ISP).

Chaque interface déclare un groupe cohérent de capacités.
Les providers n'ont pas à implémenter toutes les interfaces — utiliser
isinstance(provider, TransactionalProvider) pour vérifier le support.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Protocol, runtime_checkable

from core.migration.clean_summary import CleanExecutionSummary


@dataclass(frozen=True)
class DroppableObject:
    """Database object that clean can drop without rich schema introspection."""

    name: str
    object_type: str
    drop_sql: str
    record_result: bool = True


class ConnectionProvider(ABC):
    """Capacité de connexion à une base de données."""

    @abstractmethod
    def create_connection(self) -> Any:
        """Create a database connection.

        Returns:
            Connection object (type depends on provider)
        """
        ...

    @abstractmethod
    def close(self) -> None:
        """Close the database connection."""
        ...

    @abstractmethod
    def is_connected(self) -> bool:
        """Check if the provider is connected to the database.

        Returns:
            True if connected, False otherwise
        """
        ...

    @abstractmethod
    def connect(self) -> None:
        """Connect to the database."""
        ...


class QueryProvider(ABC):
    """Capacité d'exécution de requêtes SQL."""

    @abstractmethod
    def execute_statement(
        self, sql: str, schema: Optional[str] = None, params: Optional[List[Any]] = None
    ) -> int:
        """Execute a SQL statement.

        Args:
            sql: SQL statement to execute
            schema: Optional schema context
            params: Optional parameters for the statement

        Returns:
            Number of rows affected
        """
        ...

    @abstractmethod
    def execute_query(self, sql: str, params: Optional[List[Any]] = None) -> List[Dict[str, Any]]:
        """Execute a SQL query and return results.

        Args:
            sql: SQL query to execute
            params: Optional parameters for the query

        Returns:
            List of dictionaries, each representing a row with column names as keys
        """
        ...

    def get_parameter_placeholders(self, count: int) -> str:
        """Get parameter placeholders for prepared statements.

        Args:
            count: Number of placeholders needed

        Returns:
            String of comma-separated placeholders (e.g., "?, ?, ?")
        """
        return ", ".join(["?"] * count)


class SchemaProvider(ABC):
    """Capacité de gestion du schéma de base de données."""

    @abstractmethod
    def create_schema_if_not_exists(self, schema: str) -> None:
        """Create a schema if it doesn't exist.

        Args:
            schema: Name of the schema to create
        """
        ...

    @abstractmethod
    def table_exists(self, schema: str, table_name: str) -> bool:
        """Check if a table exists in the specified schema.

        Args:
            schema: Schema name
            table_name: Table name

        Returns:
            True if the table exists, False otherwise
        """
        ...

    @abstractmethod
    def get_database_version(self) -> str:
        """Get the database version information.

        Returns:
            Database version string
        """
        ...

    @abstractmethod
    def set_current_schema(self, schema: str) -> None:
        """Set the default schema for the connection.

        Args:
            schema: Schema name
        """
        ...

    @abstractmethod
    def get_schema_qualified_name(self, schema: str, object_name: str) -> str:
        """Get a properly formatted schema-qualified object name.

        Args:
            schema: Schema name
            object_name: Object name (table, view, etc.)

        Returns:
            Properly formatted schema.object name for this database
        """
        ...

    @abstractmethod
    def clean_schema(self, schema: str) -> Any:
        """Clean a schema by dropping all objects.

        Args:
            schema: Schema name

        Returns:
            Structured summary of executed statements and dropped objects.
        """
        ...

    def list_droppable_objects(self, schema: str) -> List[DroppableObject]:
        """Return schema objects in the order clean should drop them."""
        raise NotImplementedError(f"{type(self).__name__} must implement list_droppable_objects()")

    @abstractmethod
    def create_snapshot_table_if_not_exists(
        self, schema: str, table_name: str = "dblift_schema_snapshots"
    ) -> None:
        """Create the schema snapshot storage table if it does not exist.

        Args:
            schema: Schema name
            table_name: Table name for snapshots (default: dblift_schema_snapshots)
        """
        ...

    @abstractmethod
    def create_data_history_table_if_not_exists(self, schema: str, table_name: str) -> None:
        """Create the per-dataset data history (ledger) table if it does not exist.

        Args:
            schema: Schema name
            table_name: Data history table name
        """
        ...

    @abstractmethod
    def create_data_change_set_table_if_not_exists(
        self, schema: str, table_name: str = "dblift_data_change_set"
    ) -> None:
        """Create the data change-set table (before/after payloads via snapshot codec) if it does not exist.

        Args:
            schema: Schema name
            table_name: Table name (default from core.constants)
        """
        ...


class TransactionalProvider(ABC):
    """Capacité de gestion des transactions."""

    @abstractmethod
    def begin_transaction(self) -> None:
        """Begin a database transaction."""
        ...

    @abstractmethod
    def commit_transaction(self) -> None:
        """Commit the current transaction."""
        ...

    @abstractmethod
    def rollback_transaction(self) -> None:
        """Rollback the current transaction."""
        ...

    def supports_transactions(self) -> bool:
        """Retourne True si ce provider supporte les transactions traditionnelles.

        Override dans les providers non-transactionnels (ex: CosmosDB).
        Permet aux callers de vérifier avant d'appeler begin/commit/rollback.
        """
        return True

    def supports_snapshots(self) -> bool:
        """Return True if the provider supports schema snapshot persistence.

        Override to False in providers where the snapshot repository queries
        cannot be executed. Defaults to True for all SQL providers including CosmosDB.
        """
        return True

    def supports_transactional_ddl(self) -> bool:
        """Return True if the database supports transactional DDL (rollback of CREATE/ALTER/DROP).

        Databases like PostgreSQL, SQL Server, and DB2 support transactional DDL.
        MySQL and Oracle auto-commit DDL statements, meaning rollback cannot undo them.
        Override to False in providers where DDL is non-transactional.
        """
        return True


class MigrationProvider(ABC):
    """Capacité de tracking des migrations."""

    @abstractmethod
    def get_applied_migrations(
        self, schema: str, table_name: str = "dblift_schema_history"
    ) -> List[Dict[str, Any]]:
        """Get list of applied migrations from history table.

        Args:
            schema: Schema name
            table_name: Custom history table name (default: dblift_schema_history)

        Returns:
            List of dictionaries containing migration information
        """
        ...

    @abstractmethod
    def record_migration(
        self, schema: str, migration_info: Dict[str, Any], table_name: str = "dblift_schema_history"
    ) -> None:
        """Record a migration in the history table.

        Args:
            schema: Schema name
            migration_info: Dictionary containing migration information
            table_name: Custom history table name (default: dblift_schema_history)
        """
        ...

    @abstractmethod
    def create_history_table(self, schema: str, table_name: str) -> str:
        """Get the SQL to create the migration history table.

        Args:
            schema: Schema name
            table_name: History table name

        Returns:
            SQL string to create the history table
        """
        ...

    @abstractmethod
    def create_history_table_if_not_exists(
        self, schema: str, create_schema: bool = False, table_name: str = "dblift_schema_history"
    ) -> None:
        """Create the migration history table if it doesn't exist.

        Args:
            schema: Schema name
            create_schema: Whether to create the schema if it doesn't exist
            table_name: History table name (default: dblift_schema_history)
        """
        ...

    @abstractmethod
    def create_migration_lock_table_if_not_exists(self, schema: str) -> None:
        """Create the migration lock table if it doesn't exist.

        Args:
            schema: Schema name
        """
        ...

    @abstractmethod
    def acquire_migration_lock(self, schema: str, wait_timeout_seconds: int = 60) -> bool:
        """Acquire a lock for migration.

        Args:
            schema: Schema name
            wait_timeout_seconds: How long to wait for lock acquisition in seconds

        Returns:
            True if lock acquired successfully, False otherwise
        """
        ...

    @abstractmethod
    def release_migration_lock(self, schema: str) -> bool:
        """Release migration lock.

        Args:
            schema: Schema name

        Returns:
            True if lock released successfully, False otherwise
        """
        ...


@runtime_checkable
class ConnectionStateProvider(Protocol):
    """Optional hook for providers that can eagerly open or refresh a connection."""

    def _ensure_connection(self) -> None:
        """Ensure the provider has an active connection."""
        ...


@runtime_checkable
class ProviderUrlProvider(Protocol):
    """Optional neutral display URL contract for providers."""

    def get_display_url(self) -> str:
        """Return a user-facing connection URL suitable for masking and logs."""
        ...


@runtime_checkable
class CleanPreviewProvider(Protocol):
    """Optional native clean dry-run contract."""

    def get_clean_preview(self, schema: str) -> CleanExecutionSummary:
        """Return the objects a clean operation would remove without dropping them."""
        ...
