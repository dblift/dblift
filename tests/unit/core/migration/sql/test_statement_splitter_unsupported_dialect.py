"""A dialect without a statement parser splits through the caller's fallback."""

from __future__ import annotations

import pytest

from dblift.core.exceptions import UnsupportedDialectError
from dblift.core.migration.sql.sql_analyzer import SqlAnalyzer


def test_a_dialect_without_a_parser_still_splits_through_the_fallback() -> None:
    sql = "CREATE TABLE t (id int);\nCREATE TABLE u (id int);"
    assert SqlAnalyzer("firebird").split_statements(sql) == [
        "CREATE TABLE t (id int);",
        "CREATE TABLE u (id int);",
    ]


def test_a_dialect_without_a_parser_raises_under_strict_mode() -> None:
    with pytest.raises(UnsupportedDialectError):
        SqlAnalyzer("firebird").split_statements("CREATE TABLE t (id int);", strict_tokenizer=True)
