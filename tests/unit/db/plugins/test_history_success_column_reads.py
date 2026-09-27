"""History reads must interpret the ``success`` column, not truth-test it.

``import-flyway`` reads the Flyway table through each provider's
``get_applied_migrations``. A hand-built Flyway table can declare ``success``
as text holding ``'0'`` or ``'false'``; plain ``bool()`` turns both into
``True``, so failed Flyway rows were imported as successful (MySQL, SQLite),
and ``bool(int('false'))`` crashed the read outright (Oracle, DB2).
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from dblift.core.migration.migration import success_to_bool
from dblift.db.plugins.db2.provider import Db2Provider
from dblift.db.plugins.mysql.provider import MySqlProvider
from dblift.db.plugins.oracle.provider import OracleProvider
from dblift.db.plugins.sqlite.sqlite.history_manager import SQLiteHistoryManager

CASES = [
    ("0", False),
    ("false", False),
    ("1", True),
    (0, False),
    (1, True),
    (True, True),
    (False, False),
]


@pytest.mark.parametrize(("raw", "expected"), CASES)
def test_success_to_bool(raw: Any, expected: bool) -> None:
    assert success_to_bool(raw) is expected


def _read_through_provider(cls: type, raw: Any, upper_keys: bool) -> Any:
    provider = object.__new__(cls)
    provider.table_exists = MagicMock(return_value=True)  # type: ignore[method-assign]
    provider.get_schema_qualified_name = MagicMock(return_value="s.t")  # type: ignore[method-assign]
    key = "SUCCESS" if upper_keys else "success"
    provider.execute_query = MagicMock(  # type: ignore[method-assign]
        return_value=[{"script": "V1__a.sql", key: raw}]
    )
    rows = provider.get_applied_migrations("s", "flyway_schema_history")
    return rows[0]["success"]


@pytest.mark.parametrize(("raw", "expected"), CASES)
def test_mysql_reads_success(raw: Any, expected: bool) -> None:
    assert _read_through_provider(MySqlProvider, raw, upper_keys=False) is expected


@pytest.mark.parametrize(("raw", "expected"), CASES)
def test_oracle_reads_success(raw: Any, expected: bool) -> None:
    assert _read_through_provider(OracleProvider, raw, upper_keys=True) is expected


@pytest.mark.parametrize(("raw", "expected"), CASES)
def test_db2_reads_success(raw: Any, expected: bool) -> None:
    assert _read_through_provider(Db2Provider, raw, upper_keys=True) is expected


@pytest.mark.parametrize(("raw", "expected"), CASES)
def test_sqlite_reads_success(raw: Any, expected: bool) -> None:
    executor = MagicMock()
    executor.table_exists.return_value = True
    executor.execute_query.return_value = [{"script": "V1__a.sql", "success": raw}]
    manager = SQLiteHistoryManager(executor, MagicMock(), MagicMock(), log=MagicMock())
    rows = manager.get_applied_migrations(MagicMock(), "main", "flyway_schema_history")
    assert rows[0]["success"] is expected
