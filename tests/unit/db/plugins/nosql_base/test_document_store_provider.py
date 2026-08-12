"""``DocumentStoreProvider`` — the document operations a document store offers.

Runtime-checkable so a caller can ask "does this provider speak documents?"
instead of comparing dialect strings.
"""

from typing import Any, Dict, List

from db.plugins.nosql_base import DocumentStoreProvider


class _Complete:
    def upsert_native_item(self, collection: str, document: Dict[str, Any]) -> Dict[str, Any]:
        return document

    def delete_native_item(self, collection: str, item_id: str, partition_key: Any) -> None:
        return None

    def list_native_items(self, collection: str) -> List[Dict[str, Any]]:
        return []


class _MissingList:
    def upsert_native_item(self, collection: str, document: Dict[str, Any]) -> Dict[str, Any]:
        return document

    def delete_native_item(self, collection: str, item_id: str, partition_key: Any) -> None:
        return None


class _Relational:
    def execute_statement(self, sql: str) -> int:
        return 0


def test_complete_implementation_matches():
    assert isinstance(_Complete(), DocumentStoreProvider)


def test_partial_implementation_does_not_match():
    """A provider missing an operation must not pass as a document store —
    that is the whole point of checking the capability instead of the name."""
    assert not isinstance(_MissingList(), DocumentStoreProvider)


def test_relational_provider_does_not_match():
    assert not isinstance(_Relational(), DocumentStoreProvider)
