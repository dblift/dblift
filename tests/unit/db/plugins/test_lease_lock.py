"""Shared migration-lock lease: expiry, heartbeat, reclaim and ownership.

The store here is an in-memory stand-in for the lock table (or document): one
lease slot whose "server clock" is ``time.monotonic``. The engine-specific
stores are covered against real databases and recorded SQL elsewhere; this file
pins the engine-independent rules every store relies on.
"""

from __future__ import annotations

import signal
import threading
import time
from types import SimpleNamespace

import pytest

from dblift.db.plugins import lease_lock
from dblift.db.plugins.lease_lock import LeaseBusy, LeaseLock, LeaseStore

EXPIRY = 0.6


@pytest.fixture(autouse=True)
def _short_lease(monkeypatch):
    monkeypatch.setattr(lease_lock, "LEASE_EXPIRY_SECONDS", EXPIRY)
    monkeypatch.setattr(lease_lock, "POLL_INTERVAL_SECONDS", 0.05)


class _MemoryStore(LeaseStore):
    """One lease slot shared by every store built on the same ``slot``."""

    def __init__(self, slot: SimpleNamespace) -> None:
        self.slot = slot
        self.closed = False
        self.refresh_calls = 0

    def _busy(self) -> None:
        if time.monotonic() < self.slot.busy_until:
            raise LeaseBusy("store write-locked by another writer")

    def try_acquire(self, token: str) -> bool:
        self._busy()
        with self.slot.mutex:
            if self.slot.owner is None:
                self.slot.owner, self.slot.ts = token, time.monotonic()
                return True
            return False

    def reclaim_expired(self, expiry_seconds: float) -> bool:
        self._busy()
        with self.slot.mutex:
            if self.slot.owner is not None and time.monotonic() - self.slot.ts > expiry_seconds:
                self.slot.owner = None
                return True
            return False

    def refresh(self, token: str) -> bool:
        self.refresh_calls += 1
        if token in self.slot.unreachable:
            raise ConnectionError("connection lost")
        if token in self.slot.busy_tokens:
            raise LeaseBusy("holder's own write transaction is open")
        with self.slot.mutex:
            if self.slot.owner == token:
                self.slot.ts = time.monotonic()
                return True
            return False

    def release(self, token: str) -> bool:
        with self.slot.mutex:
            if self.slot.owner == token:
                self.slot.owner = None
                return True
            return False

    def close(self) -> None:
        self.closed = True


def _slot(owner=None, age=0.0):
    return SimpleNamespace(
        mutex=threading.Lock(),
        owner=owner,
        ts=time.monotonic() - age,
        busy_until=0.0,
        busy_tokens=set(),
        unreachable=set(),
    )


def _lock(slot):
    return LeaseLock(_MemoryStore(slot), log=None)


def test_live_holder_is_never_reclaimed_while_its_heartbeat_runs():
    slot = _slot()
    holder = _lock(slot)
    assert holder.acquire(wait_timeout_seconds=1) is True

    waiter = _lock(slot)
    assert waiter.acquire(wait_timeout_seconds=EXPIRY * 4) is False

    assert slot.owner == holder.token
    assert holder.release() is True


def test_dead_holder_is_reclaimed_after_one_expiry():
    slot = _slot(owner="dead-holder-token")
    waiter = _lock(slot)

    started = time.monotonic()
    assert waiter.acquire(wait_timeout_seconds=EXPIRY * 5) is True
    elapsed = time.monotonic() - started

    assert slot.owner == waiter.token
    assert elapsed >= EXPIRY * 0.8
    assert elapsed < EXPIRY * 4
    assert waiter.release() is True


def test_stale_holder_cannot_release_the_lease_that_replaced_it():
    slot = _slot()
    stale = _lock(slot)
    assert stale.acquire(wait_timeout_seconds=1) is True
    slot.unreachable.add(stale.token)  # partitioned: its heartbeat cannot land

    successor = _lock(slot)
    assert successor.acquire(wait_timeout_seconds=EXPIRY * 5) is True

    assert stale.release() is False
    assert slot.owner == successor.token
    assert successor.release() is True


def test_heartbeat_that_cannot_land_for_a_whole_expiry_marks_the_lease_lost():
    slot = _slot()
    holder = _lock(slot)
    assert holder.acquire(wait_timeout_seconds=1) is True
    assert holder.lost is False

    slot.unreachable.add(holder.token)
    time.sleep(EXPIRY * 2)

    assert holder.lost is True
    holder.release()


