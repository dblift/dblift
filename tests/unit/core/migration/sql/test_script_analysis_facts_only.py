"""``analyse_script`` reads statement facts and nothing else.

Every plugin that runs SQL migrations has a statement-facts reader, so the script analysis never
builds a text model. A plugin without a reader is reported, not guessed at.
"""

from __future__ import annotations

import warnings
from types import SimpleNamespace

import pytest

import dblift.core.migration.sql.script_analysis as script_analysis
from dblift.core.migration.sql.script_analysis import analyse_script
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


@pytest.mark.parametrize("dialect", _sql_dialects())
def test_analysis_builds_no_text_model(dialect, monkeypatch):
    def boom(*args, **kwargs):
        raise AssertionError("the text-model path was taken")

    monkeypatch.setattr(script_analysis.SqlParserFactory, "parse_sql", boom)
    with warnings.catch_warnings():
        warnings.simplefilter("error", DeprecationWarning)
        analysis = analyse_script(SCRIPT, dialect)

    assert [s.operation for s in analysis.statements] == ["CREATE", "DROP", "DELETE"]


def test_plugin_without_a_facts_reader_is_reported_not_guessed(monkeypatch):
    quirks = SimpleNamespace(supports_statement_facts=False)
    monkeypatch.setattr(ProviderRegistry, "get_quirks", classmethod(lambda cls, d: quirks))

    def boom(*args, **kwargs):
        raise AssertionError("the text-model path was taken")

    monkeypatch.setattr(script_analysis.SqlParserFactory, "parse_sql", boom)
    analysis = analyse_script(SCRIPT, "nofacts")

    assert analysis.statements == ()
    assert analysis.cautions == ()
    assert analysis.errors == ("statement facts unavailable for dialect 'nofacts'",)
