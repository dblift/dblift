"""Base abstract class for database locking managers."""

from abc import ABC, abstractmethod
from typing import Any, Optional

from dblift.core.logger import Log, NullLog
from dblift.db.object_naming import get_normalized_object_name


class BaseLockingManager(ABC):
    """Abstract base class for database-specific locking managers.

    This class defines the common interface that all relational database providers
    must implement for migration lock management. Each database provider implements
    these methods according to their specific locking capabilities (native advisory
    locks, application locks, or table-based fallback).

    Subclasses must define:
        - ``DEFAULT_LOCK_TABLE``: table name in dialect-native case.
        - ``DIALECT``: dialect string used with ``get_normalized_object_name``.

    Subclasses should define ``DEFAULT_LOCK_TABLE`` in the database's native case
    (e.g. ``"DBLIFT_MIGRATION_LOCK"`` for Oracle/DB2, ``"dblift_migration_lock"``
    for PostgreSQL/MySQL/SQL Server/SQLite).

    Lock Table Schema Contract:
        All relational plugins MUST create a ``dblift_migration_lock`` table with
        the following columns:

        Required columns:
            - ``lock_name  VARCHAR(128) NOT NULL PRIMARY KEY``
              Unique lock identifier (e.g. ``'migration'``).
            - ``acquired_at  TIMESTAMP NOT NULL``
              Timestamp when the lock was acquired (usually ``CURRENT_TIMESTAMP``).
            - ``acquired_by  VARCHAR(128) NOT NULL``
              Identity of the lock holder (typically ``user@host:pid``).

        Optional columns (recommended):
            - ``session_id``   INTEGER or NUMBER — database session/connection ID.
            - ``process_id``   VARCHAR(64) — OS-level process identifier.
            - ``lock_mode``    INTEGER — lock mode flag (default 1 = exclusive).

        Naming conventions:
            - Database providers use lowercase column names (e.g. ``lock_name``).
            - Oracle and DB2 use UPPERCASE by SQL convention (e.g. ``LOCK_NAME``).

    Note: CosmosDB (NoSQL) implements a conceptually equivalent locking
    interface but does not inherit from this class due to its fundamentally different
    API (no connection parameter, document-based locking). Its methods are named
    differently (e.g., create_migration_lock_container_if_not_exists instead of
    create_migration_lock_table_if_not_exists) and do not accept a connection
    parameter. CosmosDB is exempt from this schema contract and uses its own
    document fields (``id``, ``locked_at``, ``locked_by``).
    """

    # Subclasses override these to provide dialect-specific values.
    DEFAULT_LOCK_TABLE: str = "dblift_migration_lock"
    DIALECT: str = ""

    def __init__(self, query_executor: Any, log: Optional[Log] = None) -> None:
        """Initialize the locking manager.

        Args:
            query_executor: Database-specific query executor instance
            log: Logger for operation tracking (defaults to NullLog if None)
        """
        self.query_executor: Any = query_executor
        self.log: Log = log if log is not None else NullLog()

    def _get_drop_table_sql(self, qualified_table: str) -> str:
        """Return dialect-specific DROP TABLE SQL.

        Default implementation uses ``IF EXISTS`` syntax (PostgreSQL, MySQL, SQL Server).
        DB2 overrides this because it does not support ``IF EXISTS`` on DROP TABLE.

        Args:
            qualified_table: Schema-qualified table name (already formatted).

        Returns:
            DROP TABLE statement string.
        """
        return f"DROP TABLE IF EXISTS {qualified_table}"

    def _drop_lock_table_if_exists(self, connection: Any, schema: str) -> None:
        """Drop the migration lock table if it exists.

        This is called after releasing a table-based lock to clean up the fallback
        table. Uses ``self.DEFAULT_LOCK_TABLE`` and ``self.DIALECT`` to determine
        the normalized table name; delegates the DROP statement to
        ``_get_drop_table_sql()``.

        Args:
            connection: Active database connection (provided by Provider).
            schema: Schema name.
        """
        try:
            dblift_lock_table = get_normalized_object_name(self.DEFAULT_LOCK_TABLE, self.DIALECT)
            if self.query_executor.table_exists(connection, schema, dblift_lock_table):
                qualified_table = self.query_executor.get_schema_qualified_name(
                    schema, dblift_lock_table
                )
                self.query_executor.execute_statement(
                    connection, self._get_drop_table_sql(qualified_table)
                )
                self.log.debug(f"Dropped migration lock table in schema: {schema}")
        except Exception as e:
            self.log.debug(f"Could not drop lock table (non-fatal): {str(e)}")

    @abstractmethod
    def create_migration_lock_table_if_not_exists(
        self,
        connection: Any,
        schema: str,
    ) -> None:
        """Create the migration lock table if it doesn't exist.

        Args:
            connection: Active database connection (provided by Provider)
            schema: Schema name for the lock table
        """

    @abstractmethod
    def acquire_migration_lock(
        self,
        connection: Any,
        schema: str,
        wait_timeout_seconds: int = 60,
    ) -> bool:
        """Acquire the migration lock, blocking until acquired or timeout.

        Args:
            connection: Active database connection (provided by Provider)
            schema: Schema name for the lock
            wait_timeout_seconds: Maximum seconds to wait for the lock

        Returns:
            True if lock was acquired, False if timeout occurred
        """

    @abstractmethod
    def release_migration_lock(
        self,
        connection: Any,
        schema: str,
    ) -> bool:
        """Release the migration lock.

        Args:
            connection: Active database connection (provided by Provider)
            schema: Schema name for the lock

        Returns:
            True if lock was successfully released
        """
