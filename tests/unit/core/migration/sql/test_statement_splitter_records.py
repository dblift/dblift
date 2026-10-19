"""``StatementSplitter.split`` returns the records the dialect's scanner returns.

The string APIs are projections of them: execution sends ``execution_strings``, analysis reads
``analysis_sql``. A parser that only returns strings is adapted, once, in one place.
"""

from __future__ import annotations

import logging
from typing import List

import pytest

from dblift.core.exceptions import UnsafeStatementSplitError, UnsupportedMetaCommandError
from dblift.core.migration.sql import statement_splitter
from dblift.core.migration.sql.sql_analyzer import SqlAnalyzer
from dblift.core.migration.sql.statement_splitter import StatementSplitter
from dblift.core.sql_parser.statement import Statement, analysis_sql, execution_strings
from dblift.db.plugins.snowflake.statement_parser import SnowflakeStatementParser
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


# --- a parser that builds its records itself ----------------------------------------------------


def test_snowflake_statements_are_still_sent():
    script = "SELECT 1;\nSELECT 'a;b';\nSELECT 3"
    records = SnowflakeStatementParser().split(script)
    assert all(record.execution_text is None for record in records)
    assert StatementSplitter("snowflake").split_statements(script) == [
        "SELECT 1",
        "SELECT 'a;b'",
        "SELECT 3",
    ]


def test_a_parser_whose_records_never_set_execution_text_is_still_sent(monkeypatch):
    def split(self, script):
        return [Statement("SELECT 1", 1, ";"), Statement("SELECT 2", 2, None)]

    monkeypatch.setattr(SnowflakeStatementParser, "split", split)
    assert StatementSplitter("snowflake").split_statements("ignored") == ["SELECT 1", "SELECT 2"]


# --- a parser that only returns strings ---------------------------------------------------------


class _StringsOnly:
    """What a plugin dialect without a lexical spec may expose: strings, no records."""

    def __init__(self, strings: List[str]) -> None:
        self.strings = strings

    def split_statements(self, sql_content: str, strict_tokenizer: bool = False) -> List[str]:
        return list(self.strings)


def _adapted(strings: List[str]) -> StatementSplitter:
    splitter = StatementSplitter("postgresql")
    splitter._engine = None
    splitter._parser = _StringsOnly(strings)  # type: ignore[assignment]
    return splitter


def test_a_parser_with_only_strings_is_adapted_to_sql_records():
    splitter = _adapted(["SELECT 1;", "  ", "", "SELECT 2"])
    records = splitter.split("ignored")
    assert [(r.text, r.kind, r.repeat, r.execution_text) for r in records] == [
        ("SELECT 1;", "sql", 1, None),
        ("SELECT 2", "sql", 1, None),
    ]
    assert execution_strings(records) == ["SELECT 1;", "SELECT 2"]


def test_the_adapter_keeps_the_two_skips_the_engine_loops_had(monkeypatch):
    from dblift.db.base_quirks import BaseQuirks

    monkeypatch.setattr(BaseQuirks, "is_batch_separator", lambda self, s: s == "RUN", raising=False)
    records = _adapted(["SELECT 1;", "-- only a comment", "RUN", "/* x */", "SELECT 2"]).split("x")
    assert [r.text for r in records] == ["SELECT 1;", "SELECT 2"]


def test_the_adapter_announces_itself_once(caplog, monkeypatch):
    monkeypatch.setattr(statement_splitter, "_ANNOUNCED", set())
    splitter = _adapted(["SELECT 1"])
    with caplog.at_level(logging.WARNING):
        splitter.split("x")
        splitter.split("x")
    notices = [r for r in caplog.records if "return Statement records" in r.getMessage()]
    assert len(notices) == 1
    assert "postgresql" in notices[0].getMessage()


def test_a_parser_with_only_strings_returns_its_statements_without_the_pieces_that_are_none():
    strings = ["SELECT 1;", "-- only a comment", "", "  ", "SELECT 2"]
    assert _adapted(strings).split_statements("x") == ["SELECT 1;", "SELECT 2"]


def test_split_statements_of_a_strings_only_parser_announces_itself_once(caplog, monkeypatch):
    monkeypatch.setattr(statement_splitter, "_ANNOUNCED", set())
    splitter = _adapted(["SELECT 1"])
    with caplog.at_level(logging.WARNING):
        splitter.split_statements("x")
        splitter.split_statements("x")
    assert len([r for r in caplog.records if "return Statement records" in r.getMessage()]) == 1
