"""A MongoDB lease holder only ever releases its own lease.

A holder paused longer than the lease (GC, VM freeze) has its lease reclaimed
by another process. When it resumes, its release must not delete the new
holder's lease document, or a third process can take the lock while the
second is still migrating.
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

pytest.importorskip("pymongo")
from pymongo.errors import DuplicateKeyError  # noqa: E402

from dblift.db.plugins import lease_lock  # noqa: E402
from dblift.db.plugins.mongodb.mongodb import MongoDbLockingManager  # noqa: E402


class _Collection:
    """Equality-filter subset of a pymongo collection, enough for the lease."""

    def __init__(self) -> None:
        self.docs: dict = {}

    @staticmethod
    def _match(doc: dict, flt: dict) -> bool:
        return all(doc.get(key) == value for key, value in flt.items())

    def insert_one(self, doc: dict):
        if doc["_id"] in self.docs:
            raise DuplicateKeyError("duplicate key")
        self.docs[doc["_id"]] = dict(doc)
        return SimpleNamespace(inserted_id=doc["_id"])

    def find_one(self, flt: dict):
        for doc in self.docs.values():
            if self._match(doc, flt):
                return dict(doc)
        return None

    def delete_one(self, flt: dict):
        for key, doc in list(self.docs.items()):
            if self._match(doc, flt):
                del self.docs[key]
                return SimpleNamespace(deleted_count=1)
        return SimpleNamespace(deleted_count=0)

    def update_one(self, flt: dict, update: dict):
        for doc in self.docs.values():
            if self._match(doc, flt):
                doc.update(update.get("$set", {}))
                return SimpleNamespace(matched_count=1, modified_count=1)
        return SimpleNamespace(matched_count=0, modified_count=0)

    def create_index(self, *_args, **_kwargs):
        return "_id_"


def _manager(collection: _Collection, log=None) -> MongoDbLockingManager:
    executor = MagicMock()
    executor.connection_manager.get_collection.return_value = collection
    return MongoDbLockingManager(executor, log=log)


def test_stale_holder_release_leaves_the_successors_lease_in_place():
    collection = _Collection()
    stale, successor = _manager(collection), _manager(collection)

    assert stale.acquire_migration_lock("db", wait_timeout_seconds=1) is True
    lease = collection.docs["migration_lock"]
    lease["acquired_at"] = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()

    assert successor.acquire_migration_lock("db", wait_timeout_seconds=2) is True
    successors_lease = dict(collection.docs["migration_lock"])

    try:
        assert stale.release_migration_lock("db") is False
        assert collection.docs.get("migration_lock") == successors_lease
    finally:
        assert successor.release_migration_lock("db") is True
    assert collection.docs == {}


def test_live_holder_is_not_reclaimed(monkeypatch):
    monkeypatch.setattr(lease_lock, "POLL_INTERVAL_SECONDS", 0.05)
    collection = _Collection()
    holder, waiter = _manager(collection), _manager(collection)

    assert holder.acquire_migration_lock("db", wait_timeout_seconds=1) is True
    holders_lease = dict(collection.docs["migration_lock"])
    try:
        assert waiter.acquire_migration_lock("db", wait_timeout_seconds=1) is False
        assert collection.docs["migration_lock"]["owner_token"] == holders_lease["owner_token"]
    finally:
        assert holder.release_migration_lock("db") is True


def test_stale_holders_heartbeat_does_not_renew_the_successors_lease(monkeypatch):
    monkeypatch.setattr(lease_lock, "POLL_INTERVAL_SECONDS", 0.05)
    collection = _Collection()
    stale, successor = _manager(collection), _manager(collection)

    # The stale holder's first beat is due 1 s after it acquires: long
    # enough for the successor to take over first, as after a pause.
    monkeypatch.setattr(lease_lock, "LEASE_EXPIRY_SECONDS", 3.0)
    assert stale.acquire_migration_lock("db", wait_timeout_seconds=1) is True
    monkeypatch.setattr(lease_lock, "LEASE_EXPIRY_SECONDS", 0.3)
    collection.docs["migration_lock"]["acquired_at"] = (
        datetime.now(timezone.utc) - timedelta(hours=1)
    ).isoformat()
    assert successor.acquire_migration_lock("db", wait_timeout_seconds=1) is True
    try:
        time.sleep(1.3)  # the stale holder's first beat has run
        assert stale.migration_lock_lost() is True
    finally:
        stale.release_migration_lock("db")
        assert successor.release_migration_lock("db") is True


def test_normal_hand_off_is_not_reported_as_a_reclaim(monkeypatch):
    monkeypatch.setattr(lease_lock, "POLL_INTERVAL_SECONDS", 0.05)
    collection = _Collection()
    log = MagicMock()
    first, second = _manager(collection), _manager(collection, log=log)

    assert first.acquire_migration_lock("db", wait_timeout_seconds=1) is True
    assert first.release_migration_lock("db") is True
    assert second.acquire_migration_lock("db", wait_timeout_seconds=1) is True
    second.release_migration_lock("db")

    warnings = [str(call.args[0]) for call in log.warning.call_args_list]
    assert not [w for w in warnings if "reclaim" in w.lower()], warnings


def test_provider_close_releases_a_held_lease():
    from dblift.db.plugins.mongodb.provider import MongoDbProvider

    collection = _Collection()
    provider = MongoDbProvider.__new__(MongoDbProvider)
    provider.locking_manager = _manager(collection)
    provider.connection_manager = MagicMock()
    assert provider.locking_manager.acquire_migration_lock("db", wait_timeout_seconds=1) is True

    provider.close()

    assert collection.docs == {}
