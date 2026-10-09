"""A MongoDB lease holder only ever releases its own lease.

A holder paused longer than the lease (GC, VM freeze) has its lease reclaimed
by another process. When it resumes, its release must not delete the new
holder's lease document, or a third process can take the lock while the
second is still migrating.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

pytest.importorskip("pymongo")
from pymongo.errors import DuplicateKeyError  # noqa: E402

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


def _manager(collection: _Collection) -> MongoDbLockingManager:
    executor = MagicMock()
    executor.connection_manager.get_collection.return_value = collection
    return MongoDbLockingManager(executor)


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
