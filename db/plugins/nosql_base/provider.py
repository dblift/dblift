"""The document operations a document-store provider offers."""

from typing import Any, Dict, List, Protocol, runtime_checkable


@runtime_checkable
class DocumentStoreProvider(Protocol):
    """Document-level persistence, for callers that must not compose SQL.

    Storage that dblift keeps *inside* the target database — migration
    history, the lock lease, captured snapshots — is written as rows on a
    relational engine and as documents on a document store. Callers in the
    middle need to know which, and asking the dialect by name does not
    scale past the first document store: it produces a branch per engine,
    and it silently mis-routes any read path nobody remembered to branch.

    Implementing this protocol is the answer to "does this provider speak
    documents?". It is ``runtime_checkable``, so a caller uses
    ``isinstance(provider, DocumentStoreProvider)`` and gets a capability
    check rather than a name comparison.

    Each implementation keeps its own best mechanism behind these methods.
    Cosmos DB's ``list_native_items`` issues a native ``SELECT`` (its SQL
    API genuinely executes one); MongoDB's issues ``find()``. Neither
    caller nor protocol has an opinion.
    """

    def upsert_native_item(self, collection: str, document: Dict[str, Any]) -> Dict[str, Any]:
        """Insert *document* into *collection*, replacing any same-id document.

        Returns the stored document as the store recorded it.
        """
        ...

    def delete_native_item(self, collection: str, item_id: str, partition_key: Any) -> None:
        """Delete the document identified by *item_id* from *collection*.

        ``partition_key`` is the store's routing value. Engines without
        partitioning accept and ignore it, so the signature stays uniform.
        """
        ...

    def list_native_items(self, collection: str) -> List[Dict[str, Any]]:
        """Return every document in *collection*.

        Ordering is not guaranteed — callers that need an order impose it.
        """
        ...
