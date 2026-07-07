"""CockroachDB native provider (PostgreSQL-compatible)."""

from __future__ import annotations

import time

from db.plugins.postgresql.provider import PostgreSqlProvider


def _is_lock_contention_error(error: Exception) -> bool:
    message = str(error).lower()
    markers = (
        "duplicate key",
        "unique constraint",
        "violates unique",
    )
    return any(marker in message for marker in markers)


class CockroachdbProvider(PostgreSqlProvider):
    """CockroachDB provider with table-backed migration locking."""

    canonical_dialect_key = "cockroachdb"

    def acquire_migration_lock(
        self,
        schema: str,
        wait_timeout_seconds: int = 60,
    ) -> bool:
        """Acquire a CockroachDB migration lock using a committed lock row."""
        self.create_migration_lock_table_if_not_exists(schema)
        lock_table = self.MIGRATION_LOCK_TABLE
        qualified_table = self.get_schema_qualified_name(schema, lock_table)

        deadline = time.monotonic() + max(0, int(wait_timeout_seconds))
        while True:
            try:
                self.execute_statement(
                    f"""
                    INSERT INTO {qualified_table} (lock_name, locked_at)
                    VALUES (?, CURRENT_TIMESTAMP)
                    """,
                    params=["migration"],
                )
                return True
            except Exception as exc:
                self._rollback_failed_lock_attempt()
                if not _is_lock_contention_error(exc):
                    raise
                if time.monotonic() >= deadline:
                    return False
                time.sleep(min(0.2, max(0, deadline - time.monotonic())))

    def release_migration_lock(self, schema: str) -> bool:
        """Release the CockroachDB migration lock row."""
        if not self.table_exists(schema, self.MIGRATION_LOCK_TABLE):
            return True
        lock_table = self.MIGRATION_LOCK_TABLE
        qualified_table = self.get_schema_qualified_name(schema, lock_table)
        affected = self.execute_statement(
            f"""
            DELETE FROM {qualified_table}
            WHERE lock_name = ?
            """,
            params=["migration"],
        )
        return affected > 0

    def _rollback_failed_lock_attempt(self) -> None:
        connection = getattr(self, "_connection", None)
        if connection is not None:
            try:
                connection.rollback()
            except Exception as exc:
                message = "Could not rollback failed CockroachDB lock attempt"
                raise RuntimeError(message) from exc


__all__ = ["CockroachdbProvider"]
