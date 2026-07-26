"""
SQLite connection management.

This module handles SQLite database connection creation using Python's
native sqlite3 module.
"""

import sqlite3
from os.path import abspath
from pathlib import Path
from typing import Optional

from config import DbliftConfig
from core.logger import Log, NullLog
from db.plugins.sqlite.config import sqlite_path_from_url


class SQLiteConnectionManager:
    """Manages SQLite connections using Python's native sqlite3 module."""

    def __init__(self, config: DbliftConfig, log: Optional[Log] = None) -> None:
        """Initialize the connection manager.

        Args:
            config: Application configuration
            log: Optional logger
        """
        self.config: DbliftConfig = config
        self.log: Log = log if log is not None else NullLog()
        self._connection: Optional[sqlite3.Connection] = None

        # Validate required configuration
        # SQLite uses 'database' as the file path, or 'path' for the database file
        self.db_path = self._get_database_path()

    def _get_database_path(self) -> str:
        """Get the database file path from configuration.

        Returns:
            str: Path to SQLite database file

        Raises:
            ValueError: If database path is not specified
        """
        # Try different configuration options for database path
        if hasattr(self.config.database, "path") and self.config.database.path:
            path_value = self.config.database.path
            return str(path_value) if path_value is not None else ""

        if hasattr(self.config.database, "database") and self.config.database.database:
            return self.config.database.database

        if hasattr(self.config.database, "url") and self.config.database.url:
            # Handle sqlite:// URLs through the single shared parser so this
            # native sqlite3 connection and the SQLAlchemy engine built by
            # ``build_sqlalchemy_url`` always resolve the same file. See
            # ``sqlite_path_from_url``'s docstring for why SQLAlchemy's
            # convention (three slashes relative, four absolute) is the one
            # to agree with, rather than RFC 3986's.
            url = self.config.database.url
            if url.startswith("sqlite://"):
                return sqlite_path_from_url(url)

        raise ValueError(
            "SQLite database path is required. "
            "Specify 'path', 'database', or 'url' (sqlite:///path/to/db.sqlite) in configuration."
        )

    def create_connection(self) -> sqlite3.Connection:
        """Create a connection to SQLite database.

        Returns:
            sqlite3.Connection: SQLite connection object
        """
        self.log.debug(f"Connecting to SQLite database: {self.db_path}")

        try:
            # Handle special case for in-memory databases
            if self.db_path == ":memory:":
                db_file = ":memory:"
            else:
                # Ensure parent directory exists for file-based databases
                db_path_obj = Path(self.db_path)
                if db_path_obj.parent and not db_path_obj.parent.exists():
                    db_path_obj.parent.mkdir(parents=True, exist_ok=True)
                db_file = str(db_path_obj)

            # Create connection with row factory for dict-like row access
            connection = sqlite3.connect(
                db_file,
                detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES,
                isolation_level=None,  # Autocommit Python mode; transactions controlled via explicit BEGIN/COMMIT SQL
                check_same_thread=False,  # Allow multi-threaded access
            )

            # Enable row factory for easier result handling
            connection.row_factory = sqlite3.Row

            # Enable foreign keys (disabled by default in SQLite)
            connection.execute("PRAGMA foreign_keys = ON")

            # Store connection for version queries
            self._connection = connection

            version_info = self._get_database_version(connection)
            self.log.debug(f"Connected to SQLite database ({version_info})")

            return connection

        except Exception as e:
            error_msg = f"Failed to connect to SQLite database: {str(e)}"
            self.log.error(error_msg)
            raise

    def _get_database_version(self, connection: sqlite3.Connection) -> str:
        """Get SQLite database version information.

        Args:
            connection: SQLite connection

        Returns:
            str: SQLite version string
        """
        try:
            cursor = connection.execute("SELECT sqlite_version()")
            row = cursor.fetchone()
            if row:
                return f"SQLite {row[0]}"
            return "SQLite (unknown version)"
        except Exception as e:
            self.log.warning(f"Could not determine SQLite version: {str(e)}")
            return "SQLite (unknown version)"

    def get_database_url(self) -> str:
        """Return a ``sqlite://`` URI for display in the command banner.

        SQLite uses Python's native ``sqlite3`` module. The banner at
        ``base_command.py:_format_command_header`` calls this method via
        ``hasattr`` to render the "Database URL" line;
        returning a canonical ``sqlite://`` URI gives the operator a
        meaningful value instead of ``<not available>`` (BUG-08).

        Relative paths are resolved to absolute before being embedded in the
        URI. Per RFC 3986 a URI like ``sqlite://data/local.db`` has
        ``data`` as its authority component and ``/local.db`` as its path —
        which ``base_command.py``'s ``://([^:/]+)`` regex would mis-extract
        as a server name. Resolving to an absolute path guarantees the
        leading ``/`` after ``sqlite://`` so the authority is always empty.
        """
        if self.db_path == ":memory:":
            return "sqlite:///:memory:"
        return f"sqlite://{abspath(self.db_path)}"

    def close(self) -> None:
        """Close the SQLite connection."""
        if self._connection:
            try:
                self._connection.close()
                self.log.debug("SQLite connection closed")
            except Exception as e:
                self.log.warning(f"Error closing SQLite connection: {str(e)}")
            finally:
                self._connection = None
