"""MongoDB migration lock, held as a lease document."""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any, Optional

from core.constants import DEFAULT_MIGRATION_LOCK_TIMEOUT_SECONDS
from core.logger import Log
from db.plugins.nosql_base import DocumentLockingManager

#: How long a lease stays valid before another process may reclaim it. A
#: holder that dies mid-migration must not block the collection forever.
LEASE_EXPIRY_SECONDS = 3600

#: Gap between acquisition attempts while another process holds the lease.
_POLL_INTERVAL_SECONDS = 1.0


class MongoDbLockingManager(DocumentLockingManager):
    """Guards concurrent migration runs with a single lease document.

    Mutual exclusion comes from the ``_id`` index, which MongoDB creates on
    every collection and enforces as unique: an ``insert_one`` with a fixed
    ``_id`` succeeds for exactly one process and raises ``DuplicateKeyError``
    for the rest. No transaction is needed, which matters because none is
    available on a standalone mongod.
    """

    LOCK_CONTAINER_NAME = "dblift_migration_lock"
    LOCK_DOCUMENT_ID = "migration_lock"

    def __init__(self, query_executor: Any, log: Optional[Log] = None) -> None:
        """Store the executor and the logger."""
        super().__init__(query_executor=query_executor, log=log)

    def _collection(self) -> Any:
        return self.query_executor.connection_manager.get_collection(self.LOCK_CONTAINER_NAME)

    def create_migration_lock_container_if_not_exists(self, schema: str) -> None:
        """Create the lock collection if it is missing. Idempotent.

        The index on ``_id`` already exists and is already unique, so the
        call below is about materialising the collection: MongoDB creates a
        collection lazily, and an index build is the cheapest way to force
        it without writing a document that would look like a held lease.
        """
        from db.plugins.mongodb.mongodb._sdk import ASCENDING_ORDER

        self._collection().create_index([("_id", ASCENDING_ORDER)])
        self.log.debug(f"Ensured lock collection exists: {self.LOCK_CONTAINER_NAME}")

    @staticmethod
    def _is_expired(lease: Optional[dict[str, Any]]) -> bool:
        """Whether *lease* is old enough to reclaim.

        An unreadable or absent timestamp counts as expired: a lease nobody
        can date is a lease nobody can wait out.
        """
        if not lease:
            return True
        acquired_at = lease.get("acquired_at")
        if not acquired_at:
            return True
        try:
            acquired = datetime.fromisoformat(str(acquired_at))
        except ValueError:
            return True
        if acquired.tzinfo is None:
            acquired = acquired.replace(tzinfo=timezone.utc)
        age = (datetime.now(timezone.utc) - acquired).total_seconds()
        return age > LEASE_EXPIRY_SECONDS

    def _try_insert_lease(self) -> bool:
        """Attempt the insert; ``False`` when another process already holds it."""
        from db.plugins.mongodb.mongodb._sdk import DuplicateKeyError

        try:
            self._collection().insert_one(
                {
                    "_id": self.LOCK_DOCUMENT_ID,
                    "acquired_at": datetime.now(timezone.utc).isoformat(),
                }
            )
            return True
        except DuplicateKeyError:
            return False

    def acquire_migration_lock(
        self, schema: str, wait_timeout_seconds: int = DEFAULT_MIGRATION_LOCK_TIMEOUT_SECONDS
    ) -> bool:
        """Take the lease, waiting up to *wait_timeout_seconds*."""
        deadline = time.monotonic() + max(wait_timeout_seconds, 0)

        while True:
            if self._try_insert_lease():
                self.log.debug("Acquired migration lock")
                return True

            existing = self._collection().find_one({"_id": self.LOCK_DOCUMENT_ID})
            if self._is_expired(existing):
                self.log.warning("Reclaiming an expired migration lock lease")
                if existing is not None:
                    result = self._collection().delete_one(
                        {"_id": self.LOCK_DOCUMENT_ID, "acquired_at": existing.get("acquired_at")}
                    )
                    if result.deleted_count > 0 and self._try_insert_lease():
                        return True
                else:
                    # No lease document exists, try to acquire it
                    if self._try_insert_lease():
                        return True

            if time.monotonic() >= deadline:
                self.log.warning(f"Could not acquire migration lock within {wait_timeout_seconds}s")
                return False
            time.sleep(_POLL_INTERVAL_SECONDS)

    def release_migration_lock(self, schema: str) -> bool:
        """Release the lease; ``True`` when one was removed."""
        result = self._collection().delete_one({"_id": self.LOCK_DOCUMENT_ID})
        released = int(result.deleted_count) > 0
        if released:
            self.log.debug("Released migration lock")
        return released
