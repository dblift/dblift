"""Azure Cosmos DB-specific ``BaseDatabaseConfig`` subclass."""

from dataclasses import dataclass
from typing import Any, Dict, Optional

from config.database_config import BaseDatabaseConfig, register_database_type


# lint: allow-dialect-string: config type registration
@register_database_type("cosmosdb")
@dataclass
class CosmosDbConfig(BaseDatabaseConfig):
    """Configuration for Azure Cosmos DB connections."""

    # Cosmos DB specific fields
    account_endpoint: Optional[str] = None  # Cosmos DB account endpoint URL
    account_key: Optional[str] = None  # Account key for authentication
    database_name: Optional[str] = None  # Cosmos DB database name
    container_name: Optional[str] = None  # Default container name
    use_managed_identity: bool = False  # Use Azure managed identity for authentication

    def __post_init__(self) -> None:
        """Post-initialization validation and setup."""
        super().__post_init__()

        # Validate required fields
        if not self.account_endpoint and not self.url:
            raise ValueError("Either account_endpoint or url must be provided for Cosmos DB")

        if not self.use_managed_identity and not self.account_key:
            raise ValueError("account_key is required when use_managed_identity is False")

        if not self.database_name and not self.database:
            raise ValueError("Either database_name or database must be provided for Cosmos DB")

        # Set defaults from url/database fields if specific fields not provided
        if not self.account_endpoint and self.url:
            self.account_endpoint = self.url

        if not self.database_name and self.database:
            self.database_name = self.database

        if not self.account_key and self.password:
            self.account_key = self.password

    def build_connection_string(self) -> str:
        """Build a Cosmos DB connection string.

        Note: Cosmos DB doesn't use traditional connection strings,
        but this method provides a consistent interface.
        """
        endpoint = self.account_endpoint or self.url
        if not endpoint:
            raise ValueError("Cosmos DB account endpoint is required")

        return f"cosmosdb://{endpoint}/{self.database_name or self.database}"

    def build_database_url(self) -> str:
        """Build a Cosmos DB connection URL.

        Note: This method provides a consistent interface for configuration display.
        """
        return self.build_connection_string()

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary with Cosmos DB specific parameters."""
        result = super().to_dict()
        # Add Cosmos DB specific fields
        result["account_endpoint"] = self.account_endpoint
        result["account_key"] = self.account_key
        result["database_name"] = self.database_name
        result["container_name"] = self.container_name
        result["use_managed_identity"] = self.use_managed_identity
        return result

    def get_connection_props(self) -> Dict[str, str]:
        """Get connection properties for Cosmos DB connection."""
        props = {}

        if self.account_endpoint or self.url:
            props["account_endpoint"] = self.account_endpoint or self.url

        if self.account_key:
            props["account_key"] = self.account_key

        if self.database_name or self.database:
            props["database_name"] = str(self.database_name or self.database)

        if self.container_name:
            props["container_name"] = self.container_name

        props["use_managed_identity"] = str(self.use_managed_identity).lower()

        return props
