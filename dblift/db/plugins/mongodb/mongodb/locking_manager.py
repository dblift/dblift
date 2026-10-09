"""MongoDB migration lock, held as a lease document."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable, Optional

from dblift.core.constants import DEFAULT_MIGRATION_LOCK_TIMEOUT_SECONDS, MIGRATION_LOCK_TABLE
from dblift.core.logger import Log
from dblift.db.plugins import lease_lock
from dblift.db.plugins.lease_lock import LEASE_EXPIRY_SECONDS, LeaseLock, LeaseStore
from dblift.db.plugins.nosql_base import DocumentLockingManager

#: Document field holding the token of the process that holds the lease.
OWNER_FIELD = "owner_token"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class _MongoLeaseStore(LeaseStore):
    """The lease document, keyed by a fixed ``_id``.

    Timestamps come from the client clock: a clock skewed by more than the
    lease expiry against another runner can make a live lease look expired.
    """

    def __init__(self, collection: Callable[[], Any], document_id: str) -> None:
        self._collection = collection
        self._document_id = document_id

    def try_acquire(self, token: str) -> bool:
        """Insert the lease document; ``False`` when another process already holds it."""
        from dblift.db.plugins.mongodb.mongodb._sdk import DuplicateKeyError

        try:
            self._collection().insert_one(
                {"_id": self._document_id, "acquired_at": _now(), OWNER_FIELD: token}
            )
            return True
        except DuplicateKeyError:
            return False

    def reclaim_expired(self, expiry_seconds: float) -> bool:
        """Delete the lease document when it was not refreshed for *expiry_seconds*.

        The delete matches the timestamp read, so when two processes see the
        same expired lease only one deletes it; the other finds a fresh one.
        """
        existing = self._collection().find_one({"_id": self._document_id})
        if existing is None:
            return True
        if not MongoDbLockingManager._is_expired(existing, expiry_seconds):
            return False
        result = self._collection().delete_one(
            {"_id": self._document_id, "acquired_at": existing.get("acquired_at")}
        )
        return int(result.deleted_count) > 0

    def refresh(self, token: str) -> bool:
        """Renew the caller's lease document."""
        result = self._collection().update_one(
            {"_id": self._document_id, OWNER_FIELD: token}, {"$set": {"acquired_at": _now()}}
        )
        return int(result.matched_count) > 0

    def release(self, token: str) -> bool:
        """Delete the caller's lease document; another holder's is left in place."""
        result = self._collection().delete_one({"_id": self._document_id, OWNER_FIELD: token})
        return int(result.deleted_count) > 0


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
    The document carries the holder's token, so a holder whose lease was
    reclaimed can neither renew nor delete its successor's lease.
    """

    LOCK_CONTAINER_NAME = MIGRATION_LOCK_TABLE
    LOCK_DOCUMENT_ID = "migration_lock"

    def __init__(self, query_executor: Any, log: Optional[Log] = None) -> None:
        """Store the executor and the logger."""
        super().__init__(query_executor=query_executor, log=log)
        self._lease: Optional[LeaseLock] = None

    def _collection(self) -> Any:
        return self.query_executor.connection_manager.get_collection(self.LOCK_CONTAINER_NAME)

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
    def _is_expired(
        lease: Optional[dict[str, Any]], expiry_seconds: Optional[float] = None
    ) -> bool:
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
        limit = lease_lock.LEASE_EXPIRY_SECONDS if expiry_seconds is None else expiry_seconds
        return age > limit

    def acquire_migration_lock(
        self, schema: str, wait_timeout_seconds: int = DEFAULT_MIGRATION_LOCK_TIMEOUT_SECONDS
    ) -> bool:
        """Take the lease, waiting up to *wait_timeout_seconds*."""
        if self._lease is not None:
            return True
        lease = LeaseLock(_MongoLeaseStore(self._collection, self.LOCK_DOCUMENT_ID), log=self.log)
        if not lease.acquire(wait_timeout_seconds):
            self.log.warning(f"Could not acquire migration lock within {wait_timeout_seconds}s")
            return False
        self._lease = lease
        self.log.debug("Acquired migration lock")
        return True

    def release_migration_lock(self, schema: str) -> bool:
        """Release the lease; ``True`` when this process's lease was removed."""
        lease, self._lease = self._lease, None
        released = lease.release() if lease is not None else False
        if released:
            self.log.debug("Released migration lock")
        return released

    def migration_lock_lost(self) -> bool:
        """Whether the held lease was reclaimed or could not be renewed in time."""
        return self._lease is not None and self._lease.lost

    def close(self) -> None:
        """Release a lease still held (the provider is closing)."""
        self.release_migration_lock("")


__all__ = ["LEASE_EXPIRY_SECONDS", "MongoDbLockingManager"]
