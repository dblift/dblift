"""``analyse_script`` reads statement facts and nothing else.

Every plugin that runs SQL migrations has a statement-facts reader, so the script analysis never
builds a text model. A plugin without a reader is reported, not guessed at.
"""

from __future__ import annotations

import warnings

import pytest

from dblift.core.exceptions import ParserError
from dblift.core.migration.sql.lint import REVIEW, lint_script
from dblift.core.migration.sql.script_analysis import analyse_script
from dblift.core.sql_parser.parser_factory import SqlParserFactory
from dblift.db.plugins.postgresql.quirks import PostgresqlQuirks
from dblift.db.provider_registry import ProviderRegistry

pytestmark = pytest.mark.unit

SCRIPT = "CREATE TABLE t (id INTEGER);\nDROP TABLE t;\nDELETE FROM u;"


def _sql_dialects() -> list:
    ProviderRegistry.discover_plugins()
    names = [getattr(p, "name", None) or str(p) for p in ProviderRegistry.list_plugins()]
    return sorted(n for n in names if ProviderRegistry.get_quirks(n).supports_sql_migrations)


def test_every_sql_migration_plugin_reads_statement_facts():
    missing = [
        d for d in _sql_dialects() if not ProviderRegistry.get_quirks(d).supports_statement_facts
    ]
    assert missing == []


# A well-formed script, an unterminated literal and a NUL byte (the splitter refuses it).
SCRIPTS = (SCRIPT, "SELECT 'unterminated; DROP TABLE t;", "SELECT 1;\x00DROP TABLE t;")


@pytest.fixture
def text_model_calls(monkeypatch):
    """Record every ``parse_sql`` call; the analysis swallows errors, so a raise proves nothing."""
    calls = []

    def spy(self, *args, **kwargs):
        calls.append(args)
        return None

    monkeypatch.setattr(SqlParserFactory, "parse_sql", spy)
    return calls


@pytest.mark.parametrize("script", SCRIPTS)
@pytest.mark.parametrize("dialect", _sql_dialects())
def test_analysis_builds_no_text_model(dialect, script, text_model_calls):
    with warnings.catch_warnings():
        warnings.simplefilter("error", DeprecationWarning)
        analyse_script(script, dialect)

    assert text_model_calls == []


def test_a_parser_that_cannot_be_built_is_reported_not_replaced_by_a_text_model(
    monkeypatch, text_model_calls
):
    def refuse(self):
        raise ParserError("no parser")

    monkeypatch.setattr(SqlParserFactory, "get_parser", refuse)
    analysis = analyse_script(SCRIPT, "postgresql")

    assert analysis.errors == ("parser error: no parser",)
    assert analysis.statements == ()
    assert text_model_calls == []


def test_a_reader_that_raises_propagates(monkeypatch):
    def broken(self, statement):
        raise RuntimeError("reader bug")

    monkeypatch.setattr(PostgresqlQuirks, "statement_facts", broken)

    with pytest.raises(RuntimeError, match="reader bug"):
        analyse_script(SCRIPT, "postgresql")


class _NoReaderQuirks(PostgresqlQuirks):
    statement_facts_class = None


@pytest.fixture
def no_reader_plugin(monkeypatch):
    real = ProviderRegistry.get_quirks.__func__
    monkeypatch.setattr(
        ProviderRegistry,
        "get_quirks",
        classmethod(lambda cls, d: _NoReaderQuirks(d) if d == "noreader" else real(cls, d)),
    )


def test_plugin_without_a_facts_reader_is_reported_not_guessed(no_reader_plugin, text_model_calls):
    analysis = analyse_script(SCRIPT, "noreader")

    assert analysis.statements == ()
    assert analysis.cautions == ()
    assert analysis.errors == ("statement facts unavailable for dialect 'noreader'",)
    assert text_model_calls == []


def test_lint_marks_a_script_of_a_plugin_without_a_facts_reader_for_review(no_reader_plugin):
    lint = lint_script("DROP TABLE a; DELETE FROM b;", "noreader", "V1__x.sql")

    assert lint.verdict == REVIEW
    assert lint.findings == ()
    assert lint.errors == ("statement facts unavailable for dialect 'noreader'",)
