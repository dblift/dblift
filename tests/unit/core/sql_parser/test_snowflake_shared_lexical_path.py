"""Snowflake's shared lexical path keeps its D1 contract once statement facts are read."""

from __future__ import annotations

import pytest

from dblift.core.exceptions import UnsafeStatementSplitError
from dblift.core.migration.sql.statement_splitter import StatementSplitter
from dblift.core.sql_parser.lexical_engine import LexicalEngine
from dblift.core.sql_parser.lexical_spec import LexicalSpec
from dblift.core.sql_parser.parser_factory import SqlParserFactory
from dblift.core.sql_parser.statement import Statement, analysis_sql, execution_strings
from dblift.db.provider_registry import ProviderRegistry


def test_snowflake_uses_a_lexical_spec_for_statement_facts() -> None:
    quirks = ProviderRegistry.get_quirks("snowflake")
    spec = quirks.lexical_spec()

    assert isinstance(spec, LexicalSpec)
    assert spec.name == "snowflake"
    assert quirks.supports_statement_facts

    splitter = StatementSplitter("snowflake")
    assert isinstance(splitter._engine, LexicalEngine)
    assert splitter._engine.spec == spec


def test_snowflake_split_views_route_through_shared_records(monkeypatch) -> None:
    script = "SELECT 7;"
    record = Statement("SELECT 7", 1, ";", source_start=0, source_end=len(script))
    calls = []

    def split(self, sql):
        calls.append((self.spec.name, sql))
        return [record]

    monkeypatch.setattr(LexicalEngine, "split", split)

    assert StatementSplitter("snowflake").split(script) == [record]
    for mode in ("regex", "hybrid"):
        parser = SqlParserFactory("snowflake", parser_type=mode).get_parser()
        assert parser.split_statements(script) == ["SELECT 7"]
        assert parser.split_for_analysis(script) == ["SELECT 7"]
        assert parser.split_for_extraction(script) == ["SELECT 7"]

    # split_statements takes the engine's execution view, the other views its records.
    assert calls == [("snowflake", script)] * 5


def test_snowflake_retains_current_execution_and_refusal_controls() -> None:
    script = '-- setup; comment\nCREATE TABLE "QA"."A;B" ("V" VARCHAR);\nSELECT \'a;b\';'
    records = StatementSplitter("snowflake").split(script)
    first_end = script.index(";\nSELECT") + 1

    assert execution_strings(records) == [
        '-- setup; comment\nCREATE TABLE "QA"."A;B" ("V" VARCHAR)',
        "SELECT 'a;b'",
    ]
    assert analysis_sql(records) == execution_strings(records)
    assert [(record.line, record.source_start, record.source_end) for record in records] == [
        (1, 0, first_end),
        (3, first_end, len(script)),
    ]

    with pytest.raises(UnsafeStatementSplitError):
        StatementSplitter("snowflake").split("BEGIN LET x INT := 1; RETURN x; END;")


def test_snowflake_facts_parser_executes_what_the_splitter_executes() -> None:
    script = '-- setup; comment\nCREATE TABLE "QA"."A;B" ("V" VARCHAR);\nSELECT \'a;b\';\nSELECT 2'
    expected = StatementSplitter("snowflake").split_statements(script)

    assert len(expected) == 3
    for mode in ("regex", "hybrid"):
        parser = SqlParserFactory("snowflake", parser_type=mode).get_parser()
        assert parser.split_statements(script) == expected
