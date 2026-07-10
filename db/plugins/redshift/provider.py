"""Redshift native provider (PostgreSQL-compatible)."""

from __future__ import annotations

from typing import Any

from core.migration.clean_summary import CleanExecutionSummary
from db.plugins.postgresql.provider import PostgreSqlProvider


def _is_statement_timeout_error(error: Exception) -> bool:
    message = str(error).lower()
    return "statement_timeout" in message or "statement timeout" in message


class RedshiftProvider(PostgreSqlProvider):
    """Redshift provider with Redshift-specific history and locking SQL."""

    canonical_dialect_key = "redshift"
    _migration_lock_connection: Any | None = None
    _migration_lock_transaction: Any | None = None

    def clean_schema(self, schema: str) -> CleanExecutionSummary:
        """Drop Redshift objects without querying PostgreSQL-only catalogs."""
        summary = CleanExecutionSummary()
        object_names = self._redshift_clean_object_names
        qualified_name = self.get_schema_qualified_name

        for view_name in object_names(_REDSHIFT_VIEWS_QUERY, schema):
            qualified_view = qualified_name(schema, view_name)
            drop_sql = f"DROP VIEW IF EXISTS {qualified_view} CASCADE"
            self.execute_statement(drop_sql)
            summary.record_drop(
                drop_sql,
                object_type="view",
                name=view_name,
                schema=schema,
            )

        for table_name in object_names(_REDSHIFT_TABLES_QUERY, schema):
            qualified_table = qualified_name(schema, table_name)
            drop_sql = f"DROP TABLE IF EXISTS {qualified_table} CASCADE"
            self.execute_statement(drop_sql)
            summary.record_drop(
                drop_sql,
                object_type="table",
                name=table_name,
                schema=schema,
            )

        return summary

    def get_clean_preview(self, schema: str) -> CleanExecutionSummary:
        """Preview Redshift objects clean would drop."""
        summary = CleanExecutionSummary()
        object_names = self._redshift_clean_object_names
        qualified_name = self.get_schema_qualified_name

        for view_name in object_names(_REDSHIFT_VIEWS_QUERY, schema):
            qualified_view = qualified_name(schema, view_name)
            summary.record_drop(
                f"DROP VIEW IF EXISTS {qualified_view} CASCADE",
                object_type="view",
                name=view_name,
                schema=schema,
            )

        for table_name in object_names(_REDSHIFT_TABLES_QUERY, schema):
            qualified_table = qualified_name(schema, table_name)
            summary.record_drop(
                f"DROP TABLE IF EXISTS {qualified_table} CASCADE",
                object_type="table",
                name=table_name,
                schema=schema,
            )

        return summary

    def _redshift_clean_object_names(
        self,
        query: str,
        schema: str,
    ) -> list[str]:
        rows = self.execute_query(query, [schema])
        column_name = "object_name"
        return [
            str(row.get(column_name) or row.get(column_name.upper()))
            for row in rows
            if row.get(column_name) or row.get(column_name.upper())
        ]

    def acquire_migration_lock(
        self,
        schema: str,
        wait_timeout_seconds: int = 60,
    ) -> bool:
        """Acquire a Redshift table lock on a dedicated transaction."""
        if getattr(self, "_migration_lock_transaction", None) is not None:
            return True

        self.create_migration_lock_table_if_not_exists(schema)
        connection = self.engine.connect()
        transaction = connection.begin()
        try:
            timeout_ms = max(1, int(wait_timeout_seconds) * 1000)
            connection.exec_driver_sql(f"SET statement_timeout = {timeout_ms}")
            table = self.MIGRATION_LOCK_TABLE
            qualified_table = self.get_schema_qualified_name(schema, table)
            connection.exec_driver_sql(f"LOCK {qualified_table}")
        except Exception as exc:
            try:
                transaction.rollback()
            finally:
                connection.close()
            if _is_statement_timeout_error(exc):
                return False
            raise

        self._migration_lock_connection = connection
        self._migration_lock_transaction = transaction
        return True

    def release_migration_lock(self, schema: str) -> bool:
        """Release the Redshift migration lock by ending its transaction."""
        transaction = getattr(self, "_migration_lock_transaction", None)
        connection = getattr(self, "_migration_lock_connection", None)
        if transaction is None or connection is None:
            return True

        try:
            transaction.commit()
            return True
        except Exception:
            try:
                transaction.rollback()
            except Exception:
                pass
            return False
        finally:
            try:
                connection.close()
            finally:
                self._migration_lock_connection = None
                self._migration_lock_transaction = None

    def create_history_table(self, schema: str, table_name: str) -> str:
        """Return SQL for the Redshift migration history table."""
        qualified_table = self.get_schema_qualified_name(schema, table_name)
        return f"""
            CREATE TABLE IF NOT EXISTS {qualified_table} (
                installed_rank INTEGER IDENTITY(1,1) PRIMARY KEY,
                version VARCHAR(50),
                description VARCHAR(200) NOT NULL,
                type VARCHAR(20) NOT NULL,
                script VARCHAR(1000) NOT NULL,
                checksum VARCHAR(64),
                installed_by VARCHAR(100) NOT NULL,
                installed_on TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                execution_time INTEGER NOT NULL,
                success BOOLEAN NOT NULL
            )
        """


__all__ = ["RedshiftProvider"]


_REDSHIFT_VIEWS_QUERY = """
    SELECT table_name AS object_name
    FROM information_schema.views
    WHERE table_schema = ?
    ORDER BY table_name
"""

_REDSHIFT_TABLES_QUERY = """
    SELECT table_name AS object_name
    FROM information_schema.tables
    WHERE table_schema = ?
      AND table_type = 'BASE TABLE'
    ORDER BY table_name
"""
