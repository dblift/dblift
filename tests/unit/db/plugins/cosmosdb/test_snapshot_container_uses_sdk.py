"""Snapshot storage on Cosmos must be created through the SDK.

``BaseSnapshotManager`` renders ``CREATE TABLE dblift_schema_snapshots
(...)`` and sends it to ``provider.execute_statement``. On Cosmos that only
ever worked because the pseudo-SQL emulator recognised ``CREATE TABLE`` and
turned it into a container create. With the emulator deleted the statement
raises ``NoSqlWriteNotSupportedError``, which would have broken snapshot
persistence on the first ``migrate`` against a fresh account — silently, as
far as the unit suite was concerned, because nothing mocked that path.
"""

from unittest.mock import MagicMock

import pytest

from dblift.core.exceptions import NoSqlWriteNotSupportedError
from dblift.db.plugins.cosmosdb.provider import CosmosDbProvider


def _provider() -> CosmosDbProvider:
    provider = CosmosDbProvider.__new__(CosmosDbProvider)
    provider.schema_operations = MagicMock()
    provider.query_executor = MagicMock()
    provider.log = MagicMock()
    return provider


def test_snapshot_container_is_created_through_the_sdk():
    provider = _provider()

    provider.create_snapshot_table_if_not_exists("default")

    provider.schema_operations.create_container_if_not_exists.assert_called_once()
    name, kwargs = (
        provider.schema_operations.create_container_if_not_exists.call_args.args[0],
        provider.schema_operations.create_container_if_not_exists.call_args.kwargs,
    )
    assert name == "dblift_schema_snapshots"
    assert kwargs["partition_key"] == "/snapshot_id"


def test_snapshot_creation_never_reaches_the_query_executor():
    """No CREATE TABLE may be handed to Cosmos, which would now raise."""
    provider = _provider()

    provider.create_snapshot_table_if_not_exists("default", "custom_snapshots")

    provider.query_executor.execute_statement.assert_not_called()
    assert (
        provider.schema_operations.create_container_if_not_exists.call_args.args[0]
        == "custom_snapshots"
    )


def test_transient_503_is_retried_then_surfaced():
    provider = _provider()
    provider.schema_operations.create_container_if_not_exists.side_effect = RuntimeError(
        "ServiceUnavailable (503)"
    )

    with pytest.raises(RuntimeError, match="Failed to create snapshot container"):
        provider.create_snapshot_table_if_not_exists("default")

    assert provider.schema_operations.create_container_if_not_exists.call_count > 1


def test_a_write_statement_would_indeed_have_failed():
    """Pins why the override exists: execute_statement rejects DDL now."""
    from dblift.db.plugins.cosmosdb.cosmosdb.query_executor import CosmosDbQueryExecutor

    executor = CosmosDbQueryExecutor.__new__(CosmosDbQueryExecutor)
    executor.log = MagicMock()

    with pytest.raises(NoSqlWriteNotSupportedError):
        executor.execute_statement(None, "CREATE TABLE dblift_schema_snapshots (id VARCHAR(64))")
