"""Migration lock held as a lease: expiry, heartbeat, reclaim and ownership.

A ``migrate`` releases its lock in a ``finally`` block, which a process killed
with SIGKILL (or with SIGTERM while dblift runs embedded in another program)
never reaches. On engines whose lock is a committed row or document, that
lock would stay held forever. A lease fixes this without guessing how long a
migration may run: the holder refreshes the lease on a short timer, so a live
holder never lets it go stale, while a dead holder's lease expires within one
lease window and is reclaimed by the next process that waits for it.

The engine-specific part is a :class:`LeaseStore` (one row or document); the
acquire loop, the heartbeat and the ownership rules live in :class:`LeaseLock`
and are the same for every engine.
"""

from __future__ import annotations

import atexit
import threading
import time
import uuid
import weakref
from abc import ABC, abstractmethod
from typing import Optional

from dblift.core.logger import Log, NullLog

#: How long a lease stays valid without a refresh before another process may
#: reclaim it. Deliberately short: a live holder renews well before this
#: elapses, so the expiry only ever fires for a holder that has stopped.
LEASE_EXPIRY_SECONDS: float = 30

#: Gap between acquisition attempts while another process holds the lease.
POLL_INTERVAL_SECONDS: float = 1.0

#: Age after which a lock row written by a dblift version without the lease
#: (no owner) is reclaimable. Such a holder never refreshes its row, so it
#: cannot be told apart from a dead one sooner without risking a live run.
LEGACY_LEASE_EXPIRY_SECONDS: float = 24 * 60 * 60

# Leases still held, released at interpreter exit. Weak so a lease that is
# garbage-collected unreleased is simply left to expire.
_HELD_LEASES: "weakref.WeakSet[LeaseLock]" = weakref.WeakSet()
_atexit_lock = threading.Lock()
_atexit_registered = False


def _heartbeat_interval() -> float:
    """A third of the expiry: two missed beats of slack before the lease looks stale."""
    return LEASE_EXPIRY_SECONDS / 3


def _busy_retry_delay() -> float:
    """Pause before renewing again after a busy store: a tenth of a poll."""
    return POLL_INTERVAL_SECONDS / 10


def _release_held_leases() -> None:
    """Release every lease still held when the interpreter exits."""
    for lease in list(_HELD_LEASES):
        lease.release()


def _register_atexit() -> None:
    global _atexit_registered
    with _atexit_lock:
        if not _atexit_registered:
            atexit.register(_release_held_leases)
            _atexit_registered = True


class LeaseBusy(Exception):
    """The store is momentarily write-locked or in conflict.

    Some writer holds the store right now, which is evidence that a lock
    holder is alive (SQLite: the holder's own long write transaction also
    blocks its heartbeat). A waiter does not reclaim while it sees this.
    """


class LeaseStore(ABC):
    """One lease slot in a database: a lock row or a lock document.

    Every method is a single atomic statement against the store; whether a
    call changed anything is the whole answer. ``LeaseBusy`` reports a store
    that is momentarily write-locked; any other exception is unexpected.
    """

    @abstractmethod
    def try_acquire(self, token: str) -> bool:
        """Take the lease for *token* when it is free; ``False`` when held."""

    @abstractmethod
    def reclaim_expired(self, expiry_seconds: float) -> bool:
        """Free a lease not refreshed for *expiry_seconds*; ``True`` when freed."""

    @abstractmethod
    def refresh(self, token: str) -> bool:
        """Renew the lease held by *token*; ``False`` when *token* no longer holds it."""

    @abstractmethod
    def release(self, token: str) -> bool:
        """Free the lease held by *token*; ``False`` when *token* did not hold it."""

    def close(self) -> None:
        """Release the store's resources (its dedicated connection, if any)."""


