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
    lease = _lease(age_seconds=10_000)
    collection.find_one.return_value = lease
    collection.delete_one.return_value = MagicMock(deleted_count=1)

    assert manager.acquire_migration_lock("ignored", wait_timeout_seconds=1) is True
    collection.delete_one.assert_called_once_with(
        {"_id": "migration_lock", "acquired_at": lease["acquired_at"]}
    )


def test_release_reports_removal():
    manager, collection = _manager()
    collection.delete_one.return_value = MagicMock(deleted_count=1)
    assert manager.release_migration_lock("ignored") is True


def test_releasing_an_absent_lock_is_not_an_error():
    """A repair or a previous crash may already have cleared it."""
    manager, collection = _manager()
    collection.delete_one.return_value = MagicMock(deleted_count=0)
    assert manager.release_migration_lock("ignored") is False


def test_expired_lease_race_another_process_reclaims_first(monkeypatch):
    """When two processes both see an expired lease, only the one whose
    delete filter matches (acquired_at match) should proceed to insert.
    If another process reclaims first, this process's delete finds no match
    and correctly retries rather than inserting on top of the new lease."""
    monkeypatch.setattr("time.sleep", lambda _seconds: None)
    manager, collection = _manager()
    stale_lease = _lease(age_seconds=10_000)
    fresh_lease = _lease(age_seconds=1)

    # Simulate the race: both processes see the stale lease, but only one
    # can delete it. The other's delete filter (with the old acquired_at)
    # won't match because the document was already deleted and re-inserted.
    collection.insert_one.side_effect = [
        DuplicateKeyError("duplicate"),  # First insert attempt fails (lease held)
    ]
    collection.find_one.side_effect = [
        stale_lease,  # First find sees the stale lease
        fresh_lease,  # After delete fails, find sees the fresh lease (another process won)
    ]
    collection.delete_one.return_value = MagicMock(deleted_count=0)  # Delete fails (acquired_at mismatch)

    # Should timeout waiting for the fresh lease, not insert on top of it
    assert manager.acquire_migration_lock("ignored", wait_timeout_seconds=0) is False
    # Verify delete was attempted with the stale acquired_at
    collection.delete_one.assert_called_once_with(
        {"_id": "migration_lock", "acquired_at": stale_lease["acquired_at"]}
    )
    # Verify insert was NOT called after the failed delete
    collection.insert_one.assert_called_once()  # Only the initial attempt


def test_container_creation_adds_the_unique_index():
    manager, collection = _manager()
    manager.create_migration_lock_container_if_not_exists("ignored")
    collection.create_index.assert_called_once()
