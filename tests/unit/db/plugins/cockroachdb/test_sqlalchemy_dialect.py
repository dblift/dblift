"""CockroachDB SQLAlchemy dialect: version banner parse + URL drivername."""

from __future__ import annotations

import pytest
from sqlalchemy.engine import make_url

from db.plugins.cockroachdb.sqlalchemy_dialect import (
    ensure_cockroach_drivername,
    parse_cockroach_server_version,
    register_cockroach_dialect,
)
from db.plugins.cockroachdb.sqlalchemy_url import build_sqlalchemy_url


@pytest.mark.unit
@pytest.mark.parametrize(
    "banner,expected",
    [
        (
            "CockroachDB CCL v24.3.18 (x86_64-pc-linux-gnu, built 2025/08/07 22:44:01, "
            "go1.22.8 X:nocoverageredesign)",
            (24, 3, 18),
        ),
        (
            "CockroachDB CCL v26.2.4 (x86_64-pc-linux-gnu, built 2026/07/14 16:50:57, go1.25.5)",
            (26, 2, 4),
        ),
        ("CockroachDB CCL v23.1.11", (23, 1, 11)),
        ("CockroachDB v22.2.0", (22, 2, 0)),
    ],
)
def test_parse_cockroach_server_version_product_token(banner, expected):
    """Product vX.Y.Z wins; trailing go1.x.y must not be selected."""
    assert parse_cockroach_server_version(banner) == expected


@pytest.mark.unit
def test_parse_cockroach_server_version_rejects_unrelated_banner():
    with pytest.raises(AssertionError, match="Could not determine version"):
        parse_cockroach_server_version("PostgreSQL 16.2 on x86_64-pc-linux-gnu")


@pytest.mark.unit
def test_ensure_cockroach_drivername_rewrites_postgresql_family():
    assert ensure_cockroach_drivername("postgresql") == "cockroachdb+psycopg"
    assert ensure_cockroach_drivername("postgresql+psycopg") == "cockroachdb+psycopg"
    assert ensure_cockroach_drivername("postgres+psycopg") == "cockroachdb+psycopg"
    assert ensure_cockroach_drivername("cockroachdb+psycopg") == "cockroachdb+psycopg"


@pytest.mark.unit
def test_ensure_cockroach_drivername_rejects_unregistered_drivers():
    with pytest.raises(ValueError, match="psycopg"):
        ensure_cockroach_drivername("postgresql+asyncpg")
    with pytest.raises(ValueError, match="psycopg"):
        ensure_cockroach_drivername("cockroachdb+asyncpg")
    with pytest.raises(ValueError, match="PostgreSQL/CockroachDB"):
        ensure_cockroach_drivername("mysql+pymysql")


@pytest.mark.unit
def test_build_sqlalchemy_url_rewrites_postgresql_raw_url():
    class _Cfg:
        url = "postgresql+psycopg://root:root@localhost:26257/defaultdb?sslmode=disable"
        username = "root"
        password = "root"
        host = None
        port = None
        database = None
        schema = "public"
        extra_params = None
        options = None
        connection_timeout = None
        ssl_mode = None

    url = build_sqlalchemy_url(_Cfg())
    assert url.startswith("cockroachdb+psycopg://")
    assert "sslmode=disable" in url
    assert "root" in url


@pytest.mark.unit
def test_build_sqlalchemy_url_keeps_public_on_search_path():
    """CockroachDB gets the same extension-resolvable search path as PostgreSQL.

    CockroachDB has a ``public`` schema and honours ``search_path``, so a
    schema-only path hides anything installed there just as it does upstream.
    """

    class _Cfg:
        url = None
        username = "root"
        password = "root"
        host = "localhost"
        port = 26257
        database = "defaultdb"
        schema = "tenant_a"
        extra_params = None
        options = None
        connection_timeout = None
        ssl_mode = None

    url = make_url(build_sqlalchemy_url(_Cfg()))

    assert dict(url.query)["options"] == "-csearch_path=tenant_a,public"


@pytest.mark.unit
def test_build_sqlalchemy_url_does_not_repeat_public_schema():
    """A ``public`` target schema is not listed twice."""

    class _Cfg:
        url = None
        username = "root"
        password = "root"
        host = "localhost"
        port = 26257
        database = "defaultdb"
        schema = "public"
        extra_params = None
        options = None
        connection_timeout = None
        ssl_mode = None

    url = make_url(build_sqlalchemy_url(_Cfg()))

    assert dict(url.query)["options"] == "-csearch_path=public"


@pytest.mark.unit
def test_build_sqlalchemy_url_rejects_non_postgres_scheme():
    class _Cfg:
        url = "mysql+pymysql://root@localhost/db"
        username = password = host = port = database = schema = None
        extra_params = options = connection_timeout = ssl_mode = None

    with pytest.raises(ValueError, match="PostgreSQL/CockroachDB"):
        build_sqlalchemy_url(_Cfg())


@pytest.mark.unit
def test_register_cockroach_dialect_is_idempotent():
    register_cockroach_dialect()
    register_cockroach_dialect()
    from sqlalchemy.dialects import registry

    # Resolving the entry point must return our dialect class.
    dialect_cls = registry.load("cockroachdb.psycopg")
    assert dialect_cls.__name__ == "CockroachDBDialect_psycopg"
