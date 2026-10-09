"""
SQLite migration locking manager.

SQLite has no advisory locks, so the migration lock is a lease in a lock
table: a row that exists while the lock is held, refreshed by a heartbeat
and reclaimed once its holder stops refreshing it (see
:mod:`dblift.db.plugins.lease_lock`).
"""

import os
import sqlite3
from functools import partial
from typing import Any, Optional

from dblift.core.constants import MIGRATION_LOCK_TABLE
from dblift.core.logger import Log, NullLog
from dblift.db.plugins.base_locking_manager import BaseLockingManager
from dblift.db.plugins.lease_lock import LeaseLock
from dblift.db.plugins.sql_lease_store import (
    OWNER_COLUMN,
    LeaseSession,
    Sqlite3LeaseSession,
    SqlLeaseDialect,
    SqlLeaseStore,
    ensure_owner_column,
)

from .schema_operations import SQLiteSchemaOperations

#: How long a lease statement waits for another connection's write lock
#: before reporting the store busy. Short: the heartbeat must not stall, and
#: a busy store is itself proof that a writer is alive.
LEASE_BUSY_TIMEOUT_SECONDS = 2.0


def _seconds_before(clock: str, seconds: str) -> str:
    return f"datetime({clock}, '-{seconds} seconds')"


def _is_database_locked(error: BaseException) -> bool:
    """``database is locked``: another connection holds the write lock right now."""
    if not isinstance(error, sqlite3.OperationalError):
        return False
    message = str(error).lower()
    return "locked" in message or "busy" in message


def _database_file(connection: sqlite3.Connection) -> str:
    """Return the file behind the connection's main database ('' when in memory)."""
    for row in connection.execute("PRAGMA database_list").fetchall():
        if row[1] == "main":
            return str(row[2] or "")
    return ""


def _lock_row_present(connection: sqlite3.Connection, dialect: SqlLeaseDialect) -> bool:
    """Whether *connection* sees a lock row (held, or left by a dead holder)."""
    row = connection.execute(
        f"SELECT 1 FROM {dialect.table} WHERE {dialect.name_column} = ?", [dialect.lock_name]
    ).fetchone()
    return row is not None


