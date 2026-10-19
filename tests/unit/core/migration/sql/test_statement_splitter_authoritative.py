"""A splitter that declares itself authoritative is never second-guessed by a fallback."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from dblift.core.exceptions import UnsafeStatementSplitError
from dblift.core.migration.sql.sql_analyzer import SqlAnalyzer
from dblift.core.migration.sql.statement_splitter import StatementSplitter
from dblift.db.plugins.postgresql.parser.lexical_spec import POSTGRESQL_SPEC


def test_directive_only_script_yields_nothing() -> None:
    assert (
        StatementSplitter("postgresql").split_statements("\\restrict abc\n\\unrestrict abc\n") == []
    )


def test_analyzer_returns_nothing_for_a_directive_only_script() -> None:
    assert SqlAnalyzer("postgresql").split_statements("\\restrict abc\n\\unrestrict abc\n") == []


def test_a_refusal_is_not_softened_by_non_strict_mode() -> None:
    with pytest.raises(UnsafeStatementSplitError):
        SqlAnalyzer("postgresql").split_statements("SELECT 'abc; SELECT 2;", strict_tokenizer=False)


def test_the_postgresql_parser_has_no_regex_splitting_path() -> None:
    from dblift.db.plugins.postgresql.parser import postgresql_regex_parser as module

    # The dialect parser does not own a second semicolon splitter.
    assert "_split_by_semicolon" not in vars(module.PostgreSqlRegexParser)
    with open(module.__file__) as handle:
        source = handle.read().lower()
    allowed = source.replace("there is no fallback", "")
    assert "fallback" not in allowed


def _boom(self):
    raise ValueError("boom")


def test_a_parser_bug_is_a_refusal_not_a_semicolon_split(monkeypatch) -> None:
    from dblift.core.migration.sql.migration_sql_parser import parse_migration_sql
    from dblift.core.sql_parser.lexical_statement_parser import (
        LexicalStatementParser,
    )

    monkeypatch.setattr(LexicalStatementParser, "split", _boom)
    script = "SELECT 1; SELECT $$a;b$$;"
    with pytest.raises(UnsafeStatementSplitError):
        SqlAnalyzer("postgresql").split_statements(script)
    with pytest.raises(UnsafeStatementSplitError):
        parse_migration_sql(SqlAnalyzer("postgresql"), script, MagicMock())


def test_an_oracle_parser_bug_is_a_refusal_not_a_regex_split(monkeypatch) -> None:
    from dblift.core.migration.sql.migration_sql_parser import parse_migration_sql
    from dblift.core.sql_parser.lexical_statement_parser import LexicalStatementParser

    monkeypatch.setattr(LexicalStatementParser, "split", _boom)
    script = "SELECT 1 FROM dual;"
    with pytest.raises(UnsafeStatementSplitError):
        SqlAnalyzer("oracle").split_statements(script)
    with pytest.raises(UnsafeStatementSplitError):
        parse_migration_sql(SqlAnalyzer("oracle"), script, MagicMock())
