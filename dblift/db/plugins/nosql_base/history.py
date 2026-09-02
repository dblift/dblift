"""Migration history stored as documents rather than table rows."""

from abc import abstractmethod
from typing import Any, Optional

from dblift.db.plugins.base_history_manager import BaseHistoryManager


class DocumentHistoryManager(BaseHistoryManager):
    """History manager for a document store.

    Keeps the same contract every backend honours — record a migration,
    read what has been applied, repair a checksum, delete a failed row —
    but each operation is an SDK call on a collection of documents rather
    than SQL against a table.

    Two inherited assumptions do not hold here and are re-stated so an
    implementer does not have to rediscover them:

    * ``create_history_table`` cannot return runnable DDL. Return a short
      description of the SDK call instead; nothing executes the result.
    * ``delete_failed_migration_entry`` must not fall through to the
      inherited ``DELETE`` — the query API of a document store is
      read-only, so the base implementation would raise. Override it and
      delete the document.
    """

    #: Name of the collection/container holding migration history.
    #: Implementations override; the framework never assumes a SQL table
    #: name so this may differ from ``dblift_schema_history``.
    HISTORY_CONTAINER_NAME: str = "dblift_schema_history"

    @abstractmethod
    def delete_failed_migration_entry(
        self,
        connection: Any,
        schema: str,
        script_name: str,
        table_name: Optional[str] = None,
    ) -> int:
        """Delete the failed history document(s) for *script_name*.

        Returns the number of documents removed. Called by ``repair`` so a
        failed migration can be re-applied.
        """

    def create_history_table(self, schema: str, table_name: str) -> str:
        """Describe how history storage is created — not executable DDL.

        Callers log this string; none of them execute it. Implementations
        may override to name their own SDK call.
        """
        return (
            f"-- {self.__class__.__name__}: history collection "
            f"'{table_name}' is created through the vendor SDK, not DDL."
        )
