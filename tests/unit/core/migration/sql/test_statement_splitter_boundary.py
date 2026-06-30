from __future__ import annotations

import pytest

from core.migration.sql import statement_splitter as splitter_module
from core.migration.sql.sql_analyzer import SqlAnalyzer
from core.migration.sql.statement_splitter import StatementSplitter
from core.sql_parser.parser_factory import SqlParserFactory


@pytest.mark.unit
def test_statement_splitter_dialect_is_required():
    """ADR-26 E: ``dialect`` has no default — the sole production caller
    (SqlAnalyzer) always passes ``self.dialect``, so the literal default was
    removed."""
    with pytest.raises(TypeError):
        StatementSplitter()


@pytest.mark.unit
def test_statement_splitter_uses_regex_parser_factory(monkeypatch):
    created_parser_types = []

    class FakeParser:
        def split_statements(self, sql, strict_tokenizer=False):
            return [sql.strip()]

    class FakeFactory:
        def __init__(self, dialect, parser_type="hybrid"):
            created_parser_types.append(parser_type)

        def get_parser(self):
            return FakeParser()

    monkeypatch.setattr(splitter_module, "SqlParserFactory", FakeFactory)

    splitter = StatementSplitter("postgresql")

    assert splitter.split_statements("select 1;") == ["select 1;"]
    assert created_parser_types == ["regex"]


@pytest.mark.unit
def test_sql_analyzer_split_statements_does_not_use_rich_parser_factory():
    class ExplodingAnalysisFactory:
        def get_parser(self, dialect=None):
            raise AssertionError("rich analysis parser should not split execution statements")

        def extract_objects(self, statement, schema=None):
            raise AssertionError("rich object extraction should not split execution statements")

    class FakeStatementSplitter:
        def split_statements(self, sql, *, strict_tokenizer=False, fallback=None):
            return ["select 1", "select 2"]

    analyzer = SqlAnalyzer(
        dialect="postgresql",
        parser_factory=ExplodingAnalysisFactory(),
        statement_splitter=FakeStatementSplitter(),
    )

    assert analyzer.split_statements("select 1; select 2;") == ["select 1", "select 2"]


@pytest.mark.unit
def test_sql_parser_factory_get_parser_honors_regex_parser_type():
    factory = SqlParserFactory("postgresql", parser_type="regex")

    parser = factory.get_parser()

    assert parser.__class__.__name__ == "PostgreSqlRegexParser"


@pytest.mark.unit
def test_statement_splitter_supports_cosmosdb_regex_parser():
    splitter = StatementSplitter("cosmosdb")

    statements = splitter.split_statements(
        "CREATE CONTAINER users (id STRING) WITH (partitionKey='/id');"
    )

    assert statements == ["CREATE CONTAINER users (id STRING) WITH (partitionKey='/id');"]
