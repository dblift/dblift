"""Map a Django ``DATABASES`` entry to a SQLAlchemy URL / Engine for dblift."""

from __future__ import annotations

from typing import Any

from django.core.exceptions import ImproperlyConfigured
from sqlalchemy import create_engine
from sqlalchemy.engine import URL, Engine

_DRIVERS = {
    "postgresql": "postgresql+psycopg",
    "postgis": "postgresql+psycopg",
    "mysql": "mysql+pymysql",
    "sqlite3": "sqlite",
    "oracle": "oracle+oracledb",
}
_MSSQL_HINTS = ("mssql", "sql_server")


def _driver_for(engine_path: str) -> str:
    suffix = engine_path.rsplit(".", 1)[-1]
    if suffix in _DRIVERS:
        return _DRIVERS[suffix]
    if any(hint in engine_path for hint in _MSSQL_HINTS):
        return "mssql+pymssql"
    raise ImproperlyConfigured(
        f"dblift: unsupported Django DATABASES ENGINE '{engine_path}'. "
        "Supported: postgresql, mysql, sqlite3, oracle, mssql. "
        "Set DBLIFT_DATABASE_URL to override."
    )


def build_url(db: dict[str, Any]) -> URL:
    """Build a SQLAlchemy URL from one Django ``DATABASES`` entry."""
    driver = _driver_for(str(db.get("ENGINE", "")))
    name = str(db.get("NAME") or "")
    if driver == "sqlite":
        return URL.create("sqlite", database=name)
    port = db.get("PORT")
    return URL.create(
        driver,
        username=(db.get("USER") or None),
        password=(db.get("PASSWORD") or None),
        host=(db.get("HOST") or None),
        port=(int(port) if port else None),
        database=name,
    )


def build_engine(db: dict[str, Any]) -> Engine:
    """Build a SQLAlchemy Engine from one Django ``DATABASES`` entry."""
    return create_engine(build_url(db))
