"""Concurrency lock held as a lease document."""

from abc import ABC, abstractmethod
from typing import Any, Optional

from dblift.core.logger import Log, NullLog


class DocumentLockingManager(ABC):
    """Guards concurrent migration runs with a lease document.

    Relational plugins take the lock with a row plus the engine's own
    locking primitives (``SELECT ... FOR UPDATE``, advisory locks). A
    document store has neither, so the lock is a single document whose
    creation is made to fail when it already exists — Cosmos DB uses
    ``create_item`` (which raises on a duplicate ``id``), MongoDB would
    use ``findOneAndUpdate`` with ``upsert`` on a unique key. Both give
    the same guarantee: exactly one writer wins the create, everyone else
    waits or gives up.

    Implementations own lease expiry too. A holder that dies must not
    block the collection forever, so a stale lease — one older than the
    configured timeout — is reclaimable.
    """

    #: Collection/container holding the lease document.
    LOCK_CONTAINER_NAME: str = "dblift_migration_lock"

    def __init__(self, query_executor: Any, log: Optional[Log] = None) -> None:
        """Store the executor (for its connection manager) and the logger."""
        self.query_executor = query_executor
        #: Typed ``Any`` deliberately — each SDK exposes a different
        #: connection-manager shape, and the contract here does not
        #: constrain it.
        self.connection_manager: Any = getattr(query_executor, "connection_manager", None)
        self.log: Log = log if log is not None else NullLog()

    @abstractmethod
    def create_migration_lock_container_if_not_exists(self, schema: str) -> None:
        """Create the lock collection if it is missing. Idempotent."""

    @abstractmethod
    def acquire_migration_lock(self, schema: str, wait_timeout_seconds: int = 60) -> bool:
        """Take the lock, waiting up to *wait_timeout_seconds*.

        Returns ``True`` when the lease is held by this process, ``False``
        when the wait elapsed with another holder still active. Reclaiming
        an expired lease counts as acquiring it.
        """

    @abstractmethod
    def release_migration_lock(self, schema: str) -> bool:
        """Release a lease this process holds; ``True`` when one was removed.

        Releasing a lock that is already gone is not an error — a repair
        or a previous crash may have cleared it — and returns ``False``.
        """
