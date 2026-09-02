"""MongoDB migration lock, held as a lease document."""

from __future__ import annotations

import threading
import time
from datetime import datetime, timezone
from typing import Any, Optional

from dblift.core.constants import DEFAULT_MIGRATION_LOCK_TIMEOUT_SECONDS
from dblift.core.logger import Log
from dblift.db.plugins.nosql_base import DocumentLockingManager

#: How long a lease stays valid without a refresh before another process may
#: reclaim it. Deliberately short: a live holder renews well before this
#: elapses (see ``_HEARTBEAT_INTERVAL_SECONDS``), so the expiry only ever
#: fires for a holder that has actually stopped — a crashed or killed
#: process is detected and reclaimable within seconds, not after guessing
#: how long the longest migration might run.
LEASE_EXPIRY_SECONDS = 30

#: Gap between acquisition attempts while another process holds the lease.
_POLL_INTERVAL_SECONDS = 1.0

#: How often the current holder refreshes ``acquired_at`` while it still
#: holds the lease. A third of LEASE_EXPIRY_SECONDS gives two missed beats
#: of slack for a slow network round trip before the lease looks stale.
_HEARTBEAT_INTERVAL_SECONDS = LEASE_EXPIRY_SECONDS / 3


class MongoDbLockingManager(DocumentLockingManager):
    """Guards concurrent migration runs with a single lease document.

    Mutual exclusion comes from the ``_id`` index, which MongoDB creates on
    every collection and enforces as unique: an ``insert_one`` with a fixed
    ``_id`` succeeds for exactly one process and raises ``DuplicateKeyError``
    for the rest. No transaction is needed, which matters because none is
    available on a standalone mongod.

    The lease itself is short-lived (``LEASE_EXPIRY_SECONDS``) and kept
    alive by a background heartbeat while held, rather than sized to the
    longest migration anyone might run: a live holder never lets the lease
    go stale, so migration duration cannot cause a lock to be stolen out
    from under it, while a holder that crashes or is killed is detected
    and reclaimed within one lease window instead of an arbitrary timeout.
    """

    LOCK_CONTAINER_NAME = "dblift_migration_lock"
    LOCK_DOCUMENT_ID = "migration_lock"

    def __init__(self, query_executor: Any, log: Optional[Log] = None) -> None:
        """Store the executor and the logger."""
        super().__init__(query_executor=query_executor, log=log)
        self._heartbeat_thread: Optional[threading.Thread] = None
        self._heartbeat_stop: Optional[threading.Event] = None

    def _collection(self) -> Any:
        return self.query_executor.connection_manager.get_collection(self.LOCK_CONTAINER_NAME)

    def _start_heartbeat(self) -> None:
        """Refresh the held lease on a timer so a still-running holder is
        never mistaken for a dead one by ``_is_expired``."""
        stop = threading.Event()
        self._heartbeat_stop = stop

        def _refresh() -> None:
            while not stop.wait(_HEARTBEAT_INTERVAL_SECONDS):
                try:
                    self._collection().update_one(
                        {"_id": self.LOCK_DOCUMENT_ID},
                        {"$set": {"acquired_at": datetime.now(timezone.utc).isoformat()}},
                    )
                except Exception as exc:  # best-effort refresh; next tick retries
                    self.log.warning(f"Failed to refresh migration lock lease: {exc}")

        self._heartbeat_thread = threading.Thread(target=_refresh, daemon=True)
        self._heartbeat_thread.start()

    def _stop_heartbeat(self) -> None:
        if self._heartbeat_stop is not None:
            self._heartbeat_stop.set()
        if self._heartbeat_thread is not None:
            self._heartbeat_thread.join(timeout=1)
        self._heartbeat_thread = None
        self._heartbeat_stop = None

    def create_migration_lock_container_if_not_exists(self, schema: str) -> None:
        """Create the lock collection if it is missing. Idempotent.

        The index on ``_id`` already exists and is already unique, so the
        call below is about materialising the collection: MongoDB creates a
        collection lazily, and an index build is the cheapest way to force
        it without writing a document that would look like a held lease.
        """
        from dblift.db.plugins.mongodb.mongodb._sdk import ASCENDING_ORDER

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
        from dblift.db.plugins.mongodb.mongodb._sdk import DuplicateKeyError

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
                self._start_heartbeat()
                return True

            existing = self._collection().find_one({"_id": self.LOCK_DOCUMENT_ID})
            if self._is_expired(existing):
                self.log.warning("Reclaiming an expired migration lock lease")
                if existing is not None:
                    result = self._collection().delete_one(
                        {"_id": self.LOCK_DOCUMENT_ID, "acquired_at": existing.get("acquired_at")}
                    )
                    if result.deleted_count > 0 and self._try_insert_lease():
                        self._start_heartbeat()
                        return True
                else:
                    # No lease document exists, try to acquire it
                    if self._try_insert_lease():
                        self._start_heartbeat()
                        return True

            if time.monotonic() >= deadline:
                self.log.warning(f"Could not acquire migration lock within {wait_timeout_seconds}s")
                return False
            time.sleep(_POLL_INTERVAL_SECONDS)

    def release_migration_lock(self, schema: str) -> bool:
        """Release the lease; ``True`` when one was removed."""
        self._stop_heartbeat()
        result = self._collection().delete_one({"_id": self.LOCK_DOCUMENT_ID})
        released = int(result.deleted_count) > 0
        if released:
            self.log.debug("Released migration lock")
        return released
