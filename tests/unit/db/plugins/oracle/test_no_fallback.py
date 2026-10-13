"""The Oracle splitter has no second splitter: strict mode changes nothing and a refusal stays one."""

import pytest

from dblift.core.exceptions import UnsafeStatementSplitError
from dblift.core.migration.sql.sql_analyzer import SqlAnalyzer
from dblift.core.sql_parser.base_tokenizer import TokenizerWarning
from dblift.db.plugins.oracle.parser.oracle_parser import OracleParser


@pytest.mark.parametrize("strict", [False, True])
def test_strict_mode_changes_nothing_and_a_refusal_stays_a_refusal(strict):
    analyzer = SqlAnalyzer("oracle")
    assert analyzer.split_statements("SELECT 1 FROM dual;", strict_tokenizer=strict) == [
        "SELECT 1 FROM dual;"
    ]
    with pytest.raises(UnsafeStatementSplitError):
        analyzer.split_statements("SELECT 'open", strict_tokenizer=strict)


@pytest.mark.parametrize("strict", [False, True])
def test_strict_mode_does_not_reject_an_unclaimed_character(strict):
    # an unclaimed character is passed through verbatim with a warning in both modes
    script = "SELECT \u200b 1 FROM dual;"
    with pytest.warns(TokenizerWarning):
        assert SqlAnalyzer("oracle").split_statements(script, strict_tokenizer=strict) == [script]
        assert [
            (r.text, r.terminator) for r in OracleParser().split(script, strict_tokenizer=strict)
        ] == [("SELECT \u200b 1 FROM dual", ";")]
