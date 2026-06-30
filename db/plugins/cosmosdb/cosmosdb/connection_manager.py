"""
Cosmos DB connection management using Azure SDK.

This module handles Azure Cosmos DB connections using the Azure SDK for Python.
"""

import time
import urllib.parse
from typing import TYPE_CHECKING, Any, Dict, Optional

from config import DbliftConfig
from core.logger import Log, NullLog

if TYPE_CHECKING:
    from azure.cosmos import CosmosClient, DatabaseProxy


class CosmosDbConnectionManager:
    """Manages Cosmos DB connections using Azure SDK."""

    def __init__(self, config: DbliftConfig, log: Optional[Log] = None):
        """Initialize the connection manager.

        Args:
            config: Application configuration
            log: Optional logger
        """
        self.config = config
        self.log = log if log is not None else NullLog()
        self.client: Optional["CosmosClient"] = None
        self.database: Optional["DatabaseProxy"] = None

        # Validate required configuration
        # account_endpoint can come from url or account_endpoint field
        account_endpoint = getattr(config.database, "account_endpoint", None) or config.database.url
        if not account_endpoint:
            raise ValueError("Cosmos DB account_endpoint is required (set account_endpoint or url)")

        # database_name can come from database_name or database field
        database_name = getattr(config.database, "database_name", None) or getattr(
            config.database, "database", None
        )
        if not database_name:
            raise ValueError("Cosmos DB database_name is required")

    def _is_emulator_endpoint(self, endpoint: str) -> bool:
        """Check if the endpoint is the Azure Cosmos DB Emulator.

        Args:
            endpoint: Cosmos DB account endpoint URL

        Returns:
            True if this is an emulator endpoint (localhost)
        """
        try:
            parsed = urllib.parse.urlparse(endpoint)
            hostname = parsed.hostname or ""
            # Emulator typically runs on localhost
            return hostname in ["localhost", "127.0.0.1"] or "localhost" in hostname.lower()
        except (AttributeError, ValueError):
            # Intentional: urllib.parse.urlparse raises ValueError on malformed input;
            # AttributeError covers .hostname / .lower() access patterns when a caller
            # passes a non-string. Narrower than `except Exception:` so programming
            # bugs (KeyError, NameError, TypeError) surface in tests instead of being
            # silently classified as "non-local endpoint".
            return False

    def create_connection(self) -> Any:
        """Create Cosmos DB connection using Azure SDK.

        Returns:
            DatabaseProxy instance
        """
        # Type guard: ensure we have CosmosDbConfig
        from db.plugins.cosmosdb.config import CosmosDbConfig

        if not isinstance(self.config.database, CosmosDbConfig):
            raise TypeError("Expected CosmosDbConfig for Cosmos DB provider")

        cosmos_config: CosmosDbConfig = self.config.database

        self.log.debug(
            f"Connecting to Cosmos DB: {cosmos_config.account_endpoint or cosmos_config.url}"
        )

        # Get account endpoint (from account_endpoint field or url)
        account_endpoint = cosmos_config.account_endpoint or cosmos_config.url
        if not account_endpoint:
            raise ValueError("Cosmos DB account_endpoint is required")

        # Check if this is the emulator (localhost) - disable SSL verification for emulator
        is_emulator = self._is_emulator_endpoint(account_endpoint)
        if is_emulator:
            import urllib3

            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
            self.log.debug(
                "Detected Cosmos DB Emulator - SSL verification scoped to connection only"
            )

        try:
            from azure.cosmos import CosmosClient

            # Determine if we're using HTTPS (for connection_verify parameter)
            parsed_endpoint = urllib.parse.urlparse(account_endpoint)
            is_https = parsed_endpoint.scheme.lower() == "https"

            if cosmos_config.use_managed_identity:
                # Use DefaultAzureCredential for managed identity
                from azure.identity import DefaultAzureCredential

                credential = DefaultAzureCredential()
                client_kwargs: Dict[str, Any] = {
                    "url": account_endpoint,
                    "credential": credential,
                    "connection_timeout": 10,
                    "read_timeout": 30,
                }
                # Only disable SSL verification for emulator HTTPS endpoints
                if is_emulator and is_https:
                    client_kwargs["connection_verify"] = False
                self.client = CosmosClient(**client_kwargs)
            else:
                # Use account key
                if not cosmos_config.account_key:
                    raise ValueError("account_key is required when use_managed_identity is False")

                client_kwargs = {
                    "url": account_endpoint,
                    "credential": cosmos_config.account_key,
                    # Prevent indefinite hangs when the emulator drops connections
                    # (RemoteDisconnected under parallel-test load).
                    "connection_timeout": 10,
                    "read_timeout": 30,
                }
                # Only disable SSL verification for emulator HTTPS endpoints
                if is_emulator and is_https:
                    client_kwargs["connection_verify"] = False
                self.client = CosmosClient(**client_kwargs)

            # Get database name (from database_name field or database field)
            database_name = cosmos_config.database_name or cosmos_config.database
            if not database_name:
                raise ValueError("Cosmos DB database_name is required")

            # Create database if it doesn't exist, or get existing database
            # This is idempotent - will return existing database if it exists
            # Add retry logic for emulator which may need time for backend services to initialize
            max_retries = 6 if is_emulator else 1
            retry_delay = 3.0  # seconds

            for attempt in range(max_retries):
                try:
                    if self.client is None:
                        raise RuntimeError("Cosmos DB client not initialized")
                    database = self.client.create_database_if_not_exists(id=database_name)
                    if database is None:
                        raise RuntimeError(
                            f"Failed to create or access Cosmos DB database '{database_name}'"
                        )
                    self.database = database
                    self.log.debug(f"Connected to Cosmos DB database: {database_name}")
                    break  # Success, exit retry loop
                except Exception as e:
                    error_str = str(e).lower()
                    # Check if this is a transient connection error (retryable with emulator)
                    is_backend_error = (
                        "connection refused" in error_str
                        or "connection aborted" in error_str
                        or "remotedisconnected" in error_str
                        or "remote end closed" in error_str
                        or "poolerror" in error_str
                        or "backend" in error_str
                        or "status code: 500" in error_str
                        or "status code: 503" in error_str
                    )

                    if is_backend_error and attempt < max_retries - 1:
                        # Backend services might not be ready yet, retry
                        self.log.debug(
                            f"Backend connection error (attempt {attempt + 1}/{max_retries}), "
                            f"retrying in {retry_delay}s: {str(e)}"
                        )
                        time.sleep(retry_delay)
                        continue
                    else:
                        # Not a retryable error or out of retries
                        error_msg = f"Failed to create or access Cosmos DB database '{database_name}': {str(e)}"
                        self.log.error(error_msg)
                        raise RuntimeError(error_msg) from e

            if self.database is None:
                raise RuntimeError("Database should be initialized after retry loop")
            return self.database

        except ImportError:
            error_msg = (
                "Azure Cosmos DB SDK not installed. "
                "Install it with: pip install azure-cosmos azure-identity"
            )
            self.log.error(error_msg)
            raise ImportError(error_msg)
        except Exception as e:
            error_msg = f"Failed to connect to Cosmos DB: {str(e)}"
            self.log.error(error_msg)
            raise

    def get_container_client(self, container_name: str) -> Any:
        """Get container client.

        Args:
            container_name: Name of the container

        Returns:
            ContainerProxy instance
        """
        if self.database is None:
            self.create_connection()
        if self.database is None:
            raise RuntimeError("Database should be initialized after create_connection()")
        return self.database.get_container_client(container_name)

    def get_database_url(self) -> Optional[str]:
        """Get Cosmos DB database URL (connection endpoint).

        Returns:
            Database URL string, or None if not available
        """
        # Get account endpoint from config
        account_endpoint = (
            getattr(self.config.database, "account_endpoint", None) or self.config.database.url
        )
        if account_endpoint:
            # Mask account key if present in URL
            url = str(account_endpoint)
            # If account key is in the URL, mask it
            if "accountKey=" in url:
                url = url.split("accountKey=")[0] + "accountKey=***"
            return url
        return None

    def close(self) -> None:
        """Close the Cosmos DB connection."""
        # Cosmos DB client doesn't need explicit closing, but we can clear references
        self.client = None
        self.database = None
        self.log.debug("Cosmos DB connection closed")
