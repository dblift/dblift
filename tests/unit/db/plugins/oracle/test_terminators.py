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


@pytest.mark.parametrize(
    "script",
    [
        "INSERT INTO t VALUES (1)\n/\n/\n",
        "BEGIN NULL; END;\n/\n/\n",
        "INSERT INTO t VALUES (1)\n/\nPROMPT done\n/\n",
    ],
)
def test_second_slash_refuses_re_execution_on_line_four_or_three(script):  # row 22a
    line = 4 if "PROMPT" in script else 3
    with pytest.raises(UnsafeStatementSplitError, match=f"line {line}") as exc:
        _split(script)
    assert "re-execute" in str(exc.value)


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


def test_a_long_single_line_with_many_slashes_splits_in_linear_time():
    import time

    # A size ratio, not a wall-clock bound: absolute time varies with the runner.
    def best_time(tokens):
        script = "SELECT " + ", ".join("a.b/c" for _ in range(tokens)) + " FROM dual;"
        best = float("inf")
        for _ in range(2):
            started = time.perf_counter()
            statements = _split(script)
            best = min(best, time.perf_counter() - started)
        assert len(statements) == 1
        return best

    t_n = best_time(5_000)
    t_4n = best_time(20_000)

    # Linear scaling gives ~4x for 4x the input; a quadratic scan gives ~16x.
    assert t_4n < 8 * t_n, f"t_n={t_n:.3f}s t_4n={t_4n:.3f}s ratio={t_4n / t_n:.1f}"


@pytest.mark.parametrize("line", ["/", "  /  ", "\t/\t"])
@pytest.mark.parametrize("newline", ["\n", "\r\n"])
def test_slash_alone_between_blanks_still_terminates(line, newline):
    script = f"BEGIN NULL; END;{newline}{line}{newline}SELECT 1 FROM dual;"
    assert len(_split(script)) == 2


def test_slash_followed_by_text_after_a_unit_says_so():
    with pytest.raises(UnsafeStatementSplitError, match="followed by other text") as exc:
        _split("BEGIN NULL; END;\n/ -- c\n")
    assert "line 2" in str(exc.value)
