"""MySQL/MariaDB-specific ``BaseDatabaseConfig`` subclass.

MariaDB shares this config class via the ``_MYSQL_FAMILY`` membership check
in :meth:`MySqlConfig.__post_init__`. The plugin registry resolves
``mariadb`` -> ``mysql`` for the config class via ``PluginInfo.config_dialect``.
"""

from dataclasses import dataclass
from typing import Any, Dict

from config.database_config import BaseDatabaseConfig, register_database_type


# lint: allow-dialect-string: config type registration
@register_database_type("mysql")
@dataclass
class MySqlConfig(BaseDatabaseConfig):
    """MySQL specific configuration."""

    # MySQL specific attributes
    ssl_enabled: bool = False

    # Dialects that share this config class (mariadb inherits MySQL config).
    # lint: allow-dialect-string: config family membership
    _MYSQL_FAMILY = frozenset({"mysql", "mariadb"})

    def __post_init__(self) -> None:
        super().__post_init__()
        # Preserve the exact dialect (e.g. "mariadb") so ProviderRegistry
        # can resolve the right quirks / provider. Fall back to "mysql"
        # only when the type is unset or not a MySQL-family dialect.
        if self.type not in self._MYSQL_FAMILY:
            self.type = "mysql"  # lint: allow-dialect-string: config type identity

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary with MySQL specific parameters."""
        result = super().to_dict()
        result["ssl_enabled"] = self.ssl_enabled
        return result

    def build_connection_string(self) -> str:
        """Build a MySQL connection string for native drivers."""
        params = []
        if self.schema:
            params.append(f"schema={self.schema}")
        if self.ssl_enabled:
            params.append("useSSL=true")
        return self._build_standard_url("mysql://", params)

    def build_database_url(self) -> str:
        """Build the MySQL-family plugin-owned SQLAlchemy URL."""
        from db.provider_registry import ProviderRegistry

        return ProviderRegistry.build_sqlalchemy_url(self)

    def get_connection_props(self) -> Dict[str, str]:
        """Get connection properties for database connection.

        Returns MySQL specific connection properties.
        """
        props = super().get_connection_props()

        # Merge options map into properties
        if self.options:
            for k, v in self.options.items():
                props[str(k)] = str(v)

        # Encode session variables (if not already provided)
        if self.session_variables and "sessionVariables" not in props:
            kv = ",".join(f"{k}={v}" for k, v in self.session_variables.items())
            props["sessionVariables"] = kv

        # Sensible defaults for local containers unless explicitly overridden
        props.setdefault("allowPublicKeyRetrieval", "true")
        # Only set useSSL if not explicitly configured
        if "useSSL" not in props:
            props["useSSL"] = "true" if self.ssl_enabled else "false"
        props.setdefault("serverTimezone", "UTC")

        # Force native password plugin for compatibility with some MySQL images/driver combos
        # These can be overridden via options or extra_params if desired
        props.setdefault(
            "defaultAuthenticationPlugin",
            "com.mysql.cj.protocol.a.authentication.MysqlNativePasswordPlugin",
        )
        props.setdefault(
            "authenticationPlugins",
            "com.mysql.cj.protocol.a.authentication.MysqlNativePasswordPlugin",
        )

        return props
