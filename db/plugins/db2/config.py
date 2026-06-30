"""IBM DB2-specific ``BaseDatabaseConfig`` subclass."""

from dataclasses import dataclass
from typing import Any, Dict, Optional

from config.database_config import BaseDatabaseConfig, register_database_type


# lint: allow-dialect-string: config type registration
@register_database_type("db2")
@dataclass
class Db2Config(BaseDatabaseConfig):
    """DB2 specific configuration."""

    # DB2 specific attributes
    collection: Optional[str] = None

    def __post_init__(self) -> None:
        super().__post_init__()
        self.type = "db2"  # lint: allow-dialect-string: config type identity

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary with DB2 specific parameters."""
        result = super().to_dict()
        result["collection"] = self.collection
        return result

    def build_connection_string(self) -> str:
        """Build a DB2 connection string for native drivers."""
        params = []
        if self.schema:
            params.append(f"currentSchema={self.schema}")
        if self.collection:
            params.append(f"collection={self.collection}")
        return self._build_standard_url("ibm_db_sa://", params, timeout_key="connectTimeout")

    def build_database_url(self) -> str:
        """Build the DB2 plugin-owned SQLAlchemy URL."""
        from db.provider_registry import ProviderRegistry

        return ProviderRegistry.build_sqlalchemy_url(self)

    def get_connection_props(self) -> Dict[str, str]:
        """Get connection properties for native DB2 connection.

        Returns DB2 specific connection properties.
        """
        props = super().get_connection_props()

        if self.schema:
            props["currentSchema"] = self.schema

        if self.collection:
            props["collection"] = self.collection

        return props