def test_heartbeat_detects_a_reclaimed_lease():
    slot = _slot()
    holder = _lock(slot)
    assert holder.acquire(wait_timeout_seconds=1) is True

    with slot.mutex:
        slot.owner = "someone-else"
    time.sleep(EXPIRY)

    assert holder.lost is True
    assert holder.release() is False
    assert slot.owner == "someone-else"


def test_busy_store_counts_as_a_live_holder_and_delays_reclaim():
    """A store that is write-locked proves some writer is alive (SQLite: the
    holder's own long transaction blocks its heartbeat). The stale timestamp
    must not be reclaimed until a full expiry has passed without that evidence."""
    slot = _slot(owner="holder-in-long-transaction", age=EXPIRY * 10)
    busy_for = EXPIRY * 2
    slot.busy_until = time.monotonic() + busy_for

    waiter = _lock(slot)
    assert waiter.acquire(wait_timeout_seconds=EXPIRY * 8) is True
    acquired_at = time.monotonic()

    assert acquired_at >= slot.busy_until + EXPIRY * 0.8
    waiter.release()


def test_busy_heartbeat_failures_do_not_mark_the_lease_lost():
    slot = _slot()
    holder = _lock(slot)
    assert holder.acquire(wait_timeout_seconds=1) is True

    slot.busy_tokens.add(holder.token)
    time.sleep(EXPIRY * 3)
    assert holder.lost is False

    slot.busy_tokens.discard(holder.token)
    time.sleep(EXPIRY)
    assert holder.lost is False
    assert holder.release() is True


def test_concurrent_acquirers_have_exactly_one_winner():
    slot = _slot()
    barrier = threading.Barrier(8)
    wins = []

    def contend():
        lock = _lock(slot)
        barrier.wait()
        if lock.acquire(wait_timeout_seconds=0.2):
            wins.append(lock)

    threads = [threading.Thread(target=contend) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(wins) == 1
    wins[0].release()


def test_concurrent_reclaimers_have_exactly_one_winner():
    slot = _slot(owner="dead-holder-token", age=EXPIRY * 10)
    barrier = threading.Barrier(8)
    wins = []

    def contend():
        lock = _lock(slot)
        barrier.wait()
        if lock.acquire(wait_timeout_seconds=0.3):
            wins.append(lock)

    threads = [threading.Thread(target=contend) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(wins) == 1
    assert slot.owner == wins[0].token
    wins[0].release()


def test_each_acquisition_gets_its_own_owner_token():
    slot = _slot()
    first = _lock(slot)
    second = _lock(slot)
    assert first.acquire(wait_timeout_seconds=1) is True
    first.release()
    assert second.acquire(wait_timeout_seconds=1) is True
    second.release()
    assert first.token != second.token


def test_release_stops_the_heartbeat_and_closes_the_store():
    slot = _slot()
    store = _MemoryStore(slot)
    holder = LeaseLock(store, log=None)
    assert holder.acquire(wait_timeout_seconds=1) is True
    time.sleep(EXPIRY / 2)
    assert store.refresh_calls >= 1

    assert holder.release() is True
    calls = store.refresh_calls
    time.sleep(EXPIRY)

    assert store.refresh_calls == calls
    assert store.closed is True


def test_failed_acquire_closes_the_store():
    slot = _slot(owner="live-holder")
    slot.ts = time.monotonic() + 3600  # never expires within the test
    store = _MemoryStore(slot)
    assert LeaseLock(store, log=None).acquire(wait_timeout_seconds=0.1) is False
    assert store.closed is True


def test_lease_installs_no_signal_handlers():
    before = {sig: signal.getsignal(sig) for sig in (signal.SIGINT, signal.SIGTERM)}
    slot = _slot()
    holder = _lock(slot)
    assert holder.acquire(wait_timeout_seconds=1) is True
    during = {sig: signal.getsignal(sig) for sig in before}
    holder.release()
    after = {sig: signal.getsignal(sig) for sig in before}

    assert during == before
    assert after == before


def test_holder_renews_as_soon_as_its_busy_store_frees_up():
    """SQLite: the holder's own long write transaction blocks its heartbeat
    past the expiry, and a waiter that was blocked by the same transaction
    reaches the lock only when it ends, without having seen the store busy.
    The holder must renew before that waiter is allowed to reclaim."""
    slot = _slot()
    holder = _lock(slot)
    assert holder.acquire(wait_timeout_seconds=1) is True
    slot.busy_tokens.add(holder.token)
    time.sleep(EXPIRY * 1.5)  # the stored timestamp is now stale

    slot.busy_tokens.discard(holder.token)
    waiter = _lock(slot)
    assert waiter.acquire(wait_timeout_seconds=EXPIRY) is False

    assert slot.owner == holder.token
    assert holder.lost is False
    assert holder.release() is True
