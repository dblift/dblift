"""SQL Server-specific ``BaseDatabaseConfig`` subclass."""

from dataclasses import dataclass
from typing import Any, Dict, Optional

from config.database_config import BaseDatabaseConfig, register_database_type


# lint: allow-dialect-string: config type registration
@register_database_type("sqlserver")
@dataclass
class SqlServerConfig(BaseDatabaseConfig):
    """SQL Server specific configuration."""

    # SQL Server specific attributes
    instance: Optional[str] = None
    encrypt: bool = False
    trust_server_certificate: bool = False
    integrated_security: bool = False

    def __post_init__(self) -> None:
        super().__post_init__()
        self.type = "sqlserver"  # lint: allow-dialect-string: config type identity

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary with SQL Server specific parameters."""
        result = super().to_dict()
        result.update(
            {
                "instance": self.instance,
                "encrypt": self.encrypt,
                "trust_server_certificate": self.trust_server_certificate,
                "integrated_security": self.integrated_security,
            }
        )
        return result

    def build_connection_string(self) -> str:
        """Build a SQL Server connection string for native drivers."""
        if self.url:
            return self.url

        conn_parts = []
        conn_parts.append("DRIVER={ODBC Driver 17 for SQL Server}")
        server_host = self.host or "localhost"
        conn_parts.append(
            f"SERVER={server_host},{self.port}" if self.port else f"SERVER={server_host}"
        )

        if self.database:
            conn_parts.append(f"DATABASE={self.database}")

        # Authentication
        if not self.integrated_security:
            conn_parts.append(f"UID={self.username}")
            conn_parts.append(f"PWD={self.password}")
        else:
            conn_parts.append("Trusted_Connection=Yes")

        # Additional options
        if self.trust_server_certificate:
            conn_parts.append("TrustServerCertificate=Yes")

        if not self.encrypt:
            conn_parts.append("Encrypt=No")

        conn_parts.append(f"Connection Timeout={self.connection_timeout}")

        # Add instance if specified
        if self.instance:
            conn_parts.append(f"INSTANCE={self.instance}")

        # Add any extra parameters
        if self.extra_params:
            for key, value in self.extra_params.items():
                conn_parts.append(f"{key}={value}")

        return ";".join(conn_parts)

    def build_database_url(self) -> str:
        """Build the SQL Server plugin-owned SQLAlchemy URL."""
        from db.provider_registry import ProviderRegistry

        return ProviderRegistry.build_sqlalchemy_url(self)

    def get_connection_props(self) -> Dict[str, str]:
        """Get connection properties for database connection.

        Returns SQL Server specific connection properties.
        """
        props = super().get_connection_props()

        if self.integrated_security:
            props.pop("user", None)
            props.pop("password", None)
            props["integratedSecurity"] = "true"
        else:
            # Explicitly set integratedSecurity to false if not using it
            props["integratedSecurity"] = "false"
            # Use SqlPassword as the authentication scheme
            props["authenticationScheme"] = "SqlPassword"

        # SSL/Encryption settings - ensure compatibility with SQL Server 2022
        props["trustServerCertificate"] = "true" if self.trust_server_certificate else "false"

        props["encrypt"] = "true" if self.encrypt else "false"

        # Add application name for monitoring and debugging
        props["applicationName"] = "Dblift"

        # Add options to help troubleshoot connection issues
        props["lastUpdateCount"] = "true"
        props["xopenStates"] = "true"
        props["sendTimeAsDatetime"] = "true"

        return props
