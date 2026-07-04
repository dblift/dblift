"""SQLAlchemy URL construction for the DuckDB plugin (duckdb_engine driver)."""

from typing import Any


def _file_target(database_config: Any) -> str:
    """Resolve the DuckDB file target from the config (path/database or :memory:)."""
    for attr in ("path", "database"):
        value = getattr(database_config, attr, None)
        if value:
            return str(value)
    return ":memory:"


def build_sqlalchemy_url(database_config: Any) -> str:
    """Build the DuckDB SQLAlchemy URL from the plugin config object.

    DuckDB is embedded/file-based; the ``duckdb_engine`` dialect uses
    ``duckdb:///<file>`` (and ``duckdb:///:memory:`` for in-memory).
    """
    raw_url = getattr(database_config, "url", None)
    if isinstance(raw_url, str) and raw_url:
        if raw_url.startswith(("duckdb://", "duckdb+")):
            return raw_url
        raise ValueError("DuckDB connections require a duckdb:// SQLAlchemy URL or a file path")

    target = _file_target(database_config)
    if target == ":memory:":
        return "duckdb:///:memory:"
    return f"duckdb:///{target}"
