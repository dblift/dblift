"""PostgreSQL-specific ``BaseDatabaseConfig`` subclass."""

from dataclasses import dataclass
from typing import Any, Dict, Optional

from config.database_config import BaseDatabaseConfig, register_database_type


# lint: allow-dialect-string: config type registration
@register_database_type("postgresql")
@dataclass
class PostgreSqlConfig(BaseDatabaseConfig):
    """PostgreSQL specific configuration."""

    # PostgreSQL specific attributes
    ssl_mode: Optional[str] = None

    def __post_init__(self) -> None:
        super().__post_init__()
        self.type = "postgresql"  # lint: allow-dialect-string: config type identity

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary with PostgreSQL specific parameters."""
        result = super().to_dict()
        result["ssl_mode"] = self.ssl_mode
        return result

    def build_connection_string(self) -> str:
        """Build a PostgreSQL connection string for native drivers."""
        params = []
        if self.schema:
            params.append(f"search_path={self.schema}")
        if self.ssl_mode:
            params.append(f"sslmode={self.ssl_mode}")
        return self._build_standard_url("postgresql://", params)

    def build_database_url(self) -> str:
        """Build the PostgreSQL plugin-owned SQLAlchemy URL."""
        from db.provider_registry import ProviderRegistry

        return ProviderRegistry.build_sqlalchemy_url(self)

    def get_connection_props(self) -> Dict[str, str]:
        """Get connection properties for database connection.

        Returns PostgreSQL specific connection properties.
        """
        props = super().get_connection_props()

        if self.schema:
            props["currentSchema"] = self.schema

        if self.ssl_mode:
            props["sslmode"] = self.ssl_mode

        return props
