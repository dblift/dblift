from __future__ import annotations

import pytest

from dblift.core.migration.sql import is_comment_only_statement
from dblift.core.migration.sql import statement_splitter as splitter_module
from dblift.core.migration.sql.sql_analyzer import SqlAnalyzer
from dblift.core.migration.sql.statement_splitter import StatementSplitter
from dblift.core.sql_parser.parser_factory import SqlParserFactory


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


_ALL_SPLITTER_DIALECTS = [
    "mysql",
    "mariadb",
    "postgresql",
    "sqlserver",
    "oracle",
    "sqlite",
    "duckdb",
]


@pytest.mark.unit
@pytest.mark.parametrize("dialect", _ALL_SPLITTER_DIALECTS)
@pytest.mark.parametrize(
    "sql",
    [
        "/* just a comment */",
        "/* just a comment */\n",
        "/* block */\n-- line\n",
        "-- only a line comment\n",
        "/*\n multi\n line\n*/\n",
    ],
)
def test_comment_only_script_yields_no_executable_statement(dialect, sql):
    """A comment-only migration is a no-op: nothing handed to the engine may
    contain executable tokens (a stray ``*`` from ``*/`` used to reach the server)."""
    statements = SqlAnalyzer(dialect=dialect).split_statements(sql)

    assert all(is_comment_only_statement(stmt) for stmt in statements), statements


@pytest.mark.unit
@pytest.mark.parametrize("dialect", _ALL_SPLITTER_DIALECTS)
def test_regex_fallback_drops_closing_block_comment_marker(dialect):
    analyzer = SqlAnalyzer(dialect=dialect)

    assert analyzer._split_statements_with_regex("/* just a comment */") == []
    assert analyzer._split_statements_with_regex("/* c */ SELECT 1;") == ["SELECT 1;"]


_NESTED_COMMENT_ONLY = "/* outer /* nested */ still comment */"


@pytest.mark.unit
@pytest.mark.parametrize("dialect", ["postgresql", "sqlserver", "duckdb", "db2"])
def test_nested_comment_only_script_is_a_no_op_where_comments_nest(dialect):
    """These engines nest block comments, so the whole text is one comment
    (psql/sqlcmd accept it); ``still comment */`` must not reach the server."""
    statements = SqlAnalyzer(dialect=dialect).split_statements(_NESTED_COMMENT_ONLY)

    assert all(
        is_comment_only_statement(stmt, nested_block_comments=True) for stmt in statements
    ), statements


@pytest.mark.unit
@pytest.mark.parametrize("dialect", ["mysql", "oracle", "sqlite"])
def test_nested_comment_text_still_reaches_engine_where_comments_do_not_nest(dialect):
    """The first ``*/`` closes the comment here, so ``still comment */`` is
    real (invalid) SQL that the engine itself rejects; it is not a no-op."""
    statements = SqlAnalyzer(dialect=dialect).split_statements(_NESTED_COMMENT_ONLY)

    assert any("still comment" in stmt for stmt in statements), statements
    assert not all(is_comment_only_statement(stmt) for stmt in statements), statements


@pytest.mark.unit
@pytest.mark.parametrize("dialect", ["postgresql", "sqlserver", "duckdb", "db2"])
def test_nested_comment_before_statement_keeps_the_statement(dialect):
    statements = SqlAnalyzer(dialect=dialect).split_statements(_NESTED_COMMENT_ONLY + "\nSELECT 1;")

    assert len(statements) == 1, statements
    assert statements[0].rstrip(";").endswith("SELECT 1"), statements
    assert not statements[0].startswith("still comment"), statements


@pytest.mark.unit
@pytest.mark.parametrize(
    "sql",
    [
        "/* a /* b */ ; CREATE TABLE t_in (x INT); DROP TABLE t_keep; */\n"
        "CREATE TABLE t_after (x INT);",
        "/* a /* b */ DROP TABLE t_keep; */ CREATE TABLE t_after (x INT) /* tail */;",
    ],
)
def test_db2_nested_comment_text_is_never_executed(sql):
    """Db2 nests block comments (confirmed live with the CLP and the driver):
    the ``;``, ``CREATE TABLE`` and ``DROP`` inside the comment are comment
    text, and only the statement after it reaches the server."""
    statements = SqlAnalyzer(dialect="db2").split_statements(sql)

    assert len(statements) == 1, statements
    assert "CREATE TABLE t_after (x INT)" in statements[0], statements
    live = StatementSplitter("db2").parser_factory.get_parser()
    stripped = live._strip_comments_preserving_quotes(statements[0])
    assert "t_in" not in stripped and "DROP" not in stripped, statements
