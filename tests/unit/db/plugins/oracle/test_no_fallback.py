"""The Oracle splitter has no second splitter: strict mode changes nothing and a refusal stays one."""

import pytest

from dblift.core.exceptions import UnsafeStatementSplitError
from dblift.core.migration.sql.sql_analyzer import SqlAnalyzer


@pytest.mark.parametrize("strict", [False, True])
def test_strict_mode_neither_softens_nor_changes_the_split(strict):
    analyzer = SqlAnalyzer("oracle")
    assert analyzer.split_statements("SELECT 1 FROM dual;", strict_tokenizer=strict) == [
        "SELECT 1 FROM dual;"
    ]
    with pytest.raises(UnsafeStatementSplitError):
        analyzer.split_statements("SELECT 'open", strict_tokenizer=strict)
