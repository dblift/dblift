"""``CosmosDbSnapshotManager`` — provisioning moved off the provider.

Behavior is unchanged from the provider method it replaces: create the
container partitioned on ``/snapshot_id``, retrying transient emulator
failures with exponential backoff.
"""

from unittest.mock import MagicMock

import pytest

from dblift.db.plugins.cosmosdb.cosmosdb import CosmosDbSnapshotManager


def _provider():
    provider = MagicMock()
    provider.schema_operations = MagicMock()
    return provider


def test_creates_container_partitioned_on_snapshot_id():
    provider = _provider()
    CosmosDbSnapshotManager(provider).create_snapshot_collection("dblift_schema_snapshots")
    provider.schema_operations.create_container_if_not_exists.assert_called_once_with(
        "dblift_schema_snapshots", partition_key="/snapshot_id"
    )


def test_retries_transient_failure_then_succeeds(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda _seconds: None)
    provider = _provider()
    provider.schema_operations.create_container_if_not_exists.side_effect = [
        Exception("ServiceUnavailable (503)"),
        None,
    ]
    CosmosDbSnapshotManager(provider).create_snapshot_collection("dblift_schema_snapshots")
    assert provider.schema_operations.create_container_if_not_exists.call_count == 2


def test_non_transient_failure_is_not_retried():
    provider = _provider()
    provider.schema_operations.create_container_if_not_exists.side_effect = Exception("Forbidden")
    with pytest.raises(RuntimeError, match="Failed to create snapshot container"):
        CosmosDbSnapshotManager(provider).create_snapshot_collection("dblift_schema_snapshots")
    assert provider.schema_operations.create_container_if_not_exists.call_count == 1


def test_provider_still_exposes_the_entry_point():
    """The provider API must not move — callers reach provisioning through
    ``provider.create_snapshot_table_if_not_exists``."""
    from dblift.db.plugins.cosmosdb.provider import CosmosDbProvider

    assert hasattr(CosmosDbProvider, "create_snapshot_table_if_not_exists")
