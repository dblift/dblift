"""An unterminated comment, string, quoted identifier or dollar quote is refused with its position."""

import pytest

from dblift.core.exceptions import UnsafeStatementSplitError
from dblift.core.migration.sql.sql_analyzer import SqlAnalyzer


@pytest.mark.parametrize(
    "script, where",
    [
        ("/*DELIMITER //*/ SELECT 1;", "line 1, column 1"),
        ("SELECT 'abc; SELECT 2;", "line 1, column 8"),
        ("SELECT $$abc; SELECT 2;", "line 1, column 8"),
        ('SELECT "a;b FROM t;', "line 1, column 8"),
        ("SELECT E'abc\\'; SELECT 2;", "line 1, column 8"),
        ("SELECT 1;\n/* open", "line 2, column 1"),
    ],
)
def test_unterminated_lexeme_is_refused_with_its_position(script: str, where: str) -> None:
    with pytest.raises(UnsafeStatementSplitError) as info:
        SqlAnalyzer("postgresql").split_statements(script)
    assert where in str(info.value)


def test_unclosed_parenthesis_at_end_of_input_is_one_statement() -> None:
    assert SqlAnalyzer("postgresql").split_statements("SELECT (1; SELECT 2;") == [
        "SELECT (1; SELECT 2;"
    ]
