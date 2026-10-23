"""A dialect without a statement parser refuses execution."""

from __future__ import annotations

import pytest

from dblift.core.exceptions import UnsupportedDialectError
from dblift.core.migration.sql.sql_analyzer import SqlAnalyzer


def test_a_dialect_without_a_parser_refuses_execution() -> None:
    sql = "CREATE TABLE t (id int);\nCREATE TABLE u (id int);"
    with pytest.raises(UnsupportedDialectError):
        SqlAnalyzer("firebird").split_statements(sql)


def test_a_dialect_without_a_parser_raises_under_strict_mode() -> None:
    with pytest.raises(UnsupportedDialectError):
        SqlAnalyzer("firebird").split_statements("CREATE TABLE t (id int);")