class SQLiteLockingManager(BaseLockingManager):
    """Manages SQLite migration locking operations."""

    # SQLite is case-insensitive; we use lowercase by convention
    DEFAULT_LOCK_TABLE = MIGRATION_LOCK_TABLE

    def __init__(self, query_executor: Any, log: Optional[Log] = None) -> None:
        """Initialize the locking manager.

        Args:
            query_executor: Query executor instance for database operations
            log: Optional logger
        """
        self.query_executor: Any = query_executor
        self.log: Log = log if log is not None else NullLog()
        self._lease: Optional[LeaseLock] = None

    def create_migration_lock_table_if_not_exists(
        self, connection: sqlite3.Connection, schema: str
    ) -> None:
        """Create the migration lock table if it doesn't exist.

        A table created before the lease lacks the owner column; it is added.

        Args:
            connection: Active SQLite connection (provided by Provider)
            schema: Target schema name (ignored for SQLite)
        """
        self.log.debug("Creating migration lock table if not exists")

        try:
            create_table_sql = f"""
            CREATE TABLE IF NOT EXISTS "{MIGRATION_LOCK_TABLE}" (
                lock_name TEXT NOT NULL PRIMARY KEY,
                acquired_at TEXT DEFAULT (datetime('now')) NOT NULL,
                acquired_by TEXT NOT NULL,
                process_id TEXT,
                lock_mode INTEGER DEFAULT 1 NOT NULL,
                {OWNER_COLUMN} TEXT
            )
            """

            self.query_executor.execute_statement(connection, create_table_sql)
            schema_operations = SQLiteSchemaOperations(self.query_executor, self.log)
            ensure_owner_column(
                partial(self.query_executor.execute_query, connection),
                partial(self.query_executor.execute_statement, connection),
                schema_operations.get_columns_query(schema, MIGRATION_LOCK_TABLE),
                schema_operations.get_add_column_sql(
                    schema, MIGRATION_LOCK_TABLE, OWNER_COLUMN, "TEXT"
                ),
            )
            self.log.debug("Migration lock table ensured")

        except Exception as e:
            error_msg = f"Error creating migration lock table: {str(e)}"
            self.log.error(error_msg)
            raise

    def _lease_dialect(self, schema: str) -> SqlLeaseDialect:
        """Describe the SQLite lock table; ``datetime('now')`` is UTC."""
        user = os.environ.get("USER", os.environ.get("USERNAME", "dblift"))
        return SqlLeaseDialect(
            table=f'"{MIGRATION_LOCK_TABLE}"',
            lock_name=f"{MIGRATION_LOCK_TABLE}_{schema}",
            timestamp_column="acquired_at",
            now_utc="datetime('now')",
            legacy_now="datetime('now')",
            seconds_before=_seconds_before,
            is_busy=_is_database_locked,
            insert_values=(("acquired_by", "?"), ("process_id", "?"), ("lock_mode", "1")),
            insert_params=(user, str(os.getpid())),
        )

    def acquire_migration_lock(
        self, connection: sqlite3.Connection, schema: str, wait_timeout_seconds: int = 60
    ) -> bool:
        """Acquire an exclusive migration lock.

        The lease runs on its own connection to the same file, so its
        heartbeat commits beside a migration transaction. An in-memory
        database cannot be reached by any other connection: its lock row is
        kept on *connection* itself, with no heartbeat.

        A caller's transaction still open on *connection* (``from_sqlalchemy``)
        holds SQLite's write lock, which would block the lease connection.
        When the lock is free, that pending work is committed first, as taking
        the lock always did; when the lock is held, it is left untouched.

        Args:
            connection: Active SQLite connection (provided by Provider)
            schema: Target schema name (used for lock naming)
            wait_timeout_seconds: Maximum time to wait for lock acquisition

        Returns:
            bool: True if lock was acquired successfully, False otherwise
        """
        self.log.debug(f"Attempting to acquire migration lock for schema: {schema}")
        if self._lease is not None:
            return True
        callers_transaction = connection.in_transaction
        self.create_migration_lock_table_if_not_exists(connection, schema)
        dialect = self._lease_dialect(schema)
        if callers_transaction and not _lock_row_present(connection, dialect):
            connection.commit()

        path = _database_file(connection)
        session: LeaseSession
        if path:
            lease_connection = sqlite3.connect(
                path,
                timeout=LEASE_BUSY_TIMEOUT_SECONDS,
                isolation_level=None,
                check_same_thread=False,
            )
            session = Sqlite3LeaseSession(lease_connection, owns_connection=True)
        else:
            session = Sqlite3LeaseSession(connection, owns_connection=False)

        lease = LeaseLock(SqlLeaseStore(dialect, session), log=self.log, heartbeat=bool(path))
        if not lease.acquire(wait_timeout_seconds):
            self.log.warning(
                f"Failed to acquire migration lock within {wait_timeout_seconds} seconds"
            )
            return False
        self._lease = lease
        self.log.debug(f"Successfully acquired migration lock for: {schema}")
        return True

    def release_migration_lock(self, connection: sqlite3.Connection, schema: str) -> bool:
        """Release the migration lock.

        Args:
            connection: Active SQLite connection (provided by Provider)
            schema: Target schema name

        Returns:
            bool: True if this process's lock was released, False when none
            was held or another process had reclaimed it
        """
        lease, self._lease = self._lease, None
        released = lease.release() if lease is not None else False
        if not released:
            self.log.debug(f"Lock was not held by this process for: {schema}")
        return released

    def migration_lock_lost(self) -> bool:
        """Whether the held lease was reclaimed or could not be renewed in time."""
        return self._lease is not None and self._lease.lost

    def close(self) -> None:
        """Release a lease still held (the provider is closing)."""
        lease, self._lease = self._lease, None
        if lease is not None:
            lease.release()
