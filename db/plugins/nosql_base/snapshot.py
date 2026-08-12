"""Snapshot storage provisioned as a collection rather than a table."""

from abc import ABC, abstractmethod
from typing import Any, Optional

from core.constants import DBLIFT_SCHEMA_SNAPSHOTS_TABLE
from core.logger import Log, NullLog


class DocumentSnapshotManager(ABC):
    """Creates the snapshot collection through the vendor driver.

    The relational sibling, ``db/plugins/base_snapshot_manager.py``, renders
    a ``CREATE TABLE`` and sends it to the provider. That is the default a
    provider inherits, which makes it a trap for a document store: forget to
    override ``create_snapshot_table_if_not_exists`` and the plugin looks
    complete, discovers fine, migrates fine, and fails only when something
    first tries to persist a snapshot — with a SQL error from a store that
    has no SQL.

    Declaring :meth:`create_snapshot_collection` abstract turns that
    omission into a ``TypeError`` at construction. Same reasoning that made
    ``delete_failed_migration_entry`` abstract on
    :class:`DocumentHistoryManager`.

    Retry policy is deliberately not here. Cosmos DB retries because the
    Azure emulator answers 503 during warmup; that is one engine's operational
    quirk, not a shared contract, and it belongs in that engine's subclass.
    """

    def __init__(self, provider: Any, log: Optional[Log] = None) -> None:
        """Store the owning provider and the logger.

        ``provider`` is typed ``Any``: each driver exposes a different
        connection shape and the contract here does not constrain it.
        """
        self.provider: Any = provider
        self.log: Log = log if log is not None else NullLog()

    @abstractmethod
    def create_snapshot_collection(self, collection_name: str) -> None:
        """Create *collection_name* if it is missing. Must be idempotent."""

    def create_snapshot_table_if_not_exists(
        self,
        schema: str,
        table_name: Optional[str] = None,
    ) -> None:
        """Provider-facing entry point; resolves the name, then delegates.

        ``schema`` is accepted for signature parity with the relational
        provider API and ignored — a document store has no schema layer.
        """
        self.create_snapshot_collection(table_name or DBLIFT_SCHEMA_SNAPSHOTS_TABLE)
