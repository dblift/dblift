"""Oracle-specific ``BaseDatabaseConfig`` subclass."""

from dataclasses import dataclass
from typing import Any, Dict, Optional

from config.database_config import BaseDatabaseConfig, register_database_type


# lint: allow-dialect-string: config type registration
@register_database_type("oracle")
@dataclass
class OracleConfig(BaseDatabaseConfig):
    """Oracle specific configuration."""

    # Oracle specific attributes
    service_name: Optional[str] = None
    sid: Optional[str] = None

    def __post_init__(self) -> None:
        super().__post_init__()
        self.type = "oracle"  # lint: allow-dialect-string: config type identity
        if not self.service_name and self.extra_params.get("service_name"):
            self.service_name = str(self.extra_params["service_name"])
        if not self.sid and self.extra_params.get("sid"):
            self.sid = str(self.extra_params["sid"])
        if self.database and not self.service_name and not self.sid:
            self.service_name = self.database
        if not self.database:
            self.database = self.service_name or self.sid
        if not self.url and not self.service_name and not self.sid:
            raise ValueError("Oracle native connections require service_name or sid")

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary with Oracle specific parameters."""
        result = super().to_dict()
        result["service_name"] = self.service_name
        result["sid"] = self.sid
        return result

    def build_connection_string(self) -> str:
        """Build an Oracle connection string for native drivers."""
        return self.build_database_url()

    def build_database_url(self) -> str:
        """Build the Oracle plugin-owned SQLAlchemy URL."""
        from db.provider_registry import ProviderRegistry

        return ProviderRegistry.build_sqlalchemy_url(self)
