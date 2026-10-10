"""Oracle terminators follow SQL*Plus (docs/sql-parsing/oracle.md §4)."""

import pytest

from dblift.core.exceptions import UnsafeStatementSplitError
from dblift.core.migration.sql.sql_analyzer import SqlAnalyzer


def _split(script):
    return SqlAnalyzer("oracle").split_statements(script)


@pytest.mark.parametrize(
    "script",
    [
        "SELECT 1 FROM dual; -- note\nSELECT 2 FROM dual;",  # row 16a
        "INSERT INTO t VALUES (1); INSERT INTO t VALUES (2);",  # row 16b
        "/* outer /* inner */ DROP TABLE t; */\nSELECT 1 FROM dual;",  # row 13
    ],
)
def test_semicolon_not_last_on_its_line_is_refused(script):
    with pytest.raises(UnsafeStatementSplitError, match="line 1") as exc:
        _split(script)
    assert "ORA-03405" in str(exc.value)


def test_slash_after_a_semicolon_ended_statement_is_a_re_execution_and_refused():  # row 22
    with pytest.raises(UnsafeStatementSplitError, match="line 2"):
        _split("CREATE TABLE t (id NUMBER);\n/\n")


def test_dot_alone_is_refused():  # row 26
    with pytest.raises(UnsafeStatementSplitError, match="line 4"):
        _split("BEGIN\n  NULL;\nEND;\n.\nCREATE TABLE t26 (id NUMBER);")


def test_slash_ends_a_sql_statement_without_semicolon():  # row 2
    assert _split("CREATE TABLE a (x NUMBER)\n/\nCREATE TABLE b (y NUMBER);") == [
        "CREATE TABLE a (x NUMBER)",
        "CREATE TABLE b (y NUMBER);",
    ]


def test_slash_with_trailing_text_is_statement_text():  # row 25
    out = _split("CREATE TABLE t25 (id NUMBER)\n/ -- done\nINSERT INTO t25 VALUES (1);")
    assert len(out) == 1
    assert "/ -- done" in out[0]


def test_semicolon_inside_literal_at_line_end_is_not_a_terminator():
    assert len(_split("INSERT INTO t VALUES ('a;');\nSELECT 1 FROM dual;")) == 2


def test_slash_inside_literal_at_line_start_is_text():
    assert len(_split("INSERT INTO t VALUES ('x\n/\ny');\nSELECT 1 FROM dual;")) == 2


def test_semicolon_inside_parentheses_does_not_end():
    assert len(_split("CREATE TABLE t (v VARCHAR2(10) DEFAULT (';')\n);\nSELECT 1 FROM dual;")) == 2
