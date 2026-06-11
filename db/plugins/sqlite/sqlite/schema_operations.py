"""
SQLite schema operations and metadata queries.

This module handles SQLite-specific schema operations including
cleaning and metadata queries for tables, columns, and other database objects.

Note: SQLite doesn't support schemas - the entire database file is the "schema".
"""

import sqlite3
from typing import Any, List, Optional, Tuple

from core.logger import Log, NullLog
from core.migration.clean_summary import CleanExecutionSummary


class SQLiteSchemaOperations:
    """Handles SQLite schema operations and metadata queries."""

    def __init__(self, query_executor: Any, log: Optional[Log] = None) -> None:
        """Initialize the schema operations manager.

        Args:
            query_executor: Query executor instance
            log: Optional logger
        """
        self.query_executor: Any = query_executor
        self.log: Log = log if log is not None else NullLog()

    _FTS5_SHADOW_SUFFIXES = (
        "_data",
        "_idx",
        "_content",
        "_docsize",
        "_config",
        "_segdir",
        "_segments",
        "_stat",
    )

    def _fts5_shadow_table_names(self, connection: sqlite3.Connection) -> set[str]:
        """Return the set of FTS5 shadow (internal) table names.

        BUG-05: ``CREATE VIRTUAL TABLE foo USING fts5(...)`` produces five
        internal tables (``foo_data``, ``foo_idx``, ``foo_content``,
        ``foo_docsize``, ``foo_config``) that SQLite exposes via
        ``sqlite_master`` as regular tables. Treating them as user tables
        inflates object counts in schema introspection and makes ``clean``
        attempt a plain ``DROP TABLE`` against an FTS5-managed shadow.
        """
        try:
            rows = self.query_executor.execute_query(
                connection,
                "SELECT name FROM sqlite_master "
                "WHERE type = 'table' AND sql LIKE '%VIRTUAL TABLE%USING fts5%'",
            )
        except Exception as e:
            self.log.debug(f"FTS5 shadow detection query failed: {e}")
            return set()
        vts = [str(r["name"]) for r in rows if r.get("name")]
        return {f"{vt}{s}" for vt in vts for s in self._FTS5_SHADOW_SUFFIXES}

    def create_schema_if_not_exists(self, connection: sqlite3.Connection, schema: str) -> None:
        """Create schema if it doesn't exist.

        Note: SQLite doesn't support schemas. This is a no-op for compatibility.

        Args:
            connection: Active SQLite connection (provided by Provider)
            schema: Schema name (ignored for SQLite)
        """
        self.log.debug(f"SQLite doesn't support schemas. Schema '{schema}' parameter ignored.")
        # No-op for SQLite - the database file IS the schema

    # Single source of truth for which objects a clean would drop — used by
    # both dry-run enumeration (clean_command.py) and actual clean_schema below.
    # Keep the enumeration order aligned with clean_schema's drop order.
    def enumerate_clean_candidates(
        self, connection: sqlite3.Connection, schema: str
    ) -> List[Tuple[str, str, str]]:
        """Return (object_type, name, drop_sql) triples for every droppable object.

        Returned in clean order: views → triggers → indexes → tables.

        OBS-04: clean produces a true empty slate. The lock table, history
        table, and snapshot table are all dropped; the lock manager
        re-creates the lock table on the next ``acquire_migration_lock``.
        """
        candidates: List[Tuple[str, str, str]] = []

        views_query = (
            "SELECT name FROM sqlite_master "
            "WHERE type = 'view' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )
        for row in self.query_executor.execute_query(connection, views_query):
            name = row.get("name")
            if name:
                candidates.append(("view", name, f'DROP VIEW IF EXISTS "{name}"'))

        # OBS-04: clean drops the lock table along with history/snapshots.
        # Triggers, indexes, and the table itself are all in scope. The lock
        # manager re-creates the table on the next acquire_migration_lock.
        triggers_query = (
            "SELECT name FROM sqlite_master "
            "WHERE type = 'trigger' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )
        for row in self.query_executor.execute_query(connection, triggers_query):
            name = row.get("name")
            if name:
                candidates.append(("trigger", name, f'DROP TRIGGER IF EXISTS "{name}"'))

        indexes_query = (
            "SELECT name FROM sqlite_master "
            "WHERE type = 'index' AND name NOT LIKE 'sqlite_%' "
            "AND name NOT LIKE 'sqlite_autoindex_%' ORDER BY name"
        )
        for row in self.query_executor.execute_query(connection, indexes_query):
            name = row.get("name")
            if name:
                candidates.append(("index", name, f'DROP INDEX IF EXISTS "{name}"'))

        tables_query = (
            "SELECT name FROM sqlite_master "
            "WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )
        shadow_names = self._fts5_shadow_table_names(connection)
        for row in self.query_executor.execute_query(connection, tables_query):
            name = row.get("name")
            if name and name not in shadow_names:
                candidates.append(("table", name, f'DROP TABLE IF EXISTS "{name}"'))

        return candidates

    def get_clean_preview(
        self, connection: sqlite3.Connection, schema: str
    ) -> CleanExecutionSummary:
        """Return a CleanExecutionSummary listing what a clean would drop, without executing anything."""
        summary = CleanExecutionSummary()
        for object_type, name, drop_sql in self.enumerate_clean_candidates(connection, schema):
            summary.add_object(object_type=object_type, name=name, schema=None)
            summary.add_statement(drop_sql)
        return summary

    def clean_schema(self, connection: sqlite3.Connection, schema: str) -> CleanExecutionSummary:
        """Clean all objects from the SQLite database.

        This drops all user-created tables, views, triggers, and indexes,
        leaving only system tables.

        Args:
            connection: Active SQLite connection (provided by Provider)
            schema: Schema name (ignored for SQLite)

        Returns:
            CleanExecutionSummary: Statements executed and objects removed.
        """
        self.log.debug("Cleaning SQLite database")

        summary = CleanExecutionSummary()

        try:
            # Disable foreign key checks temporarily to allow dropping tables
            connection.execute("PRAGMA foreign_keys = OFF")

            for object_type, name, drop_sql in self.enumerate_clean_candidates(connection, schema):
                try:
                    self.query_executor.execute_statement(connection, drop_sql)
                    summary.record_drop(drop_sql, object_type=object_type, name=name, schema=None)
                    self.log.debug(f"Dropped {object_type}: {name}")
                except Exception as e:
                    self.log.warning(f"Failed to drop {object_type} {name}: {str(e)}")

            # Re-enable foreign key checks
            connection.execute("PRAGMA foreign_keys = ON")

            self.log.debug(
                f"Schema cleanup completed. Executed {len(summary.statements)} statements."
            )

            return summary

        except Exception as e:
            error_msg = f"Error cleaning database: {str(e)}"
            self.log.error(error_msg)
            # Try to re-enable foreign keys even on error
            try:
                connection.execute("PRAGMA foreign_keys = ON")
            except Exception as pragma_e:
                self.log.debug(f"Could not re-enable SQLite foreign keys after error: {pragma_e}")
            raise

    def get_database_version(self, connection: sqlite3.Connection) -> str:
        """Get SQLite database version information.

        Args:
            connection: Active SQLite connection (provided by Provider)

        Returns:
            str: SQLite database version string
        """
        try:
            result = self.query_executor.execute_query(
                connection, "SELECT sqlite_version() as version"
            )
            if result and len(result) > 0:
                version = result[0].get("version", "Unknown")
                return f"SQLite {version}"
            return "SQLite (unknown version)"
        except Exception as e:
            self.log.warning(f"Could not determine SQLite version: {str(e)}")
            return "SQLite (unknown version)"

    def set_current_schema(self, connection: sqlite3.Connection, schema: str) -> None:
        """Set the current schema for the session.

        Note: SQLite doesn't support schemas. This is a no-op for compatibility.

        Args:
            connection: Active SQLite connection (provided by Provider)
            schema: Schema name (ignored for SQLite)
        """
        self.log.debug("SQLite doesn't support schemas. set_current_schema is a no-op.")
        # No-op for SQLite

    def get_columns_query(self, schema: str, table: str) -> str:
        """Get a SQLite-specific query to retrieve column information from a table.

        Args:
            schema: Schema name (ignored for SQLite)
            table: Table name

        Returns:
            str: PRAGMA statement to get column information
        """
        # Use PRAGMA table_info which returns:
        # cid, name, type, notnull, dflt_value, pk
        return f"PRAGMA table_info('{table}')"

    def get_add_column_sql(self, schema: str, table: str, column: str, type_def: str) -> str:
        """Generate SQLite-specific SQL to add a column to a table.

        Note: SQLite has limited ALTER TABLE support - only ADD COLUMN is supported.

        Args:
            schema: Schema name (ignored for SQLite)
            table: Table name
            column: Column name to add
            type_def: Column data type definition

        Returns:
            str: SQL for adding the column
        """
        # SQLite uses simple double quotes for identifiers
        clean_table = table.replace('"', '""')
        clean_column = column.replace('"', '""')
        return f'ALTER TABLE "{clean_table}" ADD COLUMN "{clean_column}" {type_def}'

    def get_parameter_placeholders(self, count: int) -> str:
        """Get SQLite-specific parameter placeholders for prepared statements.

        Args:
            count: Number of parameters

        Returns:
            str: Parameter placeholders string
        """
        # SQLite uses ? for positional parameters
        return ", ".join(["?"] * count)

    def get_tables(self, connection: sqlite3.Connection, schema: str) -> List[str]:
        """Get list of table names in the database.

        Args:
            connection: Active SQLite connection (provided by Provider)
            schema: Schema name (ignored for SQLite)

        Returns:
            List of table names
        """
        self.log.debug("Getting tables in SQLite database")

        try:
            query = """
            SELECT name
            FROM sqlite_master
            WHERE type = 'table' AND name NOT LIKE 'sqlite_%'
            ORDER BY name
            """

            result = self.query_executor.execute_query(connection, query)
            shadow_names = self._fts5_shadow_table_names(connection)
            tables = [str(row["name"]) for row in result if row["name"] not in shadow_names]

            self.log.debug(f"Found {len(tables)} tables: {tables}")

            return tables
        except Exception as e:
            self.log.error(f"Error getting tables: {str(e)}")
            return []

    def get_schemas(self, connection: sqlite3.Connection) -> List[str]:
        """Get list of schema names.

        Note: SQLite doesn't support schemas. Returns ['main'] for compatibility.

        Args:
            connection: Active SQLite connection (provided by Provider)

        Returns:
            List containing 'main' (SQLite's default schema name)
        """
        # SQLite uses 'main' as the default schema for the primary database
        return ["main"]
