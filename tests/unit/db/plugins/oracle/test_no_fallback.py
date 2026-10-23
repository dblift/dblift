"""The Oracle splitter has no second splitter: strict mode changes nothing and a refusal stays one."""

import pytest

from dblift.core.exceptions import UnsafeStatementSplitError
from dblift.core.migration.sql.sql_analyzer import SqlAnalyzer
from dblift.core.sql_parser.base_tokenizer import TokenizerWarning
from tests.support.facts_parser import facts_parser


@pytest.mark.parametrize("strict", [False, True])
def test_strict_mode_changes_nothing_and_a_refusal_stays_a_refusal(strict):
    analyzer = SqlAnalyzer("oracle")
    assert analyzer.split_statements("SELECT 1 FROM dual;") == ["SELECT 1 FROM dual;"]
    with pytest.raises(UnsafeStatementSplitError):
        analyzer.split_statements("SELECT 'open")


@pytest.mark.parametrize("strict", [False, True])
def test_strict_mode_does_not_reject_an_unclaimed_character(strict):
    # an unclaimed character is passed through verbatim with a warning in both modes
    script = "SELECT \u200b 1 FROM dual;"
    with pytest.warns(TokenizerWarning):
        assert SqlAnalyzer("oracle").split_statements(script) == [script]
        assert [(r.text, r.terminator) for r in facts_parser("oracle").split(script)] == [
            ("SELECT \u200b 1 FROM dual", ";")
        ]
