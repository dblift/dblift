"""SQLite-specific ``BaseDatabaseConfig`` subclass."""

from dataclasses import dataclass
from typing import Any, Dict, Optional

import sqlalchemy

from config.database_config import BaseDatabaseConfig, register_database_type


def sqlite_path_from_url(url: str) -> str:
    """Resolve a ``sqlite://`` URL to a file path, in agreement with SQLAlchemy.

    dblift used to strip the literal ``sqlite://`` prefix and RFC-3986-parse
    what remained: authority is empty (nothing between the second and third
    slash), so the leading slash of what follows belongs to the path — that
    reading resolves ``sqlite:///release.db`` to ``/release.db``, the
    filesystem root. That reading is defensible in isolation. What is not
    defensible is that dblift held *both* readings at once:
    :func:`db.plugins.sqlite.sqlalchemy_url.build_sqlalchemy_url` fed the same
    string to SQLAlchemy, which resolves it relatively, so the SQLAlchemy
    engine and the native ``sqlite3`` connection addressed two different
    files for one config. The disagreement was the bug, not the RFC-3986
    reading.

    SQLAlchemy's convention wins because it is the one users already know —
    every SQLAlchemy tutorial writes ``sqlite:///file.db`` meaning "the file
    next to me" — and because it's the convention dblift's own URL builder
    already emits. Delegating the parsing to SQLAlchemy's own
    ``make_url`` — rather than re-implementing "three slashes is relative,
    four is absolute" by hand — is what makes the two paths structurally
    unable to drift apart again: there is only one parser now, not two
    implementations of the same rule.
    """
    return sqlalchemy.engine.make_url(url).database or ""


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
            # Check if path is in url field. ``sqlite_path_from_url`` is the
            # single place dblift parses a ``sqlite://`` URL — see its
            # docstring for why this must agree with SQLAlchemy's own
            # resolution rather than RFC 3986's.
            if self.url:
                url = self.url
                if url.startswith("sqlite://"):
                    self.path = sqlite_path_from_url(url)
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
