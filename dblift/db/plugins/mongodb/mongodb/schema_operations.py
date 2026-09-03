"""MongoDB collection operations — created and dropped through the driver."""

from __future__ import annotations

from typing import Any, List, Optional, Tuple, Union

from dblift.core.logger import Log
from dblift.core.migration.clean_summary import CleanExecutionSummary
from dblift.db.plugins.base_schema_operations import BaseSchemaOperations


class MongoDbSchemaOperations(BaseSchemaOperations):
    """Lists, creates and drops collections.

    MongoDB has no DDL and no schema layer: a collection springs into
    existence on first write, and dblift creates them explicitly only so
    that its own storage is present before anything reads it.
    """

    def __init__(self, query_executor: Any, log: Optional[Log] = None) -> None:
        """Store the executor (for its connection manager) and the logger."""
        super().__init__(query_executor=query_executor, log=log)

    def _database(self) -> Any:
        """Return the live ``Database`` handle, connecting if needed."""
        connection_manager = self.query_executor.connection_manager
        if connection_manager.database is None:
            connection_manager.create_connection()
        return connection_manager.database

    def create_schema_if_not_exists(self, connection: Any, schema: str) -> None:
        """No-op for MongoDB — it has no schema layer.

        MongoDB has no schemas. The database is selected by the connection,
        and collections spring into existence on first write.
        """
        self.log.debug(f"Schema layer not applicable to MongoDB; using database: {schema}")

    def set_current_schema(self, connection: Any, schema: str) -> None:
        """No-op for MongoDB — it has no schema layer.

        MongoDB has no schemas. The database is selected at connection time.
        """
        self.log.debug("Schema setting not applicable to MongoDB")

    def list_collections(self) -> List[str]:
        """Return every collection name, dblift's own storage included.

        Unfiltered on purpose: ``collection_exists``, ``get_tables`` and
        ``create_collection_if_not_exists`` all need the true full list, not
        a clean-specific view of it. Clean itself enumerates through
        :meth:`list_droppable_collections`, which excludes collections whose
        name starts with the server-reserved ``system.`` prefix — see that
        method for why.
        """
        return list(self._database().list_collection_names())

    def collection_exists(self, collection_name: str) -> bool:
        """Whether *collection_name* exists."""
        return collection_name in self.list_collections()

    def list_droppable_collections(self) -> List[str]:
        """Return collection names clean should drop.

        Same as :meth:`list_collections` — dblift's own storage included,
        since clean's contract is a full reset — except for anything whose
        name *starts with* ``system.``. That prefix is reserved by MongoDB
        itself: the server refuses to create a collection under it (an
        attempt to make ``system.custom`` fails outright), so anything
        carrying it is server-maintained bookkeeping, never user schema.
        Relational ``clean`` drops user objects and leaves catalogs like
        ``pg_catalog`` alone; this is the MongoDB equivalent. A name that
        merely *contains* ``system.`` — e.g. ``orders_system.log`` — is an
        ordinary, server-accepted user collection and must still be
        dropped, which is why this is a prefix check, not a substring one.

        Excluding the prefix is not just tidiness: ``system.views`` stores
        every view's definition, so dropping it erases the views
        themselves. A later attempt to drop one of those now-vanished
        views then reports a spurious failure for an object clean's own
        earlier step already removed. Skipping ``system.views`` here
        removes the cause instead of reordering around it.

        Trade-off worth stating: ``system.js`` — the legacy user-writable
        stored-JavaScript collection — also carries this prefix and is
        skipped by the same rule, and unlike ``system.views`` it holds
        user-authored content, not metadata. It survives a clean. That is
        judged acceptable because dblift manages schema and stored
        JavaScript is not schema, but it is a real, visible behavioural
        consequence of this filter.
        """
        return [name for name in self.list_collections() if not name.startswith("system.")]

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

    def get_tables(self, connection: Any, schema: str) -> List[str]:
        """Return list of collections (tables in MongoDB's document model).

        Args:
            connection: Database connection (unused, uses internal connection manager)
            schema: Schema name (unused, MongoDB has no schemas)

        Returns:
            List of collection names
        """
        return self.list_collections()

    def get_schemas(self, connection: Any) -> List[str]:
        """Return list of schemas (empty for MongoDB).

        MongoDB has no schema layer. A database contains collections,
        but no nested schema objects.

        Args:
            connection: Database connection (unused)

        Returns:
            Empty list
        """
        return []

    def get_columns_query(self, schema: str, table: str) -> Union[str, Tuple[str, List[Any]]]:
        """Return a MongoDB query to sample a collection's documents.

        MongoDB is schema-less. This returns a find query that samples
        documents from the collection to inspect their structure.

        Args:
            schema: Schema name (unused)
            table: Collection name

        Returns:
            MongoDB find query string
        """
        return f"db.{table}.findOne()"

    def get_add_column_sql(self, schema: str, table: str, column: str, type_def: str) -> str:
        """Return a comment string; MongoDB needs no schema alterations.

        MongoDB is schema-less. Adding a field to a document requires only
        a write operation on documents that need it; no DDL is necessary.

        Args:
            schema: Schema name (unused)
            table: Collection name
            column: Field name
            type_def: Type definition (unused)

        Returns:
            Comment string explaining why no SQL is needed
        """
        return f"-- MongoDB is schema-less; no ALTER needed for {table}.{column}"

    def get_parameter_placeholders(self, count: int) -> str:
        """Return positional parameter placeholders for prepared statements.

        MongoDB drivers use ? for parameter placeholders in SQL contexts
        (e.g., when the plugin must interop with SQL-based tools).

        Args:
            count: Number of placeholders needed

        Returns:
            Comma-separated placeholder string (e.g., "?, ?, ?")
        """
        return ", ".join(["?" for _ in range(count)])

    def clean_schema(self, connection: Any, schema: str) -> CleanExecutionSummary:
        """Drop every droppable collection, dblift's own storage included.

        A failure on one collection is recorded and the loop continues:
        abandoning the rest would leave the database in a state that is
        neither the old one nor clean. See :meth:`list_droppable_collections`
        for what is excluded and why.
        """
        summary = CleanExecutionSummary()
        for collection_name in self.list_droppable_collections():
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
        for collection_name in self.list_droppable_collections():
            summary.record_drop(
                sql=self._drop_audit_line(collection_name),
                object_type="COLLECTION",
                name=collection_name,
                schema=None,
            )
        return summary
