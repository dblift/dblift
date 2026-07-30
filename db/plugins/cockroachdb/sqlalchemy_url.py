"""SQLAlchemy URL construction for CockroachDB.

Reuses the PostgreSQL URL shape (host/user/sslmode/search_path) but forces the
``cockroachdb+psycopg`` drivername so SQLAlchemy loads
:class:`CockroachDBDialect_psycopg` instead of the stock PostgreSQL dialect
that cannot parse CockroachDB ``version()`` banners.
"""

from __future__ import annotations

from typing import Any, Dict

from sqlalchemy.engine import URL, make_url

from db.plugins.cockroachdb.sqlalchemy_dialect import (
    ensure_cockroach_drivername,
    register_cockroach_dialect,
)


def _string_mapping(values: Any) -> Dict[str, str]:
    if not isinstance(values, dict):
        return {}
    return {str(key): str(value) for key, value in values.items()}


def _query_mapping(database_config: Any, base_query: Any = None) -> Dict[str, str]:
    query = _string_mapping(base_query)
    query.update(_string_mapping(getattr(database_config, "extra_params", None)))
    query.update(_string_mapping(getattr(database_config, "options", None)))

    connection_timeout = getattr(database_config, "connection_timeout", None)
    if connection_timeout:
        query["connect_timeout"] = str(connection_timeout)

    ssl_mode = getattr(database_config, "ssl_mode", None)
    if ssl_mode:
        query["sslmode"] = str(ssl_mode)

    schema = getattr(database_config, "schema", None)
    if schema:
        schema_option = f"-csearch_path={schema}"
        query["options"] = (
            f"{query['options']} {schema_option}" if query.get("options") else schema_option
        )

    return query


def build_sqlalchemy_url(database_config: Any) -> str:
    """Build a CockroachDB SQLAlchemy URL (psycopg driver, CRDB dialect)."""
    register_cockroach_dialect()

    raw_url = getattr(database_config, "url", None)
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
                "CockroachDB native connections require a PostgreSQL/CockroachDB " "SQLAlchemy URL"
            )
        url = make_url(raw_url)
        url = url.set(drivername=ensure_cockroach_drivername(url.drivername))
        username = getattr(database_config, "username", None) or url.username or None
        password = getattr(database_config, "password", None) or url.password or None
        if username != url.username or password != url.password:
            url = url.set(username=username, password=password)
        query = _query_mapping(database_config, url.query)
        if query != dict(url.query):
            url = url.set(query=query)
        return url.render_as_string(hide_password=False)

    return URL.create(
        "cockroachdb+psycopg",
        username=getattr(database_config, "username", None) or None,
        password=getattr(database_config, "password", None) or None,
        host=getattr(database_config, "host", None) or "localhost",
        port=getattr(database_config, "port", None),
        database=getattr(database_config, "database", None),
        query=_query_mapping(database_config),
    ).render_as_string(hide_password=False)


__all__ = ["build_sqlalchemy_url"]
