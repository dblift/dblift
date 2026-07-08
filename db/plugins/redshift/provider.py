"""Redshift native provider (PostgreSQL-compatible)."""

from __future__ import annotations

from db.plugins.postgresql.provider import PostgreSqlProvider


def _is_statement_timeout_error(error: Exception) -> bool:
    message = str(error).lower()
    return "statement_timeout" in message or "statement timeout" in message


class RedshiftProvider(PostgreSqlProvider):
    """Redshift provider with Redshift-specific history and locking SQL."""

    canonical_dialect_key = "redshift"

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
