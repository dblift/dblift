"""SQLAlchemy dialect for CockroachDB (PostgreSQL wire, CRDB version banner).

SQLAlchemy's stock PostgreSQL dialect requires a ``PostgreSQL X.Y`` (or
``EnterpriseDB``) prefix from ``select version()``. CockroachDB returns banners
like::

    CockroachDB CCL v24.3.18 (x86_64-pc-linux-gnu, built 2025/08/07 22:44:01, go1.22.8 ...)

which raise ``AssertionError: Could not determine version from string`` on every
``create_engine`` connect. This dialect reuses the psycopg PostgreSQL dialect
and only overrides server-version parsing so the product version ``vX.Y.Z`` is
used — never the trailing ``go1.x.y`` fragment.
"""

from __future__ import annotations

import re
from typing import Any, Optional, Tuple

from sqlalchemy.dialects.postgresql.psycopg import PGDialect_psycopg

# Prefer an explicit product "vMAJOR.MINOR[.PATCH]" token (CRDB's usual form).
_CRDB_V_TOKEN = re.compile(r"\bv(\d+)\.(\d+)(?:\.(\d+))?\b", re.IGNORECASE)
# Fallback when the banner omits the leading ``v`` (older strings).
_CRDB_DOTTED = re.compile(
    r"CockroachDB(?:\s+CCL)?\s+(\d+)\.(\d+)(?:\.(\d+))?",
    re.IGNORECASE,
)

_registered = False


def parse_cockroach_server_version(banner: str) -> Tuple[int, ...]:
    """Return ``(major, minor[, patch])`` from a CockroachDB ``version()`` banner.

    Raises:
        AssertionError: when no product version can be extracted (same shape as
            SQLAlchemy's PostgreSQL dialect failure).
    """
    text = banner or ""
    match = _CRDB_V_TOKEN.search(text)
    if match is None:
        match = _CRDB_DOTTED.search(text)
    if match is None:
        raise AssertionError(f"Could not determine version from string '{banner}'")
    major = int(match.group(1))
    minor = int(match.group(2))
    patch = match.group(3)
    if patch is not None:
        return (major, minor, int(patch))
    return (major, minor)


class CockroachDBDialect_psycopg(PGDialect_psycopg):
    """PostgreSQL+psycopg dialect that accepts CockroachDB version banners."""

    name = "cockroachdb"
    driver = "psycopg"
    # Inherit PG caching semantics; SQLAlchemy warns if a subclass omits this.
    supports_statement_cache = True

    def _get_server_version_info(self, connection: Any) -> Tuple[int, ...]:
        raw = connection.exec_driver_sql("select version()").scalar()
        return parse_cockroach_server_version(str(raw) if raw is not None else "")


def register_cockroach_dialect() -> None:
    """Register ``cockroachdb`` / ``cockroachdb.psycopg`` with SQLAlchemy once."""
    global _registered
    if _registered:
        return
    from sqlalchemy.dialects import registry

    registry.register(
        "cockroachdb",
        "db.plugins.cockroachdb.sqlalchemy_dialect",
        "CockroachDBDialect_psycopg",
    )
    registry.register(
        "cockroachdb.psycopg",
        "db.plugins.cockroachdb.sqlalchemy_dialect",
        "CockroachDBDialect_psycopg",
    )
    _registered = True


def ensure_cockroach_drivername(drivername: str) -> str:
    """Map a PostgreSQL-family drivername onto ``cockroachdb+psycopg``.

    Only the ``psycopg`` DBAPI is registered for CockroachDB. Bare
    ``postgresql`` / ``postgres`` / ``cockroachdb`` names and ``+psycopg``
    variants rewrite cleanly; any other driver suffix (e.g. ``asyncpg``)
    raises so ``create_engine`` does not fail later with an unloadable dialect.
    """
    if drivername in (
        "cockroachdb",
        "cockroachdb+psycopg",
        "postgresql",
        "postgres",
        "postgresql+psycopg",
        "postgres+psycopg",
    ):
        return "cockroachdb+psycopg"
    if drivername.startswith(("postgresql+", "postgres+", "cockroachdb+")):
        suffix = drivername.split("+", 1)[1]
        if suffix != "psycopg":
            raise ValueError(
                "CockroachDB native connections require the psycopg driver "
                f"(got {drivername!r}); use cockroachdb+psycopg or "
                "postgresql+psycopg"
            )
        return "cockroachdb+psycopg"
    raise ValueError(
        "CockroachDB native connections require a PostgreSQL/CockroachDB "
        f"SQLAlchemy URL (got drivername {drivername!r})"
    )


__all__ = [
    "CockroachDBDialect_psycopg",
    "ensure_cockroach_drivername",
    "parse_cockroach_server_version",
    "register_cockroach_dialect",
]
