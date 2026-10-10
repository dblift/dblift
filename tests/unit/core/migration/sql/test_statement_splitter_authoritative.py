"""A splitter that declares itself authoritative is never second-guessed by a fallback."""

from __future__ import annotations

import pytest

from dblift.core.exceptions import UnsafeStatementSplitError
from dblift.core.migration.sql.sql_analyzer import SqlAnalyzer
from dblift.core.migration.sql.statement_splitter import StatementSplitter


def test_directive_only_script_yields_nothing_and_never_reaches_the_fallback() -> None:
    calls: list[str] = []
    out = StatementSplitter("postgresql").split_statements(
        "\\restrict abc\n\\unrestrict abc\n", fallback=lambda sql: calls.append(sql) or ["BOOM"]
    )
    assert out == [] and calls == []


def test_analyzer_returns_nothing_for_a_directive_only_script() -> None:
    assert SqlAnalyzer("postgresql").split_statements("\\restrict abc\n\\unrestrict abc\n") == []


def test_a_refusal_is_not_softened_by_non_strict_mode() -> None:
    with pytest.raises(UnsafeStatementSplitError):
        SqlAnalyzer("postgresql").split_statements("SELECT 'abc; SELECT 2;", strict_tokenizer=False)


def test_the_postgresql_parser_has_no_regex_splitting_path() -> None:
    from dblift.db.plugins.postgresql.parser import postgresql_regex_parser as module

    # The generic base parser still owns a regex splitter; this class must not override it.
    assert "_split_by_semicolon" not in vars(module.PostgreSqlRegexParser)
    with open(module.__file__) as handle:
        source = handle.read().lower()
    # Tolerated: the docstring sentence and the attribute that declares it.
    allowed = source.replace("there is no fallback", "").replace("splits_without_fallback", "")
    assert "fallback" not in allowed
