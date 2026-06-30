"""Schema snapshot table manager for database providers."""

from __future__ import annotations

from typing import Any

from db.constants import CHECKSUM_VARCHAR_SIZE, SNAPSHOT_ID_VARCHAR_SIZE
from db.exceptions import DB_OPERATION_EXCEPTIONS
from db.object_naming import get_normalized_object_name
from db.provider_registry import ProviderRegistry


class BaseSnapshotManager:
    """Creates the schema snapshot storage table for providers.

    The manager delegates connection state, schema management, and statement
    execution to the owning provider. It owns only the dialect-aware
    SQL generation for the snapshot table and the commit/rollback wrap-up.
    """

    def __init__(self, provider: Any) -> None:
        """Store the owning provider used for connection state and SQL execution."""
        self._provider = provider

    @property
    def _log(self) -> Any:
        return self._provider.log

    def _is_provider_connected(self) -> bool:
        """Return connection state while tolerating lightweight provider test doubles."""
        provider = self._provider
        is_connected = getattr(provider, "is_connected", None)
        if not callable(is_connected):
            return True
        try:
            return bool(is_connected())
        except AttributeError as exc:
            if "_connection" in str(exc):
                return True
            raise

    def _provider_dialect(self) -> str:
        """Return the provider dialect from config or the provider class metadata."""
        provider = self._provider
        config = getattr(provider, "config", None)
        database = getattr(config, "database", None)
        return (
            getattr(database, "type", None)
            or getattr(provider, "canonical_dialect_key", None)
            or ""
        ).lower()

    def _provider_owns_legacy_snapshot_ddl(self, dialect: str) -> bool:
        """True only for the canonical native provider class (not a generic
        provider configured with the same type). Whether that provider keeps
        legacy compat DDL is then decided by its quirks."""
        provider_key = getattr(self._provider.__class__, "canonical_dialect_key", None)
        return provider_key is not None and provider_key == dialect

    def create_snapshot_table_if_not_exists(
        self, schema: str, table_name: str = "dblift_schema_snapshots"
    ) -> None:
        """Create the schema snapshot storage table if it does not exist."""
        provider = self._provider

        if not self._is_provider_connected():
            provider.create_connection()

        provider.create_schema_if_not_exists(schema)

        dialect = self._provider_dialect()
        dblift_table_name = get_normalized_object_name(table_name, dialect)
        quirks = ProviderRegistry.get_quirks(dialect)
        uses_compat = self._provider_owns_legacy_snapshot_ddl(dialect)

        skip_existence_check = uses_compat and quirks.provider_compat_snapshot_skips_existence_check
        if not skip_existence_check and provider.table_exists(schema, dblift_table_name):
            return

        qualified_table = provider.get_schema_qualified_name(schema, dblift_table_name)

        try:
            create_table_sql = quirks.build_snapshot_table_ddl(
                qualified_table,
                SNAPSHOT_ID_VARCHAR_SIZE,
                CHECKSUM_VARCHAR_SIZE,
            )
        except NotImplementedError:
            if not uses_compat:
                raise
            compat_sql = quirks.build_provider_compat_snapshot_ddl(
                qualified_table,
                SNAPSHOT_ID_VARCHAR_SIZE,
                CHECKSUM_VARCHAR_SIZE,
            )
            if compat_sql is None:
                raise
            create_table_sql = compat_sql

        try:
            provider.execute_statement(create_table_sql, schema=schema)

            if hasattr(provider, "connection") and provider.connection:
                try:
                    if not provider.connection.getAutoCommit():
                        provider.connection.commit()
                        self._log.debug("Committed snapshot table creation")
                except DB_OPERATION_EXCEPTIONS as commit_e:
                    if hasattr(provider, "commit_transaction"):
                        try:
                            provider.commit_transaction()
                            self._log.debug(
                                "Committed snapshot table creation via commit_transaction"
                            )
                        except DB_OPERATION_EXCEPTIONS as fallback_e:
                            self._log.debug(
                                f"Could not commit snapshot table creation "
                                f"[type={type(commit_e).__name__}, "
                                f"fallback_type={type(fallback_e).__name__}]: {commit_e}"
                            )
                    else:
                        self._log.debug(
                            f"Could not commit snapshot table creation "
                            f"[type={type(commit_e).__name__}]: {commit_e}"
                        )
        except DB_OPERATION_EXCEPTIONS as e:
            if hasattr(provider, "connection") and provider.connection:
                try:
                    if not provider.connection.getAutoCommit():
                        provider.connection.rollback()
                except DB_OPERATION_EXCEPTIONS as rollback_e:
                    self._log.debug(
                        f"Snapshot table rollback skipped "
                        f"[type={type(rollback_e).__name__}]: {rollback_e}"
                    )

            if quirks.is_snapshot_table_already_exists_error(str(e)):
                self._log.debug(
                    f"Snapshot table {schema}.{table_name} already exists "
                    f"({type(e).__name__}); ignoring"
                )
                return

            raise


__all__ = ["BaseSnapshotManager"]
