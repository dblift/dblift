"""Snowflake-specific ``BaseDatabaseConfig`` subclass."""

from dataclasses import dataclass
from typing import Any, Dict, Optional

from config.database_config import BaseDatabaseConfig, register_database_type


# lint: allow-dialect-string: config type registration
@register_database_type("snowflake")
@dataclass
class SnowflakeConfig(BaseDatabaseConfig):
    """Configuration for Snowflake SQLAlchemy connections."""

    account: Optional[str] = None
    warehouse: Optional[str] = None
    role: Optional[str] = None
    authenticator: Optional[str] = None

    def __post_init__(self) -> None:
        """Resolve account/database/schema from Snowflake URL fields."""
        super().__post_init__()
        # lint: allow-dialect-string: config type identity
        self.type = "snowflake"

        if not self.account and self.host:
            self.account = str(self.host)

        database_value = getattr(self, "database", None)
        if database_value and "/" in str(database_value):
            database, schema = str(database_value).split("/", 1)
            self.database = database or None
            if schema and not getattr(self, "schema", ""):
                self.schema = schema

    def build_connection_string(self) -> str:
        """Build the Snowflake plugin-owned SQLAlchemy URL."""
        return self.build_database_url()

    def build_database_url(self) -> str:
        """Build the Snowflake SQLAlchemy URL through the provider registry."""
        from db.provider_registry import ProviderRegistry

        url: str = ProviderRegistry.build_sqlalchemy_url(self)
        return url

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary with Snowflake-specific parameters."""
        result: Dict[str, Any] = super().to_dict()
        result["account"] = self.account
        result["warehouse"] = self.warehouse
        result["role"] = self.role
        result["authenticator"] = self.authenticator
        return result

    def get_connection_props(self) -> Dict[str, str]:
        """Return Snowflake connection properties."""
        props: Dict[str, str] = super().get_connection_props()
        if self.account:
            props["account"] = self.account
        if self.warehouse:
            props["warehouse"] = self.warehouse
        if self.role:
            props["role"] = self.role
        if self.authenticator:
            props["authenticator"] = self.authenticator
        return props
