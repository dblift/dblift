"""CockroachDB native provider (PostgreSQL-compatible)."""

from __future__ import annotations

from dblift.db.plugins.postgresql.provider import PostgreSqlProvider
from dblift.db.plugins.sql_lease_store import (
    OWNER_COLUMN,
    OWNER_COLUMN_TYPE,
    SqlLeaseDialect,
    SqlLeaseLockingProvider,
    interval_before,
)


def _is_transaction_retry(error: BaseException) -> bool:
    """A serialization conflict (SQLSTATE 40001): another writer is active."""
    message = str(error).lower()
    return "40001" in message or "restart transaction" in message


class CockroachdbProvider(SqlLeaseLockingProvider, PostgreSqlProvider):
    """CockroachDB provider with a lease in the lock table as migration lock."""

    canonical_dialect_key = "cockroachdb"

    def create_migration_lock_table_if_not_exists(self, schema: str) -> None:
        """Create the lock table; a table created before the lease gains the owner column."""
        super().create_migration_lock_table_if_not_exists(schema)
        qualified_table = self.get_schema_qualified_name(schema, self.MIGRATION_LOCK_TABLE)
        self.execute_statement(
            f"ALTER TABLE {qualified_table} "
            f"ADD COLUMN IF NOT EXISTS {OWNER_COLUMN} {OWNER_COLUMN_TYPE}"
        )

    def _migration_lease_dialect(self, schema: str) -> SqlLeaseDialect:
        """Describe the CockroachDB lock table.

        Rows written before the lease hold ``CURRENT_TIMESTAMP`` stored in a
        ``TIMESTAMP`` column, i.e. the session time zone's wall clock.
        """
        return SqlLeaseDialect(
            table=self.get_schema_qualified_name(schema, self.MIGRATION_LOCK_TABLE),
            lock_name="migration",
            now_utc="timezone('UTC', now())",
            legacy_now="CAST(CURRENT_TIMESTAMP AS TIMESTAMP)",
            seconds_before=interval_before,
            is_busy=_is_transaction_retry,
        )


__all__ = ["CockroachdbProvider"]
