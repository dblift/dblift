"""``CosmosDbProvider.list_native_items`` must be a thin forward to the
query executor, not a new SQL path.

Mirrors ``test_upsert_native_item_provider_wrapper.py``: that file pins the
document-*write* seam; this one pins the missing document-*read* seam --
``DocumentStoreProvider`` declares ``list_native_items`` alongside
``upsert_native_item`` / ``delete_native_item``, but ``CosmosDbProvider``
only implemented the first two, so ``isinstance(provider,
DocumentStoreProvider)`` answered ``False`` for CosmosDB even though it is a
document store.
"""

from unittest.mock import MagicMock

from db.plugins.cosmosdb.provider import CosmosDbProvider


def _provider() -> CosmosDbProvider:
    provider = CosmosDbProvider.__new__(CosmosDbProvider)
    provider.query_executor = MagicMock()
    provider.log = MagicMock()
    return provider


def test_list_native_items_forwards_to_the_query_executor():
    provider = _provider()

    provider.list_native_items("dblift_schema_snapshots")

    provider.query_executor.list_native_items.assert_called_once_with("dblift_schema_snapshots")


def test_list_native_items_returns_whatever_the_query_executor_returns():
    provider = _provider()
    documents = [{"id": "a"}, {"id": "b"}]
    provider.query_executor.list_native_items.return_value = documents

    result = provider.list_native_items("dblift_schema_snapshots")

    assert result == documents


def test_list_native_items_never_reaches_execute_statement():
    """Regression guard: this must not become a rendered-SQL path that would
    hit the same NoSqlWriteNotSupportedError family of problems the native
    write/delete paths exist to avoid."""
    provider = _provider()

    provider.list_native_items("dblift_schema_snapshots")

    provider.query_executor.execute_statement.assert_not_called()
