"""DuckDB-specific ``BaseDatabaseConfig`` subclass."""

from dataclasses import dataclass
from typing import Any, Dict, Optional

from config.database_config import BaseDatabaseConfig, register_database_type


# lint: allow-dialect-string: config type registration
@register_database_type("duckdb")
@dataclass
class DuckDBConfig(BaseDatabaseConfig):
    """Configuration for DuckDB connections.

    DuckDB is embedded/file-based (like SQLite): no server, no
    credentials, ``"main"`` default schema. Connections resolve to a
    file path (or ``:memory:``) rather than a host/port.
    """

    # DuckDB specific fields
    path: Optional[str] = None  # Path to the DuckDB file (or :memory: for in-memory)

    def __post_init__(self) -> None:
        """Resolve the file path from path/url/database and apply defaults."""
        super().__post_init__()

        if not self.path:
            if self.url:
                url = self.url
                if url.startswith("duckdb://"):
                    self.path = url[len("duckdb://") :]
                    if self.path == "/:memory:":
                        self.path = ":memory:"
                    if self.path.startswith("//"):
                        self.path = "/" + self.path.lstrip("/")
                else:
                    self.path = url
            elif self.database:
                self.path = self.database

        if not self.path:
            raise ValueError(
                "Database path is required for DuckDB (use 'path' or 'database' field)"
            )

        # DuckDB's default schema is 'main'; no credentials required.
        if not self.schema:
            self.schema = "main"
        if not self.username:
            self.username = ""
        if not self.password:
            self.password = ""

    def build_connection_string(self) -> str:
        """Build a DuckDB connection string (file path)."""
        return self.path or ""

    def build_database_url(self) -> str:
        """Build the DuckDB plugin-owned SQLAlchemy URL."""
        from db.provider_registry import ProviderRegistry

        return ProviderRegistry.build_sqlalchemy_url(self)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary with DuckDB specific parameters."""
        result = super().to_dict()
        result["path"] = self.path
        return result

    def get_connection_props(self) -> Dict[str, str]:
        """Get connection properties for DuckDB connection."""
        props: Dict[str, str] = {}
        if self.path:
            props["path"] = self.path
        return props
