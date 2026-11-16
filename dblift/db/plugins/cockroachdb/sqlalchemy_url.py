"""SQLAlchemy URL construction for CockroachDB.

Reuses the PostgreSQL URL shape (host/user/sslmode/search_path) but forces the
``cockroachdb+psycopg`` drivername so SQLAlchemy loads
:class:`CockroachDBDialect_psycopg` instead of the stock PostgreSQL dialect
that cannot parse CockroachDB ``version()`` banners.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.engine import make_url

from dblift.db.plugins.cockroachdb.sqlalchemy_dialect import (
    ensure_cockroach_drivername,
    register_cockroach_dialect,
)
from dblift.db.plugins.postgresql.sqlalchemy_url import _query_mapping
from dblift.db.sqlalchemy_url_utils import merge_config_credentials, render_url_from_config


def build_sqlalchemy_url(database_config: Any) -> str:
    """Build a CockroachDB SQLAlchemy URL (psycopg driver, CRDB dialect)."""
    register_cockroach_dialect()

    raw_url = database_config.url
    if isinstance(raw_url, str) and raw_url:
        # Same scheme gate as the PostgreSQL builder, plus cockroachdb:// so a
        # pre-rewritten URL still validates. Other schemes raise immediately.
        if not raw_url.startswith(
            (
                "postgresql://",
                "postgresql+",
                "postgres://",
                "postgres+",
                "cockroachdb://",
                "cockroachdb+",
            )
        ):
            raise ValueError(
                "CockroachDB native connections require a PostgreSQL/CockroachDB SQLAlchemy URL"
            )
        url = make_url(raw_url)
        url = url.set(drivername=ensure_cockroach_drivername(url.drivername))
        url = merge_config_credentials(url, database_config)
        query = _query_mapping(database_config, url.query)
        if query != dict(url.query):
            url = url.set(query=query)
        return url.render_as_string(hide_password=False)

    return render_url_from_config(
        "cockroachdb+psycopg", database_config, _query_mapping(database_config)
    )


__all__ = ["build_sqlalchemy_url"]
