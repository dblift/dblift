"""MongoDB document operations, and the rejection of string statements.

dblift's own storage inside the target database — migration history, the
lock lease, captured snapshots — is written through the typed document
methods here. A user-authored Python migration does not come through this
module at all: it reaches the driver via ``context.db`` /
``context.raw_client``.
"""

from __future__ import annotations

from typing import Any, Dict, List, NoReturn, Optional

from core.exceptions import NoSqlQueryLanguageUnsupportedError
from core.logger import Log, NullLog

_NO_QUERY_LANGUAGE = (
    "DBLIFT-NOSQL-002: MongoDB has no SQL or string query language, so "
    "'{statement}' cannot be executed. Reach the driver directly from your "
    "Python migration: context.db (a pymongo.database.Database) or "
    "context.raw_client (a pymongo.MongoClient). Reads are collection "
    "method calls — context.db['users'].find({{...}}) — not statements."
)

#: Longest statement excerpt echoed back in the error. Long enough to
#: identify the offending call, short enough not to dump a whole script.
_EXCERPT_LIMIT = 120


class MongoDbQueryExecutor:
    """Executes document operations; refuses statements.

    Unlike Cosmos DB — whose SQL API genuinely executes ``SELECT``, so its
    executor rejects only writes — MongoDB has no string language at all.
    Both ``execute_statement`` and ``execute_query`` therefore raise. The
    methods exist because the provider interface declares them, and raising
    a named, coded error is a better answer than an ``AttributeError``.
    """

    def __init__(self, connection_manager: Any, log: Optional[Log] = None) -> None:
        """Store the connection manager and the logger."""
        self.connection_manager = connection_manager
        self.log: Log = log if log is not None else NullLog()

    @staticmethod
    def _reject(sql: str) -> NoReturn:
        """Raise the coded error naming the statement and the remedy.

        Annotated ``NoReturn`` so the callers below need no unreachable
        ``return`` to satisfy their declared types — mypy understands that
        control never comes back from here.
        """
        excerpt = (sql or "")[:_EXCERPT_LIMIT]
        raise NoSqlQueryLanguageUnsupportedError(_NO_QUERY_LANGUAGE.format(statement=excerpt))

    def execute_statement(
        self,
        sql: str,
        schema: Optional[str] = None,
        params: Optional[Any] = None,
    ) -> int:
        """Always raises — see the class docstring."""
        self._reject(sql)

    def execute_query(self, sql: str, params: Optional[Any] = None) -> List[Dict[str, Any]]:
        """Always raises — see the class docstring."""
        self._reject(sql)

    def upsert_document(self, collection: str, document: Dict[str, Any]) -> Dict[str, Any]:
        """Insert *document*, replacing any existing document with the same ``_id``.

        Returns the document as supplied — the driver's ``replace_one``
        reports counts, not the stored body, and callers only need to know
        the write happened.
        """
        self.connection_manager.get_collection(collection).replace_one(
            {"_id": document["_id"]}, document, upsert=True
        )
        return document

    def delete_document(self, collection: str, item_id: str) -> int:
        """Delete the document with ``_id == item_id``; return the count removed."""
        result = self.connection_manager.get_collection(collection).delete_one({"_id": item_id})
        return int(result.deleted_count)

    def list_documents(
        self, collection: str, filter_: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        """Return the documents in *collection* matching *filter_*.

        The cursor is drained into a list because every caller here reads
        the whole (small, dblift-owned) collection and holding a cursor open
        across a migrate run buys nothing.
        """
        cursor = self.connection_manager.get_collection(collection).find(filter_ or {})
        return list(cursor)

    def get_schema_qualified_name(self, schema: str, object_name: str) -> str:
        """Return *object_name* unchanged — MongoDB has no schema layer.

        Prefixing would name a collection that does not exist. ``schema`` is
        accepted for interface parity.
        """
        return object_name
