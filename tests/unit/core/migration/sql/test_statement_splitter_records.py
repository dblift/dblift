"""``StatementSplitter.split`` returns the records the dialect's scanner returns.

The string APIs are projections of them: execution sends ``execution_strings``, analysis reads
``analysis_sql``.
"""

from __future__ import annotations

import pytest

from dblift.core.exceptions import UnsafeStatementSplitError, UnsupportedMetaCommandError
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


# --- a parser that cannot return records --------------------------------------------------------


class _StringsOnly:
    def split_statements(self, sql_content: str, strict_tokenizer: bool = False):
        return ["SELECT 1"]


def _with_parser(parser) -> StatementSplitter:
    splitter = StatementSplitter("postgresql")
    splitter._engine = None
    splitter._parser = parser
    return splitter


@pytest.mark.parametrize("method", ["split", "split_statements"])
def test_a_strings_only_parser_refuses_before_execution(method):
    splitter = _with_parser(_StringsOnly())
    with pytest.raises(UnsafeStatementSplitError, match="postgresql.*Statement records"):
        getattr(splitter, method)("SELECT 1")


@pytest.mark.parametrize("method", ["split", "split_statements"])
def test_a_parser_returning_strings_from_split_refuses(method):
    class InvalidParser:
        def split(self, sql):
            return ["SELECT 1"]

    with pytest.raises(UnsafeStatementSplitError, match="postgresql.*Statement records"):
        getattr(_with_parser(InvalidParser()), method)("SELECT 1")


def test_record_parser_preserves_source_metadata():
    records = [
        Statement("SELECT 1", 3, "GO", repeat=0, source_start=5, source_end=17),
        Statement("DELIMITER $$", 4, "\n", kind="directive", source_start=18, source_end=31),
        Statement("SELECT 2", 5, ";", execution_text="SELECT 2 /* sent */", source_start=32, source_end=41),
    ]

    class RecordParser:
        def split(self, sql):
            return records

    splitter = _with_parser(RecordParser())
    assert splitter.split("ignored") == records
    assert splitter.split_statements("ignored") == ["SELECT 2 /* sent */"]


@pytest.mark.parametrize("error", [UnsafeStatementSplitError("unsafe"), UnsupportedMetaCommandError("meta")])
def test_parser_refusals_keep_their_class_and_message(error):
    class RefusingParser:
        def split(self, sql):
            raise error

    with pytest.raises(type(error), match=str(error)):
        _with_parser(RefusingParser()).split("ignored")
