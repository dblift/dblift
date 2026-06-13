"""SQLAlchemy URL construction for the {{cookiecutter.dialect_name}} plugin.

Per ADR-0026: the URL builder lives inside the plugin. Core and config
contain no central dialect-to-URL maps or if/elif ladders.
"""

from typing import Any


def build_sqlalchemy_url(database_config: Any) -> str:
    """Build the SQLAlchemy URL from the plugin config object.

    This is the minimal starting implementation. Extend it to handle
    raw .url, driver selection, extra query params, ssl, schema etc.
    exactly as your first-party equivalents do (see postgresql/sqlalchemy_url.py
    or sqlite/sqlalchemy_url.py for patterns).
    """
    raw_url = getattr(database_config, "url", None)
    if isinstance(raw_url, str) and raw_url:
        return raw_url

    # Very basic example assuming common config fields.
    # Real implementation must be owned by this plugin.
    username = getattr(database_config, "username", None) or None
    password = getattr(database_config, "password", None) or None
    host = getattr(database_config, "host", None) or "localhost"
    port = getattr(database_config, "port", None)
    database = getattr(database_config, "database", None) or getattr(database_config, "path", None) or ""

    if username:
        auth = f"{username}:{password}@" if password else f"{username}@"
    else:
        auth = ""

    port_part = f":{port}" if port else ""
    db_part = f"/{database}" if database else ""
    return f"{{cookiecutter.dialect_name}}://{auth}{host}{port_part}{db_part}"
