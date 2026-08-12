"""``MongoDbLockingManager`` — one lease document, exactly one winner.

The lease is taken with an insert on a fixed ``_id``: MongoDB raises
DuplicateKeyError for the losers, which is the mutual exclusion. An expired
lease is reclaimable so a dead holder cannot block the collection forever.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

from pymongo.errors import DuplicateKeyError

from db.plugins.mongodb.mongodb import MongoDbLockingManager


def _manager():
    query_executor = MagicMock()
    collection = MagicMock()
    query_executor.connection_manager.get_collection.return_value = collection
    return MongoDbLockingManager(query_executor), collection


def _lease(age_seconds):
    return {
        "_id": "migration_lock",
        "acquired_at": (
            datetime.now(timezone.utc) - timedelta(seconds=age_seconds)
        ).isoformat(),
    }


def test_lock_names():
    manager, _ = _manager()
    assert manager.LOCK_CONTAINER_NAME == "dblift_migration_lock"
    assert manager.LOCK_DOCUMENT_ID == "migration_lock"


def test_uncontended_acquire_succeeds():
    manager, collection = _manager()
    assert manager.acquire_migration_lock("ignored", wait_timeout_seconds=1) is True
    collection.insert_one.assert_called_once()
    assert collection.insert_one.call_args.args[0]["_id"] == "migration_lock"


def test_contended_acquire_gives_up_after_the_timeout(monkeypatch):
    """A live lease held by someone else means this process waits, then
    reports failure rather than proceeding unlocked."""
    monkeypatch.setattr("time.sleep", lambda _seconds: None)
    manager, collection = _manager()
    collection.insert_one.side_effect = DuplicateKeyError("duplicate")
    collection.find_one.return_value = _lease(age_seconds=1)

    assert manager.acquire_migration_lock("ignored", wait_timeout_seconds=0) is False


def test_expired_lease_is_reclaimed(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda _seconds: None)
    manager, collection = _manager()
    collection.insert_one.side_effect = [DuplicateKeyError("duplicate"), None]
    collection.find_one.return_value = _lease(age_seconds=10_000)

    assert manager.acquire_migration_lock("ignored", wait_timeout_seconds=1) is True
    collection.delete_one.assert_called_once_with({"_id": "migration_lock"})


def test_release_reports_removal():
    manager, collection = _manager()
    collection.delete_one.return_value = MagicMock(deleted_count=1)
    assert manager.release_migration_lock("ignored") is True


def test_releasing_an_absent_lock_is_not_an_error():
    """A repair or a previous crash may already have cleared it."""
    manager, collection = _manager()
    collection.delete_one.return_value = MagicMock(deleted_count=0)
    assert manager.release_migration_lock("ignored") is False


def test_container_creation_adds_the_unique_index():
    manager, collection = _manager()
    manager.create_migration_lock_container_if_not_exists("ignored")
    collection.create_index.assert_called_once()
