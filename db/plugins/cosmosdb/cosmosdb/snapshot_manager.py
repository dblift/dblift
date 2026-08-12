"""Cosmos DB snapshot container provisioning."""

from __future__ import annotations

import time
from typing import Any, Optional

from core.logger import Log
from db.plugins.nosql_base import DocumentSnapshotManager


class CosmosDbSnapshotManager(DocumentSnapshotManager):
    """Creates the snapshot container through the Azure SDK, retrying on 503.

    Cosmos has no DDL. The inherited relational default renders
    ``CREATE TABLE`` and sends it to ``execute_statement``; that only ever
    worked while the pseudo-SQL emulator recognised the statement and turned
    it into a container create. With the emulator gone the statement raises,
    so the container is created directly here.

    The Azure emulator also returns ServiceUnavailable / 503 during warmup,
    so the create is retried with exponential backoff — that is why snapshot
    persistence survives the first migrate after a fresh container start.
    """

    MAX_RETRIES = 5
    BACKOFF_BASE = 2.0

    def __init__(self, provider: Any, log: Optional[Log] = None) -> None:
        """Take the owning provider; the logger defaults to the provider's."""
        super().__init__(provider=provider, log=log if log is not None else provider.log)

    @staticmethod
    def _is_transient(exc: Exception) -> bool:
        msg = str(exc).lower()
        return (
            "serviceunavailable" in msg
            or "service unavailable" in msg
            or "503" in msg
            or "timeout" in msg
            or "timed out" in msg
        )

    def create_snapshot_collection(self, collection_name: str) -> None:
        """Create the snapshot container, partitioned on ``/snapshot_id``.

        Snapshots are keyed by ``snapshot_id``; partitioning on it lets a
        point read find one without a cross-partition query.
        """
        last_exc: Optional[Exception] = None
        for attempt in range(self.MAX_RETRIES):
            try:
                self.provider.schema_operations.create_container_if_not_exists(
                    collection_name, partition_key="/snapshot_id"
                )
                return
            except Exception as e:
                last_exc = e
                if attempt < self.MAX_RETRIES - 1 and self._is_transient(e):
                    wait = self.BACKOFF_BASE**attempt
                    self.log.warning(
                        f"Snapshot container creation transient failure "
                        f"(attempt {attempt + 1}/{self.MAX_RETRIES}): {e}. "
                        f"Retrying in {wait:.1f}s…"
                    )
                    time.sleep(wait)
                    continue
                break
        raise RuntimeError(f"Failed to create snapshot container: {str(last_exc)}") from last_exc
