"""SQLite-specific ``BaseDatabaseConfig`` subclass."""

from dataclasses import dataclass
from typing import Any, Dict, Optional

from config.database_config import BaseDatabaseConfig, register_database_type


@register_database_type("sqlite")  # lint: allow-dialect-string: config type registration
@register_database_type("sqlite3")  # lint: allow-dialect-string: config type registration
@dataclass
class SQLiteConfig(BaseDatabaseConfig):
    """Configuration for SQLite database connections.

    SQLite is a file-based database that doesn't require a server.
    It uses Python's built-in sqlite3 module for connections.
    """

    # SQLite specific fields
    path: Optional[str] = None  # Path to SQLite database file (or :memory: for in-memory)

    def __post_init__(self) -> None:
        """Post-initialization validation and setup."""
        super().__post_init__()

        # Determine database path from various sources
        if not self.path:
            # Check if path is in url field; strip sqlite:// prefix so the path
            # field always contains a bare file system path (or :memory:).
            # Per RFC 3986, ``sqlite:///tmp/x.db`` is scheme=sqlite, authority=""
            # (between the second and third slash), path=/tmp/x.db — i.e. the
            # leading slash belongs to the path and MUST be preserved.
            if self.url:
                url = self.url
                if url.startswith("sqlite://"):
                    self.path = url[9:]
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
                "Database path is required for SQLite (use 'path' or 'database' field)"
            )

        # Set default schema to 'main' (SQLite's default schema name)
        if not self.schema:
            self.schema = "main"

        # SQLite doesn't require username/password
        if not self.username:
            self.username = ""
        if not self.password:
            self.password = ""

    def build_connection_string(self) -> str:
        """Build a SQLite connection string (file path).

        Note: SQLite uses file paths, not traditional connection strings.
        """
        return self.path or ""

    def build_database_url(self) -> str:
        """Build a SQLite connection URL.

        Note: This method provides a consistent interface for configuration display.
        """
        return f"sqlite:///{self.path}"

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary with SQLite specific parameters."""
        result = super().to_dict()
        result["path"] = self.path
        return result

    def get_connection_props(self) -> Dict[str, str]:
        """Get connection properties for SQLite connection."""
        props = {}

        if self.path:
            props["path"] = self.path

        return props
