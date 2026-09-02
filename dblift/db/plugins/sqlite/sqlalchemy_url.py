"""SQLAlchemy URL construction for the SQLite plugin."""

from typing import Any


def build_sqlalchemy_url(database_config: Any) -> str:
    """Build the SQLite SQLAlchemy URL from the plugin config object."""
    raw_url = getattr(database_config, "url", None)
    if isinstance(raw_url, str) and raw_url.startswith("sqlite://"):
        return raw_url
    configured_path = getattr(database_config, "path", None)
    configured_database = getattr(database_config, "database", None)
    path = configured_path or configured_database or ""
    if path == ":memory:":
        return "sqlite:///:memory:"
    return f"sqlite:///{path}"
