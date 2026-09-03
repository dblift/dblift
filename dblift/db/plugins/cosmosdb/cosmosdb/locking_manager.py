"""
Cosmos DB migration locking using optimistic concurrency and document-based locking.

This module implements distributed locking for migrations using Cosmos DB's native
optimistic concurrency (ETag-based conditional updates) as the primary mechanism,
with document-based locking as a fallback.

The pattern matches other providers:
1. Try native locking (ETag-based conditional updates)
2. Fall back to document-based locking if native locking fails
3. Lock is always cleaned up after migration completes
"""

import datetime
import os
import socket
import time
from typing import TYPE_CHECKING, Optional

from dblift.core.constants import DEFAULT_MIGRATION_LOCK_TIMEOUT_SECONDS
from dblift.core.logger import Log
from dblift.db.plugins.nosql_base import DocumentLockingManager

from .query_executor import CosmosDbQueryExecutor

if TYPE_CHECKING:
    from azure.cosmos import ContainerProxy


class CosmosDbLockingManager(DocumentLockingManager):
    """Manages migration locks using Cosmos DB optimistic concurrency and document-based locking.

    Uses CosmosDB's native optimistic concurrency (ETag-based conditional updates) as the
    primary locking mechanism, falling back to document-based locking if native locking fails.

    Note: This class does NOT inherit from BaseLockingManager (db/plugins/base_locking_manager.py)
    because CosmosDB has a fundamentally different API:
    - No connection parameter (uses _container instead of a passed connection)
    - Document-based locking (create_migration_lock_container_if_not_exists vs
      create_migration_lock_table_if_not_exists)
    - acquire_migration_lock and release_migration_lock signatures omit the connection parameter

    CosmosDB is conceptually aligned with the locking contract but cannot implement the
    Base BaseLockingManager interface without breaking its existing API.
    """

    LOCK_CONTAINER_NAME = "dblift_migration_lock"
    LOCK_DOCUMENT_ID = "migration_lock"

    def __init__(self, query_executor: CosmosDbQueryExecutor, log: Optional[Log] = None):
        """Initialize the locking manager.

        Args:
            query_executor: Cosmos DB query executor
            log: Optional logger
        """
        super().__init__(query_executor, log)
        self.lock_container: Optional["ContainerProxy"] = None

    def create_migration_lock_container_if_not_exists(self, schema: str) -> None:
        """Create the migration lock container if it doesn't exist.

        Args:
            schema: Schema name (not used in Cosmos DB, but kept for compatibility)
        """
        try:
            from azure.cosmos import PartitionKey

            database = self.connection_manager.database
            if database is None:
                self.connection_manager.create_connection()
                database = self.connection_manager.database

            if database is None:
                raise RuntimeError("Failed to get database connection")

            # Use create_container_if_not_exists to avoid conflicts (side-effect:
            # provisions the container; the returned proxy is discarded in favour
            # of get_container_client below for consistency with subsequent ops).
            database.create_container_if_not_exists(
                id=self.LOCK_CONTAINER_NAME,
                partition_key=PartitionKey(path="/id"),
            )

            # Get container client for operations
            self.lock_container = database.get_container_client(self.LOCK_CONTAINER_NAME)

            # Small delay to ensure container is ready
            time.sleep(0.5)  # Increased delay for emulator

            self.log.debug(f"Ensured lock container exists: {self.LOCK_CONTAINER_NAME}")

        except Exception as e:
            error_msg = f"Error creating lock container: {str(e)}"
            self.log.error(error_msg)
            raise

    def acquire_migration_lock(
        self, schema: str, wait_timeout_seconds: int = DEFAULT_MIGRATION_LOCK_TIMEOUT_SECONDS
    ) -> bool:
        """Acquire migration lock using Cosmos DB native optimistic concurrency, with fallback.

        Tries native locking first (ETag-based conditional updates), then falls back to
        document-based locking if native locking fails. This matches the pattern used by
        other database providers.

        Args:
            schema: Schema name (not used in Cosmos DB, but kept for compatibility)
            wait_timeout_seconds: How long to wait for lock acquisition

        Returns:
            True if lock acquired successfully, False otherwise
        """
        self.log.debug(f"Attempting to acquire migration lock for schema: {schema}")

        # Ensure lock container exists. Catch infra failures and
        # return ``False`` so the ``-> bool`` contract callers depend
        # on (``MigrateCommand`` checks ``if not provider.acquire_...``)
        # holds. Log at error level so the conflation between
        # "lock held" and "infra failure" is visible to operators.
        # Earlier attempt to let the exception propagate broke the
        # migrate flow when callers expected a bool (PR #241 Bugbot).
        try:
            self.create_migration_lock_container_if_not_exists(schema)
        except Exception as exc:
            self.log.error(
                f"Failed to initialize Cosmos DB lock container for schema "
                f"{schema!r}: {exc}. Treating as 'lock not acquired'."
            )
            return False

        # Ensure we have the container client
        if not self.lock_container:
            database = self.connection_manager.database
            if database is None:
                self.connection_manager.create_connection()
                database = self.connection_manager.database
            if database is None:
                raise RuntimeError("Database not initialized")
            self.lock_container = database.get_container_client(self.LOCK_CONTAINER_NAME)

        if self.lock_container is None:
            raise RuntimeError("Lock container not initialized")

        # Try native locking first (ETag-based conditional updates)
        try:
            if self._try_native_lock_acquire(schema, wait_timeout_seconds):
                return True
        except Exception as e:
            self.log.warning(
                f"Error acquiring native migration lock for schema {schema}: {str(e)}; falling back to document-based locking"
            )

        # Fall back to document-based locking
        self.log.debug("Falling back to document-based locking mechanism")
        return self._acquire_document_based_lock(schema, wait_timeout_seconds)

    def _try_native_lock_acquire(self, schema: str, wait_timeout_seconds: int) -> bool:
        """Try to acquire lock using CosmosDB's native optimistic concurrency (ETag-based).

        Uses conditional updates with ETags to atomically acquire the lock.
        This is CosmosDB's "native" locking mechanism using optimistic concurrency.

        Args:
            schema: Schema name (not used in Cosmos DB)
            wait_timeout_seconds: How long to wait for lock acquisition

        Returns:
            True if lock acquired successfully, False otherwise
        """
        start_time = time.time()
        username = os.environ.get("USER", os.environ.get("USERNAME", "unknown"))
        hostname = socket.gethostname()
        f"{username}@{hostname}"

        while time.time() - start_time < wait_timeout_seconds:
            if self.lock_container is None:
                self.log.debug("Lock container not initialized, skipping native lock attempt")
                return False
            try:
                # Try to read existing lock document
                try:
                    existing_lock = self.lock_container.read_item(
                        item=self.LOCK_DOCUMENT_ID,
                        partition_key=self.LOCK_DOCUMENT_ID,
                    )

                    # Check if lock is expired
                    expires_at = existing_lock.get("expires_at")
                    if expires_at:
                        expires_datetime = datetime.datetime.fromisoformat(
                            expires_at.replace("Z", "+00:00")
                        )
                        if datetime.datetime.now(datetime.timezone.utc) > expires_datetime:
                            # Lock expired, try to delete and recreate atomically
                            try:
                                # Delete expired lock using its ETag (conditional delete)
                                etag = existing_lock.get("_etag")
                                if etag:
                                    self.lock_container.delete_item(
                                        item=self.LOCK_DOCUMENT_ID,
                                        partition_key=self.LOCK_DOCUMENT_ID,
                                        etag=etag,  # Conditional delete - only if ETag matches
                                    )
                                    time.sleep(0.2)  # Small delay after deletion
                                    continue
                            except Exception as delete_error:
                                # ETag mismatch or other error - another process might have deleted it
                                error_str = str(delete_error).lower()
                                if "precondition" in error_str or "412" in error_str:
                                    # ETag mismatch - another process modified it, retry
                                    time.sleep(0.5)
                                    continue
                                # Other error, continue to retry
                                time.sleep(0.5)
                                continue

                    # Lock exists and is not expired - wait and retry
                    elapsed = int(time.time() - start_time)
                    self.log.debug(
                        f"Lock held by another process, waiting... (elapsed: {elapsed}s)"
                    )
                    time.sleep(1)
                    continue

                except Exception as read_error:
                    # Document doesn't exist (404) - try to create it immediately
                    error_str = str(read_error).lower()
                    if "not found" in error_str or "notfound" in error_str or "404" in error_str:
                        # Document doesn't exist, try to create it atomically
                        if self._create_lock_document():
                            self.log.debug(
                                "Successfully acquired migration lock using native optimistic concurrency"
                            )
                            return True
                        # Creation failed - document was created by another process between read and create
                        # This is expected in concurrent scenarios, wait and retry
                        elapsed = int(time.time() - start_time)
                        self.log.debug(
                            f"Lock document created by another process, retrying... (elapsed: {elapsed}s)"
                        )
                        time.sleep(0.5)
                        continue
                    else:
                        # Other error reading document - fall back to document-based locking
                        self.log.debug(
                            f"Error reading lock document: {str(read_error)}, will fall back"
                        )
                        return False

            except Exception as e:
                error_str = str(e).lower()
                if "conflict" in error_str or "already exists" in error_str or "409" in error_str:
                    # Lock is held by another process, wait and retry
                    elapsed = int(time.time() - start_time)
                    self.log.debug(
                        f"Lock held by another process (conflict), waiting... (elapsed: {elapsed}s)"
                    )
                    time.sleep(1)
                    continue
                else:
                    # Unexpected error - fall back to document-based locking
                    self.log.debug(f"Error in native lock acquisition: {str(e)}, will fall back")
                    return False

        # Timeout exceeded
        self.log.debug(f"Native lock acquisition timeout after {wait_timeout_seconds} seconds")
        return False

    def _acquire_document_based_lock(self, schema: str, wait_timeout_seconds: int) -> bool:
        """Acquire lock using document-based mechanism as fallback.

        Uses a simple create-if-not-exists pattern matching other database providers.

        Args:
            schema: Schema name (not used in Cosmos DB)
            wait_timeout_seconds: How long to wait for lock acquisition

        Returns:
            True if lock acquired successfully, False otherwise
        """
        self.log.debug("Using document-based locking mechanism as fallback")

        start_time = time.time()

        while time.time() - start_time < wait_timeout_seconds:
            try:
                # Try to create lock document (will fail if it already exists)
                if self._create_lock_document():
                    self.log.debug(
                        "Successfully acquired migration lock using document-based locking"
                    )
                    return True

                # Creation failed - document might already exist
                # Check if existing lock is expired and can be cleaned up
                if self.lock_container is None:
                    time.sleep(0.5)
                    continue
                try:
                    existing_lock = self.lock_container.read_item(
                        item=self.LOCK_DOCUMENT_ID,
                        partition_key=self.LOCK_DOCUMENT_ID,
                    )
                    # Check if lock is expired
                    expires_at = existing_lock.get("expires_at")
                    if expires_at:
                        expires_datetime = datetime.datetime.fromisoformat(
                            expires_at.replace("Z", "+00:00")
                        )
                        if datetime.datetime.now(datetime.timezone.utc) > expires_datetime:
                            # Lock expired, delete it and try again
                            self.log.debug("Found expired lock, deleting and retrying")
                            self.lock_container.delete_item(
                                item=self.LOCK_DOCUMENT_ID,
                                partition_key=self.LOCK_DOCUMENT_ID,
                            )
                            time.sleep(0.2)  # Small delay after deletion
                            continue
                    # Lock exists and is not expired - wait and retry
                    elapsed = int(time.time() - start_time)
                    self.log.debug(
                        f"Lock held by another process, waiting... (elapsed: {elapsed}s)"
                    )
                    time.sleep(1)
                    continue

                except Exception as read_error:
                    # Document doesn't exist (404) or other error
                    error_str = str(read_error).lower()
                    if "not found" in error_str or "notfound" in error_str or "404" in error_str:
                        # Document doesn't exist, but creation failed - might be a timing issue
                        elapsed = int(time.time() - start_time)
                        self.log.debug(
                            f"Lock document not found after failed creation, retrying... (elapsed: {elapsed}s)"
                        )
                        time.sleep(0.5)
                        continue
                    else:
                        # Other error reading document
                        self.log.debug(f"Error reading lock document: {str(read_error)}")
                        time.sleep(1)
                        continue

            except Exception as e:
                error_str = str(e).lower()
                # Check if it's a conflict (document already exists)
                if "conflict" in error_str or "already exists" in error_str or "409" in error_str:
                    # Lock is held by another process, wait and retry
                    elapsed = int(time.time() - start_time)
                    self.log.debug(
                        f"Lock held by another process (conflict), waiting... (elapsed: {elapsed}s)"
                    )
                    time.sleep(1)
                    continue
                else:
                    # Unexpected error
                    self.log.warning(f"Error acquiring lock: {str(e)}")
                    time.sleep(1)
                    continue

        self.log.warning(f"Failed to acquire migration lock after {wait_timeout_seconds} seconds")
        return False

    def _create_lock_document(self) -> bool:
        """Create initial lock document.

        Uses create_item which will fail if document already exists (equivalent to unique constraint
        violation in SQL databases). This matches the pattern used by other providers.

        Returns:
            True if created successfully, False if document already exists (lock held)
        """
        try:
            username = os.environ.get("USER", os.environ.get("USERNAME", "unknown"))
            hostname = socket.gethostname()
            locked_by = f"{username}@{hostname}"

            expires_at = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(
                minutes=5
            )

            lock_doc = {
                "id": self.LOCK_DOCUMENT_ID,
                "schema": "default",
                "locked_by": locked_by,
                "locked_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                "expires_at": expires_at.isoformat(),
            }

            if self.lock_container is None:
                # Uninitialised container is an infra/setup bug.
                # Return False (matches the ``-> bool`` contract
                # callers expect) but log at error level so it
                # surfaces in operator output instead of being
                # silently treated as "lock held". (PR #241 Bugbot.)
                self.log.error(
                    "Lock container is not initialised; cannot create lock document. "
                    "Call create_migration_lock_container_if_not_exists() first. "
                    "Treating as 'lock not acquired'."
                )
                return False

            # Use create_item - will raise exception if document already exists
            # This matches the pattern: INSERT fails if unique constraint violated
            created_doc = self.lock_container.create_item(body=lock_doc)

            # Verify document was created successfully
            if created_doc and created_doc.get("id") == self.LOCK_DOCUMENT_ID:
                self.log.debug(f"Successfully created lock document: {self.LOCK_DOCUMENT_ID}")
                return True
            else:
                self.log.warning(
                    f"Lock document creation returned unexpected result: {created_doc}"
                )
                return False

        except Exception as e:
            # Check if it's a conflict (document already exists)
            error_str = str(e).lower()
            if "conflict" in error_str or "already exists" in error_str or "409" in error_str:
                # Document already exists - lock is held by another process
                self.log.debug("Lock document already exists (lock held by another process)")
                return False
            # For other errors, re-raise so caller can handle
            self.log.error(f"Error creating lock document: {str(e)} (type: {type(e).__name__})")
            raise

    def release_migration_lock(self, schema: str) -> bool:
        """Release migration lock.

        Args:
            schema: Schema name (not used in Cosmos DB, but kept for compatibility)

        Returns:
            True if lock released successfully, False otherwise
        """
        self.log.debug(f"Releasing migration lock for schema: {schema}")

        if not self.lock_container:
            self.lock_container = self.connection_manager.get_container_client(
                self.LOCK_CONTAINER_NAME
            )

        try:
            # Delete lock document
            if self.lock_container is None:
                raise RuntimeError("Lock container not initialized")
            self.lock_container.delete_item(
                item=self.LOCK_DOCUMENT_ID,
                partition_key=self.LOCK_DOCUMENT_ID,
            )

            self.log.debug("Migration lock released successfully")
            return True

        except Exception as e:
            # Lock might not exist or already released
            if "NotFound" in str(e) or "not found" in str(e).lower():
                self.log.debug("Lock document not found (may have been released already)")
                return True
            error_msg = f"Error releasing migration lock: {str(e)}"
            self.log.error(error_msg)
            return False
