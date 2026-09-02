"""``MongoDbSnapshotManager`` — snapshot storage created through pymongo."""

from unittest.mock import MagicMock

import pytest

from dblift.core.constants import DBLIFT_SCHEMA_SNAPSHOTS_TABLE
from dblift.db.plugins.mongodb.mongodb import MongoDbSnapshotManager


def _manager():
    provider = MagicMock()
    provider.schema_operations = MagicMock()
    return MongoDbSnapshotManager(provider), provider


def test_creates_the_collection():
    manager, provider = _manager()
    manager.create_snapshot_collection("dblift_schema_snapshots")
    provider.schema_operations.create_collection_if_not_exists.assert_called_once_with(
        "dblift_schema_snapshots"
    )


def test_provider_entry_point_resolves_the_default_name():
    manager, provider = _manager()
    manager.create_snapshot_table_if_not_exists("ignored")
    provider.schema_operations.create_collection_if_not_exists.assert_called_once_with(
        DBLIFT_SCHEMA_SNAPSHOTS_TABLE
    )


def test_no_retry_wrapper():
    """MongoDB has no warmup-503 problem, so a failure surfaces immediately
    instead of being retried five times."""
    manager, provider = _manager()
    provider.schema_operations.create_collection_if_not_exists.side_effect = RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        manager.create_snapshot_collection("dblift_schema_snapshots")

    assert provider.schema_operations.create_collection_if_not_exists.call_count == 1