class LeaseLock:
    """A migration lock held as a lease in a :class:`LeaseStore`.

    Each acquisition gets a fresh owner token. Refresh and release only act
    on the caller's own token, so a holder whose lease was reclaimed (it was
    paused longer than the lease) can neither renew nor delete its
    successor's lease. While held, a daemon thread refreshes the lease; when
    a refresh finds the lease gone, or no refresh lands for a whole lease
    window, the lease is reported :attr:`lost`.

    No signal handlers are installed: dblift may run inside another program.
    A lease still held at interpreter exit is released by ``atexit``; one
    held by a killed process expires.
    """

    def __init__(
        self, store: LeaseStore, log: Optional[Log] = None, heartbeat: bool = True
    ) -> None:
        """Wrap *store*; ``heartbeat=False`` for a store nobody else can reach
        (a private in-memory database), where the lease can never be contended."""
        self._store = store
        self.log: Log = log if log is not None else NullLog()
        self._heartbeat_enabled = heartbeat
        self.token: Optional[str] = None
        self._held = False
        self._lost = False
        self._stop: Optional[threading.Event] = None
        self._thread: Optional[threading.Thread] = None

    @property
    def lost(self) -> bool:
        """Whether the held lease was reclaimed or could not be renewed in time."""
        return self._lost

    def acquire(self, wait_timeout_seconds: float) -> bool:
        """Take the lease, waiting up to *wait_timeout_seconds*.

        A held lease is reclaimed only once the store reports it expired and
        no busy store was seen for a whole lease window, and never on the
        first attempt: a holder whose heartbeat was blocked (SQLite: its own
        long write transaction) renews within a fraction of a poll interval
        once unblocked, and a waiter that was blocked by the same transaction
        first reaches the lock table just as it ends. A failed acquire closes
        the store.
        """
        self.token = uuid.uuid4().hex
        deadline = time.monotonic() + max(wait_timeout_seconds, 0)
        last_busy: Optional[float] = None
        first_attempt = True
        while True:
            acquired = False
            try:
                if not first_attempt and self._may_reclaim(last_busy):
                    expiry = LEASE_EXPIRY_SECONDS
                    if self._store.reclaim_expired(expiry):
                        self.log.warning(
                            f"Reclaimed a migration lock not refreshed for {expiry:g} seconds; "
                            "its holder is presumed dead"
                        )
                first_attempt = False
                acquired = self._store.try_acquire(self.token)
            except LeaseBusy:
                last_busy = time.monotonic()
            except Exception:
                self._store.close()
                raise
            if acquired:
                self._on_acquired()
                return True
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                self._store.close()
                return False
            time.sleep(min(POLL_INTERVAL_SECONDS, remaining))

    @staticmethod
    def _may_reclaim(last_busy: Optional[float]) -> bool:
        return last_busy is None or time.monotonic() - last_busy >= LEASE_EXPIRY_SECONDS

    def _on_acquired(self) -> None:
        self._held = True
        self._lost = False
        _register_atexit()
        _HELD_LEASES.add(self)
        if self._heartbeat_enabled:
            stop = threading.Event()
            self._stop = stop
            self._thread = threading.Thread(
                target=self._heartbeat, args=(stop,), name="dblift-lock-heartbeat", daemon=True
            )
            self._thread.start()

    def _heartbeat(self, stop: threading.Event) -> None:
        """Renew the lease until stopped or lost."""
        last_alive = time.monotonic()
        delay = _heartbeat_interval()
        while not stop.wait(delay):
            delay = _heartbeat_interval()
            try:
                if self._store.refresh(self.token or ""):
                    last_alive = time.monotonic()
                    continue
                self.log.error(
                    "The migration lock was taken over by another process; "
                    "no further migration will start"
                )
                self._lost = True
                return
            except LeaseBusy:
                # Our own writer (or another one) holds the store: the lease
                # is not lost, it just cannot be renewed this beat. Retry
                # soon, so it is renewed as soon as the store is free again.
                last_alive = time.monotonic()
                delay = _busy_retry_delay()
            except Exception as exc:
                self.log.warning(f"Failed to refresh the migration lock: {exc}")
                if time.monotonic() - last_alive >= LEASE_EXPIRY_SECONDS:
                    self.log.error(
                        "The migration lock could not be refreshed for a whole lease window "
                        "and may have been taken over; no further migration will start"
                    )
                    self._lost = True
                    return

    def _stop_heartbeat(self) -> None:
        if self._stop is not None:
            self._stop.set()
        if self._thread is not None and self._thread is not threading.current_thread():
            self._thread.join(timeout=5)
        self._stop = None
        self._thread = None

    def release(self) -> bool:
        """Release the lease; ``True`` when this holder's lease was removed.

        A lease that was reclaimed by another process is left in place and
        ``False`` is returned. The store is closed either way.
        """
        if not self._held:
            return False
        self._held = False
        _HELD_LEASES.discard(self)
        self._stop_heartbeat()
        try:
            return self._store.release(self.token or "")
        except Exception as exc:
            self.log.warning(f"Could not release the migration lock: {exc}")
            return False
        finally:
            self._store.close()


__all__ = [
    "LEASE_EXPIRY_SECONDS",
    "LEGACY_LEASE_EXPIRY_SECONDS",
    "POLL_INTERVAL_SECONDS",
    "LeaseBusy",
    "LeaseLock",
    "LeaseStore",
]
