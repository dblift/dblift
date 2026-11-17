"""SQLAlchemy URL construction for the SQLite plugin."""

from typing import Any

from dblift.config.file_path_anchoring import render_file_url


def build_sqlalchemy_url(database_config: Any) -> str:
    """Build the SQLite SQLAlchemy URL from the plugin config object."""
    raw_url = database_config.url
    if isinstance(raw_url, str) and raw_url.startswith("sqlite://"):
        return raw_url
    configured_path = getattr(database_config, "path", None)
    configured_database = database_config.database
    path = configured_path or configured_database or ""
    return render_file_url("sqlite", path)
