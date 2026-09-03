"""MongoDB snapshot collection provisioning."""

from __future__ import annotations

from typing import Any, Optional

from dblift.core.logger import Log
from dblift.db.plugins.nosql_base import DocumentSnapshotManager


class MongoDbSnapshotManager(DocumentSnapshotManager):
    """Creates the snapshot collection through pymongo.

    No retry wrapper, unlike the Cosmos DB implementation: that one exists
    because the Azure emulator answers 503 while warming up. A mongod that
    refuses a collection create is reporting a real fault, and hiding it
    behind five attempts would only delay the error.
    """

    def __init__(self, provider: Any, log: Optional[Log] = None) -> None:
        """Take the owning provider; the logger defaults to the provider's."""
        super().__init__(provider=provider, log=log if log is not None else provider.log)

    def create_snapshot_collection(self, collection_name: str) -> None:
        """Create the snapshot collection when missing. Idempotent."""
        self.provider.schema_operations.create_collection_if_not_exists(collection_name)
