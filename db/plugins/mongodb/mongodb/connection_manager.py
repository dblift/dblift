"""MongoDB connection management using pymongo."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional

from config import DbliftConfig
from core.logger import Log, NullLog

if TYPE_CHECKING:
    from pymongo import MongoClient
    from pymongo.database import Database

#: Fail fast rather than block a migrate run behind the driver's 30s default.
_SERVER_SELECTION_TIMEOUT_MS = 10_000


def _load_mongo_client() -> Any:
    """Import ``MongoClient`` at call time.

    Kept behind a function so plugin discovery works without pymongo
    installed, and so the missing-driver path is a single seam the tests
    can drive.
    """
    from pymongo import MongoClient

    return MongoClient


class MongoDbConnectionManager:
    """Manages MongoDB connections using pymongo.

    ``client`` and ``database`` are part of dblift's public contract, not
    private state: ``MigrationContext.raw_client`` and ``MigrationContext.db``
    resolve by reading exactly these attribute names off the provider's
    connection manager. A user's Python migration reaches the driver through
    them, so renaming either breaks every migration silently.
    """

    def __init__(self, config: DbliftConfig, log: Optional[Log] = None) -> None:
        """Initialize the connection manager and validate the target."""
        self.config = config
        self.log = log if log is not None else NullLog()
        self.client: Optional["MongoClient[Any]"] = None
        self.database: Optional["Database[Any]"] = None

    def create_connection(self) -> Any:
        """Open the client, prove the server is reachable, and select the database.

        Returns the ``Database`` handle. pymongo's ``MongoClient`` constructor
        itself connects lazily, so it never raises for a bad host on its own —
        every other dialect's ``create_connection`` performs a real handshake,
        and callers (``db check-connection`` in particular) rely on that to
        report failure instead of a false "connected". An explicit ``ping``
        forces that handshake now, within ``_SERVER_SELECTION_TIMEOUT_MS``,
        instead of deferring it to whatever operation happens to run first.
        """
        uri = self.config.database.build_connection_string()
        database_name = self.config.database.database
        if not database_name:
            raise ValueError("MongoDB database name is required")

        self.log.debug(f"Connecting to MongoDB: {self.config.database.build_database_url()}")

        try:
            mongo_client = _load_mongo_client()
        except ImportError as import_error:
            error_msg = (
                "MongoDB driver not installed. " 'Install it with: pip install "dblift[mongodb]"'
            )
            self.log.error(error_msg)
            raise ImportError(error_msg) from import_error

        self.client = mongo_client(
            uri,
            serverSelectionTimeoutMS=_SERVER_SELECTION_TIMEOUT_MS,
        )
        self.client.admin.command("ping")
        self.database = self.client[database_name]
        self.log.debug(f"Connected to MongoDB database: {database_name}")
        return self.database

    def get_collection(self, collection_name: str) -> Any:
        """Return a collection handle, connecting first if needed."""
        if self.database is None:
            self.create_connection()
        if self.database is None:
            raise RuntimeError("Database should be initialized after create_connection()")
        return self.database[collection_name]

    def get_database_url(self) -> Optional[str]:
        """Return the connection URI with the password masked."""
        return self.config.database.build_database_url()

    def close(self) -> None:
        """Close the client and clear both handles."""
        if self.client is not None:
            self.client.close()
        self.client = None
        self.database = None
        self.log.debug("MongoDB connection closed")
