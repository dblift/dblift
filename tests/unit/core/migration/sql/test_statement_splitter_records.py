"""``StatementSplitter.split`` returns the records the dialect's scanner returns.

The string APIs are projections of them: execution sends ``execution_strings``, analysis reads
``analysis_sql``.
"""

from __future__ import annotations

import pytest

from dblift.core.exceptions import UnsafeStatementSplitError, UnsupportedMetaCommandError
from dblift.core.migration.sql.sql_analyzer import SqlAnalyzer
from dblift.core.migration.sql.statement_splitter import StatementSplitter
from dblift.core.sql_parser.lexical_engine import LexicalEngine
from dblift.core.sql_parser.statement import Statement, analysis_sql
from tests.support import statement_list_parity as parity
from tests.support.statement_list_parity import CELLS

pytestmark = pytest.mark.unit

CELL_PARAMS = [pytest.param(d, s, id=f"{d}-{s.name}") for d, s in CELLS]


@pytest.mark.parametrize("dialect, shape", CELL_PARAMS)
def test_split_returns_the_records_of_the_scanner(dialect, shape):
    try:
        expected = parity.records(dialect, shape.script)
    except (UnsafeStatementSplitError, UnsupportedMetaCommandError) as refusal:
        with pytest.raises(type(refusal)) as raised:
            StatementSplitter(dialect).split(shape.script)
        assert str(raised.value) == str(refusal)
        return
    assert StatementSplitter(dialect).split(shape.script) == expected


@pytest.mark.parametrize("dialect, shape", CELL_PARAMS)
def test_the_analysis_list_is_the_analysis_projection_of_the_records(dialect, shape):
    analyzer = SqlAnalyzer(dialect)
    try:
        records = StatementSplitter(dialect).split(shape.script)
    except (UnsafeStatementSplitError, UnsupportedMetaCommandError) as refusal:
        with pytest.raises(type(refusal)):
            analyzer.split_statements_for_analysis(shape.script)
        return
    assert analyzer.split_statements_for_analysis(shape.script) == analysis_sql(records)


# --- a lexical engine that builds its records itself ---------------------------------------------


def test_snowflake_statements_are_still_sent():
    script = "SELECT 1;\nSELECT 'a;b';\nSELECT 3"
    records = StatementSplitter("snowflake").split(script)
    assert all(record.execution_text is None for record in records)
    assert StatementSplitter("snowflake").split_statements(script) == [
        "SELECT 1",
        "SELECT 'a;b'",
        "SELECT 3",
    ]


def test_an_engine_whose_records_never_set_execution_text_is_still_sent(monkeypatch):
    def split(self, script):
        return [Statement("SELECT 1", 1, ";"), Statement("SELECT 2", 2, None)]

    monkeypatch.setattr(LexicalEngine, "split", split)
    assert StatementSplitter("snowflake").split_statements("ignored") == ["SELECT 1", "SELECT 2"]


