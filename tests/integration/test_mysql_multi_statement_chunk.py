"""Live check: a multi-statement chunk runs on MySQL/MariaDB as the mysql client runs it."""

from __future__ import annotations

import os
import uuid
from typing import Iterator, Tuple

import pytest

from dblift.config import DbliftConfig
from dblift.db.plugins.mysql.config import MySqlConfig
from dblift.db.provider_registry import ProviderRegistry
from dblift.db.sqlalchemy_provider import SqlAlchemyProvider

pytestmark = pytest.mark.integration


def _engines() -> list:
    found = []
    for dialect in ("mysql", "mariadb"):
        host = os.environ.get(f"DBLIFT_{dialect.upper()}_HOST")
        if host:
            found.append(pytest.param(dialect, id=dialect))
    return found or [pytest.param("mysql", marks=pytest.mark.skip(reason="no live host"))]


@pytest.fixture(params=_engines())
def provider(request: pytest.FixtureRequest) -> Iterator[Tuple[SqlAlchemyProvider, str]]:
    prefix = f"DBLIFT_{request.param.upper()}_"
    db = MySqlConfig(
        type=request.param,
        host=os.environ[prefix + "HOST"],
        port=int(os.environ.get(prefix + "PORT", "3306")),
        database=os.environ.get(prefix + "DATABASE", "testdb"),
        username=os.environ.get(prefix + "USERNAME", "root"),
        password=os.environ.get(prefix + "PASSWORD", ""),
        schema=os.environ.get(prefix + "DATABASE", "testdb"),
    )
    prov = ProviderRegistry.create_provider(DbliftConfig(database=db))
    prov.create_connection()
    table = f"t1514_{uuid.uuid4().hex[:8]}"
    prov.execute_statement(f"CREATE TABLE {table} (a INT)")
    try:
        yield prov, table
    finally:
        prov.execute_statement(f"DROP TABLE IF EXISTS {table}")
        prov.close()


def _rows(prov: SqlAlchemyProvider, table: str) -> list:
    return sorted(r["a"] for r in prov.execute_query(f"SELECT a FROM {table}"))


def test_chunk_with_two_statements_stores_both_rows(provider) -> None:
    prov, table = provider
    prov.execute_statement(f"INSERT INTO {table} VALUES (1); INSERT INTO {table} VALUES (2)")
    assert _rows(prov, table) == [1, 2]


def test_second_statement_error_surfaces(provider) -> None:
    prov, table = provider
    with pytest.raises(Exception, match="1146|doesn't exist"):
        prov.execute_statement(
            f"INSERT INTO {table} VALUES (3); INSERT INTO no_such_{table} VALUES (4)"
        )
    # the connection is still in step with the server
    assert 3 in _rows(prov, table)


def test_result_returning_first_statement_does_not_desync(provider) -> None:
    prov, table = provider
    prov.execute_statement(f"SELECT 1; INSERT INTO {table} VALUES (5)")
    assert _rows(prov, table) == [5]
