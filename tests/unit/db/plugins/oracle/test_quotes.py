"""Oracle quoting refusals (docs/sql-parsing/oracle.md §1-§2)."""

import pytest

from dblift.core.exceptions import UnsafeStatementSplitError
from dblift.core.migration.sql.statement_reader import StatementReader


def _split(script):
    return StatementReader("oracle").split_statements(script)


def test_whitespace_q_quote_delimiter_is_refused():  # row 11
    with pytest.raises(
        UnsafeStatementSplitError,
        match="q-quote delimiter cannot be whitespace at line 1, column 23",
    ):
        _split("INSERT INTO t VALUES (q' x ');")


def test_unterminated_q_quote_is_refused():
    with pytest.raises(
        UnsafeStatementSplitError, match="unterminated q-quoted string opened at line 1, column 23"
    ):
        _split("INSERT INTO t VALUES (q'[abc);\nSELECT 1 FROM dual;")


def test_unterminated_quoted_identifier_is_refused():
    with pytest.raises(
        UnsafeStatementSplitError, match="unterminated quoted identifier opened at line 1, column 8"
    ):
        _split('SELECT "abc FROM dual;')


def test_q_quote_closes_only_at_delimiter_then_quote():
    # `]b` is not `]'`, so the literal runs to the final `]'` and holds `a]b`.
    assert _split("SELECT q'[a]b]' FROM dual;") == ["SELECT q'[a]b]' FROM dual;"]


def test_text_after_first_closing_delimiter_is_ordinary_sql():
    # q'[a]' closes at the first `]'`; the trailing `b]'` opens a plain string that never closes.
    with pytest.raises(UnsafeStatementSplitError, match="unterminated string"):
        _split("SELECT q'[a]'b]' FROM dual;")


@pytest.mark.parametrize("literal", ["nq'{x;y}'", "q'!a;b!'"])
def test_semicolon_inside_q_quote_does_not_split(literal):
    assert _split(f"SELECT {literal} FROM dual;") == [f"SELECT {literal} FROM dual;"]
