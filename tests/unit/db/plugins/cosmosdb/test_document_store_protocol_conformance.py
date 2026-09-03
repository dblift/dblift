"""``CosmosDbProvider`` must satisfy ``DocumentStoreProvider``.

Before ``list_native_items`` was added, ``CosmosDbProvider`` implemented
``upsert_native_item`` and ``delete_native_item`` but not the third method
the protocol declares, so ``isinstance(provider, DocumentStoreProvider)``
answered ``False`` for CosmosDB even though it is a document store. Mirrors
``tests/unit/db/providers/mongodb/test_provider.py::
test_satisfies_the_document_store_contract``, which pins the same contract
for MongoDB.

A real ``isinstance`` check, not a ``hasattr`` sweep: ``DocumentStoreProvider``
is ``runtime_checkable``, so this exercises the same capability check a
caller performs.
"""

from dblift.db.plugins.cosmosdb.provider import CosmosDbProvider
from dblift.db.plugins.nosql_base import DocumentStoreProvider


def test_cosmosdb_provider_satisfies_the_document_store_contract():
    provider = CosmosDbProvider.__new__(CosmosDbProvider)
    assert isinstance(provider, DocumentStoreProvider)
