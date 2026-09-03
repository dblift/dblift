"""
SQLite migration history manager.

This module handles SQLite-specific migration history table operations including
creation, recording migrations, retrieving applied migrations, and repair operations.
"""

import os
import sqlite3
from typing import Any, Dict, List, Optional

from dblift.core.logger import Log
from dblift.db.object_naming import get_normalized_object_name
from dblift.db.plugins.base_history_manager import BaseHistoryManager


class SQLiteHistoryManager(BaseHistoryManager):
    """Manages SQLite migration history operations."""

    # SQLite is case-insensitive; we use lowercase by convention
    DEFAULT_HISTORY_TABLE = "dblift_schema_history"

    def __init__(
        self,
        query_executor: Any,
        schema_operations: Any,
        config: Any,
        log: Optional[Log] = None,
    ) -> None:
        """Initialize the history manager.

        Args:
            query_executor: Query executor instance
            schema_operations: Schema operations instance
            config: Configuration object (reserved; not used by this implementation)
            log: Optional logger
        """
        super().__init__(query_executor, schema_operations, config, log)

    def _get_table_name(self, raw_table: Optional[str] = None) -> str:
        """Get the history table name, normalized for SQLite.

        Uses the centralized get_normalized_object_name() for consistent
        case handling across all database dialects.

        Args:
            raw_table: Optional custom table name

        Returns:
            str: Table name to use
        """
        return get_normalized_object_name(raw_table or self.DEFAULT_HISTORY_TABLE, "sqlite")

    def create_migration_history_table_if_not_exists(
        self,
        connection: sqlite3.Connection,
        schema: str,
        create_schema: bool = False,
        table_name: str = "dblift_schema_history",
    ) -> None:
        """Create the migration history table if it doesn't exist.

        Args:
            connection: Active SQLite connection (provided by Provider)
            schema: Schema name (ignored for SQLite)
            create_schema: Whether to create schema (ignored for SQLite)
            table_name: Custom history table name
        """
        self.log.debug(f"Creating migration history table if not exists: {table_name}")

        try:
            table = self._get_table_name(table_name)

            # Check if table exists
            if self.query_executor.table_exists(connection, schema, table):
                if create_schema:
                    self._check_baseline_safety(connection, schema, table)
                self.log.debug(f"Migration history table {table} already exists")
                return

            # Create the table with SQLite-specific syntax
            # SQLite uses INTEGER PRIMARY KEY for auto-increment
            create_sql = f"""
            CREATE TABLE IF NOT EXISTS "{table}" (
                installed_rank INTEGER PRIMARY KEY AUTOINCREMENT,
                version TEXT,
                description TEXT,
                type TEXT,
                script TEXT,
                checksum TEXT,
                installed_by TEXT,
                installed_on TEXT DEFAULT (datetime('now')),
                execution_time INTEGER,
                success INTEGER
            )
            """

            self.query_executor.execute_statement(connection, create_sql)

            # Create index on version for faster lookups
            index_sql = f'CREATE INDEX IF NOT EXISTS "idx_{table}_version" ON "{table}" (version)'
            try:
                self.query_executor.execute_statement(connection, index_sql)
            except Exception as e:
                self.log.debug(f"Could not create version index: {e}")

            self.log.debug(f"Migration history table created successfully: {table}")

        except Exception as e:
            error_msg = f"Error creating migration history table: {str(e)}"
            self.log.error(error_msg)
            raise

    def record_migration(
        self,
        connection: sqlite3.Connection,
        schema: str,
        migration_info: Dict[str, Any],
        table_name: Optional[str] = None,
    ) -> None:
        """Record a migration in the history table.

        Args:
            connection: Active SQLite connection (provided by Provider)
            schema: Schema name (ignored for SQLite)
            migration_info: Dictionary containing migration information
            table_name: Custom history table name
        """
        table = self._get_table_name(table_name)

        if not self.query_executor.table_exists(connection, schema, table):
            self.create_migration_history_table_if_not_exists(
                connection, schema, True, table_name or "dblift_schema_history"
            )

        try:
            # SQLite doesn't need manual rank calculation with AUTOINCREMENT
            insert_sql = f"""
            INSERT INTO "{table}" (
                version, description, type, script,
                checksum, installed_by, installed_on, execution_time, success
            ) VALUES (?, ?, ?, ?, ?, ?, datetime('now'), ?, ?)
            """

            # Convert boolean to integer for SQLite
            success_value = 1 if migration_info.get("success", True) else 0

            params = [
                migration_info.get("version"),
                migration_info.get("description"),
                migration_info.get("type"),
                migration_info.get("script"),
                migration_info.get("checksum"),
                migration_info.get("installed_by", os.environ.get("USER", "dblift")),
                migration_info.get("execution_time", 0),
                success_value,
            ]

            self.query_executor.execute_statement(connection, insert_sql, params=params)

            self.log.debug(f"Migration recorded: {migration_info.get('script')}")

        except Exception as e:
            error_msg = f"Error recording migration: {str(e)}"
            self.log.error(error_msg)
            raise

    def get_applied_migrations(
        self, connection: sqlite3.Connection, schema: str, table_name: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Get list of applied migrations from history table.

        Args:
            connection: Active SQLite connection (provided by Provider)
            schema: Schema name (ignored for SQLite)
            table_name: Custom history table name

        Returns:
            List of dictionaries containing migration information
        """
        table = self._get_table_name(table_name)

        if not self.query_executor.table_exists(connection, schema, table):
            return []

        query = f"""
        SELECT script, installed_rank, version, description,
               type, checksum, installed_by, installed_on,
               execution_time, success
        FROM "{table}"
        ORDER BY installed_rank
        """

        try:
            results = self.query_executor.execute_query(connection, query)

            # Convert SQLite integer success values to boolean
            for row in results:
                if "success" in row and row["success"] is not None:
                    row["success"] = bool(row["success"])

            return list(results)  # Ensure it's a list, not Any

        except Exception as e:
            error_msg = f"Error getting applied migrations: {str(e)}"
            self.log.error(error_msg)
            raise

    def create_history_table(self, schema: str, table_name: str) -> str:
        """Generate the SQL to create a migration history table.

        Args:
            schema: Schema name (ignored for SQLite)
            table_name: Table name

        Returns:
            str: SQL for creating the history table
        """
        table = self._get_table_name(table_name)
        return f"""
        CREATE TABLE IF NOT EXISTS "{table}" (
            installed_rank INTEGER PRIMARY KEY AUTOINCREMENT,
            version TEXT,
            description TEXT,
            type TEXT,
            script TEXT,
            checksum TEXT,
            installed_by TEXT,
            installed_on TEXT DEFAULT (datetime('now')),
            execution_time INTEGER,
            success INTEGER
        )
        """
