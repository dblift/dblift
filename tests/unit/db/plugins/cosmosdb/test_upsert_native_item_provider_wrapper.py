"""``CosmosDbProvider.upsert_native_item`` must be a thin forward to the
query executor, not a new SQL path.

Mirrors ``test_snapshot_container_uses_sdk.py``: that file pins the
container-*creation* seam that ADR-0032's pseudo-SQL removal ported to a
native SDK call (``create_snapshot_table_if_not_exists`` ->
``schema_operations.create_container_if_not_exists``). This file pins the
matching document-*write* seam the ADR missed --
``CosmosDbProvider.upsert_native_item`` forwarding to
``CosmosDbQueryExecutor.upsert_native_item``, which callers such as the
schema-snapshot repository use instead of routing an ``INSERT`` through
``execute_statement`` (which now raises ``NoSqlWriteNotSupportedError`` for
anything but a ``SELECT``).
"""

from unittest.mock import MagicMock

from dblift.db.plugins.cosmosdb.provider import CosmosDbProvider


def _provider() -> CosmosDbProvider:
    provider = CosmosDbProvider.__new__(CosmosDbProvider)
    provider.query_executor = MagicMock()
    provider.log = MagicMock()
    return provider


def test_upsert_native_item_forwards_to_the_query_executor():
    provider = _provider()
    document = {"snapshot_id": "abc-123", "captured_at": "2026-07-28T00:00:00Z"}

    provider.upsert_native_item("dblift_schema_snapshots", document)

    provider.query_executor.upsert_native_item.assert_called_once_with(
        "dblift_schema_snapshots", document
    )


def test_upsert_native_item_returns_whatever_the_query_executor_returns():
    provider = _provider()
    sdk_echo = {"snapshot_id": "abc-123", "_etag": '"0000-abcd"'}
    provider.query_executor.upsert_native_item.return_value = sdk_echo

    result = provider.upsert_native_item("dblift_schema_snapshots", {"snapshot_id": "abc-123"})

    assert result == sdk_echo


def test_upsert_native_item_never_reaches_execute_statement():
    """Regression guard: this must not become a rendered-SQL path that would
    hit the same NoSqlWriteNotSupportedError it exists to avoid."""
    provider = _provider()

    provider.upsert_native_item("dblift_schema_snapshots", {"snapshot_id": "x"})

    provider.query_executor.execute_statement.assert_not_called()


def test_delete_native_item_forwards_to_the_query_executor():
    provider = _provider()

    provider.delete_native_item("dblift_schema_snapshots", "abc-123", partition_key="abc-123")

    provider.query_executor.delete_native_item.assert_called_once_with(
        "dblift_schema_snapshots", "abc-123", partition_key="abc-123"
    )


def test_delete_native_item_never_reaches_execute_statement():
    """Regression guard: this must not become a rendered-SQL path that would
    hit the same NoSqlWriteNotSupportedError it exists to avoid."""
    provider = _provider()

    provider.delete_native_item("dblift_schema_snapshots", "abc-123", partition_key="abc-123")

    provider.query_executor.execute_statement.assert_not_called()
