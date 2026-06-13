"""Persistence layer for schema snapshots.

Wraps the target database's ``dblift_schema_snapshots`` table with insert /
read / cap-and-prune helpers, including the dialect quirks (Oracle uppercase
identifiers, DB2 explicit commit, CosmosDB missing-container probe).
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import List, Optional

from core.migration.snapshots.schema_snapshot import (
    SNAPSHOT_TABLE_NAME,
    SchemaSnapshot,
    SchemaSnapshotPayload,
)
from db.base_provider import BaseProvider
from db.provider_capabilities import ensure_provider_connection

_ORACLE_DIALECTS = frozenset({"oracle"})  # lint: allow-dialect-string: dialect dispatch


class SchemaSnapshotRepository:
    """Persistence layer for schema snapshots stored in the target database."""

    def __init__(
        self,
        provider: BaseProvider,
        schema: str,
        table_name: Optional[str] = None,
        logger: Optional[logging.Logger] = None,
    ):
        """Bind the repository to a provider/schema and resolve the dialect-cased table name."""
        self.provider = provider
        self.schema = schema
        default_table = getattr(provider.config, "snapshot_table", SNAPSHOT_TABLE_NAME)
        raw_table_name = table_name or default_table

        # Use database-specific default case for dblift objects
        self.table_name = provider.get_normalized_object_name(raw_table_name)
        self.logger = logger or logging.getLogger(__name__)

    def ensure_table(self) -> None:
        """Create the snapshot table on first use; refreshes the connection if needed."""
        # Ensure we have a valid connection before checking table existence
        self._ensure_valid_connection()
        self.provider.create_snapshot_table_if_not_exists(self.schema, self.table_name)

    def _ensure_valid_connection(self) -> None:
        """Ensure the provider has a valid, open database connection."""
        try:
            # Try to ensure connection via provider hook if available.
            if ensure_provider_connection(self.provider):
                if self.logger:
                    self.logger.debug("Ensured valid connection via provider")
            elif hasattr(self.provider, "query_executor") and hasattr(
                self.provider.query_executor, "_ensure_connection"
            ):
                self.provider.query_executor._ensure_connection()
                if self.logger:
                    self.logger.debug("Ensured valid connection via query executor")
        except Exception as e:
            if self.logger:
                self.logger.debug(f"Could not ensure valid connection: {e}")

    def _get_snapshot_table_qualified_name(self) -> str:
        """Get qualified table name for snapshot table.

        For Oracle, uses unquoted uppercase identifiers to match table creation.
        For other databases, uses get_schema_qualified_name.
        """
        dialect = getattr(self.provider.config.database, "type", "").lower()
        if dialect in _ORACLE_DIALECTS:
            # Oracle snapshot table is created with unquoted uppercase identifiers
            schema_upper = self.schema.upper()
            table_upper = self.table_name.upper()
            return f"{schema_upper}.{table_upper}"
        else:
            return self.provider.get_schema_qualified_name(self.schema, self.table_name)

    def save_snapshot(
        self,
        payload: SchemaSnapshotPayload,
        migration_version: Optional[str] = None,
        installed_rank: Optional[int] = None,
        captured_at: Optional[datetime] = None,
    ) -> SchemaSnapshot:
        """Persist ``payload`` as a new snapshot row, stamping migration/dialect metadata."""
        # Ensure clean transaction state before snapshot operations (for DB2)
        # This prevents blocking issues from uncommitted transactions
        try:
            if hasattr(self.provider, "connection") and self.provider.connection:
                if not self.provider.connection.getAutoCommit():
                    # Rollback any existing uncommitted transaction to ensure clean state
                    try:
                        self.provider.connection.rollback()
                        if self.logger:
                            self.logger.debug(
                                "Rolled back existing transaction before snapshot creation"
                            )
                    except Exception:
                        # Intentional: rollback on a dead/closed connection is non-fatal
                        pass
        except Exception:
            # Intentional: transaction state check before snapshot is best-effort only
            pass

        self.ensure_table()
        snapshot = SchemaSnapshot(
            snapshot_id=str(uuid.uuid4()),
            captured_at=captured_at or datetime.now(timezone.utc),
            payload=payload,
        )
        snapshot.payload.metadata.setdefault(
            "dialect", getattr(self.provider.config.database, "type", None)
        )
        snapshot.payload.metadata.setdefault("schema", self.schema)
        if migration_version:
            snapshot.payload.metadata.setdefault("migration", {})[
                "last_version"
            ] = migration_version
        if installed_rank is not None:
            snapshot.payload.metadata.setdefault("migration", {})["installed_rank"] = installed_rank

        qualified_table = self._get_snapshot_table_qualified_name()
        placeholders = self.provider.get_parameter_placeholders(4)
        sql = (
            f"INSERT INTO {qualified_table} "
            "(snapshot_id, captured_at, checksum, model_data) "
            f"VALUES ({placeholders})"
        )
        values = snapshot.to_record_values()

        try:
            self.provider.execute_statement(sql, schema=self.schema, params=values)

            # CRITICAL: Commit snapshot insertion for databases with autoCommit=False (e.g., DB2)
            # This ensures the snapshot is persisted immediately
            try:
                if hasattr(self.provider, "commit_transaction"):
                    self.provider.commit_transaction()
                    if self.logger:
                        self.logger.debug("Committed snapshot transaction")
            except Exception as e:
                # Log but don't fail - some databases may auto-commit or handle this differently
                if self.logger:
                    self.logger.debug(
                        f"Could not commit snapshot transaction (may be auto-committed): {e}"
                    )
        except Exception as e:
            if self.logger:
                self.logger.error(f"Failed to save snapshot for schema '{self.schema}': {e}")
            try:
                if hasattr(self.provider, "rollback_transaction"):
                    self.provider.rollback_transaction()
            except Exception as rollback_err:
                if self.logger:
                    self.logger.debug(
                        f"Rollback after save_snapshot failure also failed: {rollback_err}"
                    )
            raise

        if self.logger:
            self.logger.debug(
                "Schema snapshot %s stored with checksum %s",
                snapshot.snapshot_id,
                snapshot.checksum,
            )
        return snapshot

    def save_snapshot_with_limit(
        self,
        payload: SchemaSnapshotPayload,
        max_snapshots: int,
        migration_version: Optional[str] = None,
        installed_rank: Optional[int] = None,
        captured_at: Optional[datetime] = None,
    ) -> SchemaSnapshot:
        """Save a snapshot and enforce the maximum snapshot limit.

        Args:
            payload: Snapshot payload to save
            max_snapshots: Maximum number of snapshots to keep
            migration_version: Optional migration version
            installed_rank: Optional installed rank
            captured_at: Optional capture timestamp

        Returns:
            The saved SchemaSnapshot
        """
        # Save the new snapshot first
        snapshot = self.save_snapshot(
            payload=payload,
            migration_version=migration_version,
            installed_rank=installed_rank,
            captured_at=captured_at,
        )

        # Then enforce the limit by deleting old snapshots
        if max_snapshots > 0:
            deleted_count = self.delete_old_snapshots(max_snapshots)
            if deleted_count > 0 and self.logger:
                self.logger.info(
                    f"Deleted {deleted_count} old snapshot(s) to maintain limit of {max_snapshots}"
                )

        return snapshot

    def _snapshot_table_exists(self) -> bool:
        """Return True if the backing snapshot table/container exists.

        Read paths must NOT issue their SELECT against a missing table.
        Aside from being wasteful on Database providers, on CosmosDB the SDK's
        ``query_items`` iterator can hang indefinitely when the target
        container has not been created yet (BUG-06). Guarding with a
        probe keeps read semantics correct (``None`` / empty list) and
        fast across every dialect.

        Real infrastructure errors (connection refused, auth failure,
        timeout) from ``provider.table_exists`` propagate unchanged so
        callers can distinguish "no snapshot yet" from "can't talk to
        the database."
        """
        self._ensure_valid_connection()
        return self.provider.table_exists(self.schema, self.table_name)

    def get_latest_snapshot(self) -> Optional[SchemaSnapshot]:
        """Return the most-recently-captured snapshot, or ``None`` if the table is empty/missing."""
        if not self._snapshot_table_exists():
            return None
        qualified_table = self._get_snapshot_table_qualified_name()
        sql = (
            "SELECT snapshot_id, captured_at, checksum, model_data "
            f"FROM {qualified_table} "
            "ORDER BY captured_at DESC"
        )
        rows = self.provider.execute_query(sql)
        if not rows:
            return None
        return SchemaSnapshot.from_record(rows[0])

    def get_snapshot_by_id(self, snapshot_id: str) -> Optional[SchemaSnapshot]:
        """Look up a snapshot by its UUID; returns ``None`` if not found or the table is missing."""
        if not self._snapshot_table_exists():
            return None
        qualified_table = self._get_snapshot_table_qualified_name()
        sql = (
            "SELECT snapshot_id, captured_at, checksum, model_data "
            f"FROM {qualified_table} "
            "WHERE snapshot_id = ?"
        )
        rows = self.provider.execute_query(sql, params=[snapshot_id])
        if not rows:
            return None
        return SchemaSnapshot.from_record(rows[0])

    def list_snapshots(self, limit: Optional[int] = None) -> List[SchemaSnapshot]:
        """List snapshots newest-first, optionally truncated to ``limit`` rows."""
        if not self._snapshot_table_exists():
            return []
        qualified_table = self._get_snapshot_table_qualified_name()
        sql = (
            "SELECT snapshot_id, captured_at, checksum, model_data "
            f"FROM {qualified_table} "
            "ORDER BY captured_at DESC"
        )
        rows = self.provider.execute_query(sql)
        if limit is not None:
            rows = rows[: limit if limit > 0 else 0]
        return [SchemaSnapshot.from_record(row) for row in rows]

    def delete_old_snapshots(self, max_snapshots: int) -> int:
        """Delete old snapshots, keeping only the most recent max_snapshots.

        Args:
            max_snapshots: Maximum number of snapshots to keep

        Returns:
            Number of snapshots deleted
        """
        if max_snapshots <= 0:
            # If max_snapshots is 0 or negative, delete all snapshots
            return self._delete_all_snapshots()

        self.ensure_table()
        qualified_table = self._get_snapshot_table_qualified_name()

        # Get all snapshots ordered by captured_at DESC
        sql = (
            "SELECT snapshot_id, captured_at, checksum, model_data "
            f"FROM {qualified_table} "
            "ORDER BY captured_at DESC"
        )
        rows = self.provider.execute_query(sql)

        if len(rows) <= max_snapshots:
            # No snapshots to delete
            return 0

        # Get snapshot IDs to delete (all except the first max_snapshots)
        snapshots_to_delete = rows[max_snapshots:]
        snapshot_ids_to_delete = []
        for row in snapshots_to_delete:
            # Normalize keys to lowercase (matching from_record behavior)
            normalized_row = {
                (key.lower() if isinstance(key, str) else key): value for key, value in row.items()
            }
            snapshot_id = normalized_row.get("snapshot_id")
            if snapshot_id:
                snapshot_ids_to_delete.append(str(snapshot_id))

        if not snapshot_ids_to_delete:
            return 0

        # Delete old snapshots
        placeholders = self.provider.get_parameter_placeholders(len(snapshot_ids_to_delete))
        delete_sql = f"DELETE FROM {qualified_table} " f"WHERE snapshot_id IN ({placeholders})"

        try:
            affected = self.provider.execute_statement(
                delete_sql, schema=self.schema, params=snapshot_ids_to_delete
            )

            # Commit deletion for databases with autoCommit=False (e.g., DB2)
            try:
                if hasattr(self.provider, "commit_transaction"):
                    self.provider.commit_transaction()
                    if self.logger:
                        self.logger.debug("Committed snapshot deletion transaction")
            except Exception as e:
                if self.logger:
                    self.logger.debug(
                        f"Could not commit snapshot deletion transaction (may be auto-committed): {e}"
                    )

            if self.logger:
                self.logger.debug(
                    f"Deleted {affected} old snapshot(s), keeping {max_snapshots} most recent"
                )
            return affected
        except Exception as e:
            if self.logger:
                self.logger.warning(f"Error deleting old snapshots from '{self.schema}': {e}")
            try:
                if hasattr(self.provider, "rollback_transaction"):
                    self.provider.rollback_transaction()
            except Exception as rollback_err:
                if self.logger:
                    self.logger.debug(
                        f"Rollback after delete_old_snapshots failure also failed: {rollback_err}"
                    )
            raise

    def _delete_all_snapshots(self) -> int:
        """Delete all snapshots from the table.

        Returns:
            Number of snapshots deleted
        """
        self.ensure_table()
        qualified_table = self._get_snapshot_table_qualified_name()
        delete_sql = f"DELETE FROM {qualified_table}"

        try:
            affected = self.provider.execute_statement(delete_sql, schema=self.schema)

            # Commit deletion for databases with autoCommit=False (e.g., DB2)
            try:
                if hasattr(self.provider, "commit_transaction"):
                    self.provider.commit_transaction()
                    if self.logger:
                        self.logger.debug("Committed snapshot deletion transaction")
            except Exception as e:
                if self.logger:
                    self.logger.debug(
                        f"Could not commit snapshot deletion transaction (may be auto-committed): {e}"
                    )

            if self.logger:
                self.logger.debug(f"Deleted all {affected} snapshot(s)")
            return affected
        except Exception as e:
            if self.logger:
                self.logger.warning(f"Error deleting all snapshots from '{self.schema}': {e}")
            try:
                if hasattr(self.provider, "rollback_transaction"):
                    self.provider.rollback_transaction()
            except Exception as rollback_err:
                if self.logger:
                    self.logger.debug(
                        f"Rollback after delete_all_snapshots failure also failed: {rollback_err}"
                    )
            raise
