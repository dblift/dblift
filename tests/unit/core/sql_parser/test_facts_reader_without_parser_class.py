"""A plugin that declares a statement-facts reader needs no parser class of its own."""

import pytest

from dblift.core.migration.sql.script_analysis import analyse_script
from dblift.core.sql_parser import SqlParserFactory
from dblift.core.sql_parser.statement_facts import SqlglotStatementFactsReader
from dblift.db.provider_registry import ProviderRegistry

pytestmark = pytest.mark.unit

DIALECTS = ["cockroachdb", "postgresql"]


@pytest.fixture(params=DIALECTS)
def reader_dialect(request, monkeypatch):
    """A dialect whose quirks gained a reader but kept their inherited parser_class."""
    quirks = ProviderRegistry.get_quirks(request.param)
    monkeypatch.setattr(type(quirks), "statement_facts_class", SqlglotStatementFactsReader)
    assert quirks.supports_statement_facts
    return request.param


def test_factory_returns_a_facts_parser(reader_dialect):
    parser = SqlParserFactory(reader_dialect).get_parser()

    assert parser.dialect_name == reader_dialect
    assert parser.split_for_analysis("DROP TABLE t; SELECT 1;") == ["DROP TABLE t", "SELECT 1"]
    result = parser.parse_sql("DROP TABLE t;")
    assert result.success, result.errors
    assert [(o.name) for o in parser.extract_objects("DROP TABLE t;")] == ["t"]
    assert parser.validate_sql("DROP TABLE t;")["valid"]


@pytest.mark.parametrize("mode", ["hybrid", "regex"])
def test_factory_serves_a_plugin_whose_parser_class_is_the_default(mode, monkeypatch):
    quirks = ProviderRegistry.get_quirks("cockroachdb")
    monkeypatch.setattr(type(quirks), "statement_facts_class", SqlglotStatementFactsReader)
    monkeypatch.setattr(type(quirks), "parser_class", lambda self, parser_type: None)

    parser = SqlParserFactory("cockroachdb", mode).get_parser()

    assert parser.dialect_name == "cockroachdb"
    assert parser.split_for_analysis("DROP TABLE t;") == ["DROP TABLE t"]


def test_analyse_script_analyses_instead_of_raising(reader_dialect):
    analysis = analyse_script("DROP TABLE t;", reader_dialect)

    assert analysis.errors == ()
    assert [s.operation for s in analysis.statements] == ["DROP"]
    assert [o.name for o in analysis.statements[0].objects] == ["t"]


def test_analyse_script_never_raises_when_no_parser_can_be_built(reader_dialect, monkeypatch):
    quirks_class = type(ProviderRegistry.get_quirks(reader_dialect))
    monkeypatch.setattr(quirks_class, "lexical_spec", lambda self: None)
    analysis = analyse_script("DROP TABLE t;", reader_dialect)

    assert analysis.statements == ()
    assert analysis.errors


def _plugin_returning(monkeypatch, cls):
    quirks = ProviderRegistry.get_quirks("cockroachdb")
    monkeypatch.setattr(type(quirks), "statement_facts_class", SqlglotStatementFactsReader)
    monkeypatch.setattr(type(quirks), "parser_class", lambda self, parser_type: cls)


def test_analyse_script_does_not_swallow_a_programming_error_from_construction(
    reader_dialect, monkeypatch
):
    def broken(self):
        raise AttributeError("plugin bug")

    monkeypatch.setattr(type(ProviderRegistry.get_quirks(reader_dialect)), "lexical_spec", broken)

    with pytest.raises(AttributeError):
        analyse_script("DROP TABLE t;", reader_dialect)
