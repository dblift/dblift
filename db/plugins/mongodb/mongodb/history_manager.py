"""MongoDB migration history, stored as documents."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from core.logger import Log
from db.plugins.nosql_base import DocumentHistoryManager


class MongoDbHistoryManager(DocumentHistoryManager):
    """Migration history as one document per applied migration.

    ``installed_rank`` is the document ``_id``: it is unique per history
    collection and monotonically assigned by the framework, so it gives a
    natural primary key without a second index. Stored as a string because
    ``_id`` values are compared exactly and a mixed int/str history would
    silently fail to match.
    """

    def __init__(
        self,
        query_executor: Any,
        schema_operations: Any,
        config: Any,
        log: Optional[Log] = None,
    ) -> None:
        """Initialize with the executor, schema operations and config."""
        super().__init__(
            query_executor=query_executor,
            schema_operations=schema_operations,
            config=config,
            log=log,
        )

    def _collection(self, table_name: Optional[str] = None) -> str:
        return table_name or self.HISTORY_CONTAINER_NAME

    def create_migration_history_table_if_not_exists(
        self,
        connection: Any,
        schema: str,
        create_schema: bool = False,
        table_name: str = "dblift_schema_history",
    ) -> None:
        """Create the history collection when missing.

        ``create_schema`` is ignored — MongoDB has no schema layer, and the
        database itself is created by the server on first write.
        """
        self.schema_operations.create_collection_if_not_exists(self._collection(table_name))

    def record_migration(
        self,
        connection: Any,
        schema: str,
        migration_info: Dict[str, Any],
        table_name: Optional[str] = None,
    ) -> None:
        """Write one history document for *migration_info*.

        ``installed_rank`` is not something the caller provides — the real
        framework caller (``MigrationHistoryManager.record_migration``)
        never includes it in ``migration_info`` — so it is assigned here,
        the MongoDB-native equivalent of an auto-increment column: the
        current maximum rank in the collection, plus one.
        """
        collection = self._collection(table_name)
        existing = self.query_executor.list_documents(collection)
        next_rank = max((doc.get("installed_rank", 0) for doc in existing), default=0) + 1

        document = dict(migration_info)
        document["installed_rank"] = next_rank
        document["_id"] = str(next_rank)
        self.query_executor.upsert_document(collection, document)

    def get_applied_migrations(
        self, connection: Any, schema: str, table_name: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Return every history row, oldest first.

        ``_id`` is dropped: it duplicates ``installed_rank`` and the
        framework's row shape has no such column, so carrying it through
        would leak storage bookkeeping into comparisons.
        """
        documents = self.query_executor.list_documents(self._collection(table_name))
        rows = [{key: value for key, value in doc.items() if key != "_id"} for doc in documents]
        return sorted(rows, key=lambda row: row.get("installed_rank", 0))

    def repair_migration_history(
        self,
        connection: Any,
        schema: str,
        script_name: str,
        checksum: Any,
        success_value: Optional[Any] = None,
        table_name: Optional[str] = None,
    ) -> bool:
        """Rewrite the stored checksum for *script_name*.

        Args:
            connection: Active database connection (not used for MongoDB).
            schema: Schema name (not used for MongoDB).
            script_name: Script name to repair.
            checksum: New checksum value.
            success_value: If provided, also update the success field.
                If None, the success field is not modified.
            table_name: Custom history collection name.

        Returns:
            True if a history document was updated, False otherwise.
        """
        collection = self._collection(table_name)
        for document in self.query_executor.list_documents(collection):
            if document.get("script") == script_name:
                document["checksum"] = checksum
                if success_value is not None:
                    document["success"] = success_value
                self.query_executor.upsert_document(collection, document)
                return True
        return False

    def delete_failed_migration_entry(
        self,
        connection: Any,
        schema: str,
        script_name: str,
        table_name: Optional[str] = None,
    ) -> int:
        """Delete the failed history document(s) for *script_name*.

        ``repair`` calls this so a failed migration can be re-applied — a
        failed row is a tombstone that ``migrate`` skips, so correcting its
        checksum would leave it blocking. Only rows with ``success`` false
        are removed; successful history is never deleted.

        Overriding is mandatory. The inherited implementation builds a SQL
        ``DELETE`` and sends it to the query executor, which on MongoDB
        raises ``DBLIFT-NOSQL-002`` — leaving the failed migration
        permanently unretryable.
        """
        collection = self._collection(table_name)
        removed = 0
        for document in self.query_executor.list_documents(collection):
            if document.get("script") == script_name and not document.get("success", False):
                removed += self.query_executor.delete_document(collection, document["_id"])
        return removed

    def create_history_table(self, schema: str, table_name: str) -> str:
        """Describe how history storage is created — not executable DDL."""
        return (
            f"-- MongoDbHistoryManager: history collection '{table_name}' "
            "is created through pymongo, not DDL."
        )
