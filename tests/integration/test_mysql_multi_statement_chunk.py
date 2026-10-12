"""Live check: a multi-statement chunk runs on MySQL/MariaDB as the mysql client runs it."""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from pathlib import Path
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


def test_same_value_update_counts_matched_rows(provider) -> None:
    prov, table = provider
    prov.execute_statement(f"INSERT INTO {table} VALUES (1)")
    assert prov.execute_statement(f"UPDATE {table} SET a = a WHERE a = 1") == 1


def test_execute_query_returns_the_first_result_set(provider) -> None:
    prov, _ = provider
    assert prov.execute_query("SELECT 1 AS a; SELECT 2 AS b") == [{"a": 1}]


def test_execute_query_returns_the_rows_of_a_call(provider) -> None:
    prov, table = provider
    proc = f"p_{table}"
    prov.execute_statement(f"CREATE PROCEDURE {proc}() SELECT 7 AS v")
    try:
        assert prov.execute_query(f"CALL {proc}()") == [{"v": 7}]
    finally:
        prov.execute_statement(f"DROP PROCEDURE IF EXISTS {proc}")


def test_later_statement_error_after_a_select_surfaces(provider) -> None:
    prov, table = provider
    with pytest.raises(Exception, match="1146|doesn't exist"):
        prov.execute_query(f"SELECT 1 AS a; INSERT INTO no_such_{table} VALUES (1)")
    assert prov.execute_query("SELECT 2 AS b") == [{"b": 2}]


def test_migrate_runs_a_select_led_unit_under_a_custom_delimiter(provider, tmp_path: Path) -> None:
    prov, table = provider
    dialect = prov.config.database.type
    prefix = f"DBLIFT_{dialect.upper()}_"
    db = os.environ.get(prefix + "DATABASE", "testdb")
    (tmp_path / "V1__x.sql").write_text(
        f"DELIMITER //\nSELECT 1; INSERT INTO {table} VALUES (5)//\nDELIMITER ;\n"
    )
    url = f"mysql://{os.environ[prefix + 'HOST']}:{os.environ.get(prefix + 'PORT', '3306')}/{db}"
    done = subprocess.run(
        [
            str(Path(sys.executable).parent / "dblift"),
            "--db-url",
            url,
            "--db-username",
            os.environ.get(prefix + "USERNAME", "root"),
            "--db-password",
            os.environ.get(prefix + "PASSWORD", ""),
            "--db-schema",
            db,
            "--scripts",
            str(tmp_path),
            "migrate",
        ],
        capture_output=True,
        text=True,
        env={**os.environ, "DBLIFT_TABLE": ""},
    )
    try:
        assert done.returncode == 0, done.stdout + done.stderr
        assert _rows(prov, table) == [5]
    finally:
        prov.execute_statement("DROP TABLE IF EXISTS dblift_schema_history")
