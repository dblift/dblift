"""MongoDB collection operations — created and dropped through the driver."""

from __future__ import annotations

from typing import Any, List, Optional

from core.logger import Log, NullLog
from core.migration.clean_summary import CleanExecutionSummary


class MongoDbSchemaOperations:
    """Lists, creates and drops collections.

    MongoDB has no DDL and no schema layer: a collection springs into
    existence on first write, and dblift creates them explicitly only so
    that its own storage is present before anything reads it.
    """

    def __init__(self, query_executor: Any, log: Optional[Log] = None) -> None:
        """Store the executor (for its connection manager) and the logger."""
        self.query_executor = query_executor
        self.log: Log = log if log is not None else NullLog()

    def _database(self) -> Any:
        """Return the live ``Database`` handle, connecting if needed."""
        connection_manager = self.query_executor.connection_manager
        if connection_manager.database is None:
            connection_manager.create_connection()
        return connection_manager.database

    def list_collections(self) -> List[str]:
        """Return every collection name, dblift's own storage included.

        Unfiltered on purpose. Clean drops the whole database — the Cosmos DB
        plugin's ``list_containers`` behaves identically for the same reason —
        so filtering here would silently make clean partial.
        """
        return list(self._database().list_collection_names())

    def collection_exists(self, collection_name: str) -> bool:
        """Whether *collection_name* exists."""
        return collection_name in self.list_collections()

    @staticmethod
    def _drop_audit_line(collection_name: str) -> str:
        """Render the driver call clean makes, for the summary's audit trail.

        Not executable and never executed: MongoDB has no statement to run.
        """
        return f"database.drop_collection({collection_name!r})"

    def create_collection_if_not_exists(self, collection_name: str) -> None:
        """Create *collection_name* when missing. Idempotent."""
        if self.collection_exists(collection_name):
            return
        self._database().create_collection(collection_name)
        self.log.debug(f"Created collection: {collection_name}")

    def drop_collection(self, collection_name: str) -> bool:
        """Drop *collection_name*; ``True`` when one was actually dropped."""
        if not self.collection_exists(collection_name):
            return False
        self._database().drop_collection(collection_name)
        self.log.debug(f"Dropped collection: {collection_name}")
        return True

    def table_exists(self, connection: Any, schema: str, table_name: str) -> bool:
        """Provider-interface alias for :meth:`collection_exists`."""
        return self.collection_exists(table_name)

    def get_database_version(self, connection: Any) -> str:
        """Return the server version, or ``"unknown"`` if it cannot be read.

        ``buildInfo`` needs no special privilege on a default deployment,
        but a locked-down cluster can refuse it — and a version string is
        never worth failing a migrate run over.
        """
        try:
            return str(self._database().command("buildInfo").get("version", "unknown"))
        except Exception as e:
            self.log.debug(f"Could not read MongoDB server version: {e}")
            return "unknown"

    def clean_schema(self, connection: Any, schema: str) -> CleanExecutionSummary:
        """Drop every collection, dblift's own storage included.

        A failure on one collection is recorded and the loop continues:
        abandoning the rest would leave the database in a state that is
        neither the old one nor clean.
        """
        summary = CleanExecutionSummary()
        for collection_name in self.list_collections():
            try:
                self._database().drop_collection(collection_name)
            except Exception as drop_error:
                message = f"Error dropping collection {collection_name}: {drop_error}"
                self.log.error(message)
                summary.errors.append(message)
                continue
            summary.record_drop(
                sql=self._drop_audit_line(collection_name),
                object_type="COLLECTION",
                name=collection_name,
                schema=None,
            )
            self.log.debug(f"Dropped collection: {collection_name}")
        return summary

    def get_clean_preview(self, schema: str) -> CleanExecutionSummary:
        """Report what :meth:`clean_schema` would drop, dropping nothing."""
        summary = CleanExecutionSummary()
        for collection_name in self.list_collections():
            summary.record_drop(
                sql=self._drop_audit_line(collection_name),
                object_type="COLLECTION",
                name=collection_name,
                schema=None,
            )
        return summary
