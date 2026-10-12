"""A script the scanner refuses cannot yield a partial parse."""

from __future__ import annotations

import pytest

from dblift.core.sql_parser import SqlParserFactory

SCRIPTS = [
    ("mysql", "UPDATE t SET a = 1;\nSELECT 1\\G\nUPDATE t SET a = 2;\n", "\\G"),
    ("mariadb", "UPDATE t SET a = 1;\nsource other.sql\nUPDATE t SET a = 2;\n", "source"),
    ("sqlserver", "UPDATE t SET a = 1;\nGO\n:r other.sql\nGO\n", ":r"),
    ("duckdb", ".mode csv\nCREATE TABLE a(x INT);\n", ".mode"),
]


@pytest.mark.parametrize("dialect,script,command", SCRIPTS)
def test_parse_sql_reports_a_refused_split_instead_of_failing(
    dialect: str, script: str, command: str
) -> None:
    result = SqlParserFactory(dialect).get_parser().parse_sql(script)
    assert not result.success
    assert result.statements == []
    assert result.tables == []
    assert any(command in error for error in result.errors)
