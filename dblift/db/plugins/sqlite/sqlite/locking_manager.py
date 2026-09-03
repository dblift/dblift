"""
SQLite migration locking manager.

This module handles SQLite-specific migration locking using a table-based
approach. SQLite doesn't have native advisory locks like PostgreSQL,
so we use a simple lock table mechanism.
"""

import os
import sqlite3
import time
from typing import Any, Optional

from dblift.core.logger import Log, NullLog
from dblift.db.plugins.base_locking_manager import BaseLockingManager


class SQLiteLockingManager(BaseLockingManager):
    """Manages SQLite migration locking operations."""

    # SQLite is case-insensitive; we use lowercase by convention
    DEFAULT_LOCK_TABLE = "dblift_migration_lock"

    def __init__(self, query_executor: Any, log: Optional[Log] = None) -> None:
        """Initialize the locking manager.

        Args:
            query_executor: Query executor instance for database operations
            log: Optional logger
        """
        self.query_executor: Any = query_executor
        self.log: Log = log if log is not None else NullLog()

    def create_migration_lock_table_if_not_exists(
        self, connection: sqlite3.Connection, schema: str
    ) -> None:
        """Create the migration lock table if it doesn't exist.

        Args:
            connection: Active SQLite connection (provided by Provider)
            schema: Target schema name (ignored for SQLite)
        """
        self.log.debug("Creating migration lock table if not exists")

        try:
            create_table_sql = """
            CREATE TABLE IF NOT EXISTS "dblift_migration_lock" (
                lock_name TEXT NOT NULL PRIMARY KEY,
                acquired_at TEXT DEFAULT (datetime('now')) NOT NULL,
                acquired_by TEXT NOT NULL,
                process_id TEXT,
                lock_mode INTEGER DEFAULT 1 NOT NULL
            )
            """

            self.query_executor.execute_statement(connection, create_table_sql)
            self.log.debug("Migration lock table ensured")

        except Exception as e:
            error_msg = f"Error creating migration lock table: {str(e)}"
            self.log.error(error_msg)
            raise

    def acquire_migration_lock(
        self, connection: sqlite3.Connection, schema: str, wait_timeout_seconds: int = 60
    ) -> bool:
        """Acquire an exclusive migration lock.

        Uses a table-based locking mechanism since SQLite doesn't support
        advisory locks like PostgreSQL.

        Args:
            connection: Active SQLite connection (provided by Provider)
            schema: Target schema name (used for lock naming)
            wait_timeout_seconds: Maximum time to wait for lock acquisition

        Returns:
            bool: True if lock was acquired successfully, False otherwise
        """
        self.log.debug(f"Attempting to acquire migration lock for schema: {schema}")

        try:
            # Ensure lock table exists
            self.create_migration_lock_table_if_not_exists(connection, schema)

            lock_name = f"dblift_migration_lock_{schema}"
            start_time = time.time()

            while time.time() - start_time < wait_timeout_seconds:
                try:
                    # First, clean up any stale locks from crashed processes
                    self._cleanup_stale_locks(connection, lock_name)

                    # Try to insert lock record (will fail if lock already exists)
                    insert_sql = """
                    INSERT INTO "dblift_migration_lock"
                    (lock_name, acquired_at, acquired_by, process_id, lock_mode)
                    VALUES (?, datetime('now'), ?, ?, 1)
                    """

                    process_id = str(os.getpid())
                    user = os.environ.get("USER", os.environ.get("USERNAME", "dblift"))

                    self.query_executor.execute_statement(
                        connection, insert_sql, params=[lock_name, user, process_id]
                    )

                    # Commit the lock immediately
                    connection.commit()

                    self.log.debug(f"Successfully acquired migration lock for: {schema}")
                    return True

                except sqlite3.IntegrityError:
                    # Lock is held by another process, wait and retry
                    elapsed = int(time.time() - start_time)
                    self.log.debug(
                        f"Lock held by another process, waiting... (elapsed: {elapsed}s)"
                    )
                    time.sleep(1)
                    continue

                except Exception as e:
                    error_str = str(e).lower()
                    if "unique" in error_str or "constraint" in error_str:
                        # Lock is held by another process
                        elapsed = int(time.time() - start_time)
                        self.log.debug(f"Lock held, waiting... (elapsed: {elapsed}s)")
                        time.sleep(1)
                        continue
                    else:
                        # Unexpected error
                        self.log.warning(f"Error during lock acquisition: {str(e)}")
                        time.sleep(1)
                        continue

            # Timeout exceeded
            self.log.warning(
                f"Failed to acquire migration lock within {wait_timeout_seconds} seconds"
            )
            return False

        except Exception as e:
            error_msg = f"Error acquiring migration lock: {str(e)}"
            self.log.error(error_msg)
            return False

    def _cleanup_stale_locks(self, connection: sqlite3.Connection, lock_name: str) -> None:
        """Clean up stale locks from crashed processes.

        In SQLite, we can't easily detect if a process is still alive,
        so we use a timeout-based approach for stale lock detection.

        Args:
            connection: Active SQLite connection
            lock_name: Name of the lock to check
        """
        try:
            # Consider locks older than 24 hours as stale
            # This is a conservative timeout to avoid accidentally cleaning up valid locks
            delete_sql = """
            DELETE FROM "dblift_migration_lock"
            WHERE lock_name = ?
            AND datetime(acquired_at) < datetime('now', '-24 hours')
            """

            rows_deleted = self.query_executor.execute_statement(
                connection, delete_sql, params=[lock_name]
            )

            if rows_deleted > 0 and self.log:
                self.log.debug(f"Cleaned up {rows_deleted} stale lock(s)")

        except Exception as e:
            self.log.debug(f"Could not cleanup stale locks: {str(e)}")

    def release_migration_lock(self, connection: sqlite3.Connection, schema: str) -> bool:
        """Release the migration lock.

        Args:
            connection: Active SQLite connection (provided by Provider)
            schema: Target schema name

        Returns:
            bool: True if lock was released successfully, False otherwise
        """
        self.log.debug(f"Attempting to release migration lock for schema: {schema}")

        try:
            lock_name = f"dblift_migration_lock_{schema}"
            process_id = str(os.getpid())

            # Only delete lock if we own it (same process_id)
            delete_sql = """
            DELETE FROM "dblift_migration_lock"
            WHERE lock_name = ? AND process_id = ?
            """

            rows_deleted = self.query_executor.execute_statement(
                connection, delete_sql, params=[lock_name, process_id]
            )

            # Commit the deletion
            connection.commit()

            if rows_deleted > 0:
                self.log.debug(f"Successfully released migration lock for: {schema}")
                return True
            else:
                self.log.debug(f"Lock was not held by this process for: {schema}")
                return False

        except Exception as e:
            error_msg = f"Error releasing migration lock: {str(e)}"
            self.log.error(error_msg)
            return False
