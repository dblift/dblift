"""Database URL parsing utilities."""

import re
import urllib.parse
from typing import Optional


class DatabaseUrlParser:
    """Utility class for extracting connection information from database URLs."""

    @staticmethod
    def _is_legacy_url(database_url: str) -> bool:
        """Return True when the URL uses a removed legacy transport scheme."""
        return database_url.strip().lower().startswith("jdbc:")

    @staticmethod
    def parse_username(database_url: Optional[str]) -> Optional[str]:
        """Extract username from a database URL.

        Args:
            database_url: The database URL to parse

        Returns:
            Username if found in URL, None otherwise
        """
        if not database_url:
            return None
        if DatabaseUrlParser._is_legacy_url(database_url):
            return None
        parsed = urllib.parse.urlparse(database_url)
        if parsed.username:
            return urllib.parse.unquote(parsed.username)

        for param_name in ["user", "username"]:
            pattern = rf"[&?;]{param_name}=([^&;]*)"
            match = re.search(pattern, database_url, re.IGNORECASE)
            if match:
                return urllib.parse.unquote(match.group(1))

        return None

    @staticmethod
    def parse_password(database_url: Optional[str]) -> Optional[str]:
        """Extract password from a database URL.

        Args:
            database_url: The database URL to parse

        Returns:
            Password if found in URL, None otherwise
        """
        if not database_url:
            return None
        if DatabaseUrlParser._is_legacy_url(database_url):
            return None
        parsed = urllib.parse.urlparse(database_url)
        if parsed.password:
            return urllib.parse.unquote(parsed.password)

        for param_name in ["password", "pwd"]:
            pattern = rf"[&?;]{param_name}=([^&;]*)"
            match = re.search(pattern, database_url, re.IGNORECASE)
            if match:
                return urllib.parse.unquote(match.group(1))

        return None

    @staticmethod
    def parse_database_name(database_url: Optional[str]) -> Optional[str]:
        """Extract database name from a database URL.

        Args:
            database_url: The database URL to parse

        Returns:
            Database name if found in URL, None otherwise
        """
        if not database_url:
            return None
        if DatabaseUrlParser._is_legacy_url(database_url):
            return None

        parsed = urllib.parse.urlparse(database_url)
        if database_url.lower().startswith("ibm_db_sa://"):
            authority_and_path = database_url.split("://", 1)[1].split("?", 1)[0]
            if "/" not in authority_and_path:
                return None
            database = authority_and_path.split("/", 1)[1]
            return urllib.parse.unquote(database) if database else None
        # Lazy import to avoid a core -> db import cycle (mirrors
        # config/database_config.py).
        from db.provider_registry import ProviderRegistry

        # Native (SQLAlchemy-style) URLs carry the DB name in the path; the
        # plugin registry is the single source of truth for which schemes are
        # native (resolving aliases like postgres/mssql). ``.lower()`` matters:
        # urlparse does not lowercase a scheme that has a ``+driver`` suffix.
        native_scheme = parsed.scheme.split("+", 1)[0].lower()
        canonical = ProviderRegistry.canonical_dialect_name(native_scheme)
        if canonical and ProviderRegistry.is_native_dialect(canonical):
            database = parsed.path.lstrip("/")
            return urllib.parse.unquote(database) if database else None

        return None
