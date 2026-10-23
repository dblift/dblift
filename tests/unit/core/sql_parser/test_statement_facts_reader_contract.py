"""Plugin facts readers own their grammar requirements."""

import pytest

from dblift.core.sql_parser.statement_facts import SqlglotStatementFactsReader, StatementFacts
from dblift.db.base_quirks import BaseQuirks
from dblift.db.plugins.db2.parser.statement_facts import Db2FactsParser
from dblift.db.plugins.db2.quirks import Db2Quirks
from dblift.db.plugins.duckdb.quirks import DuckDBQuirks
from dblift.db.plugins.sqlite.parser.lexical_spec import SQLITE_SPEC
from dblift.db.plugins.sqlite.quirks import SqliteQuirks


@pytest.mark.parametrize("spec", [None, SQLITE_SPEC])
def test_plugin_reader_without_sqlglot_dialect_receives_lexical_spec(spec):
    class Reader:
        def __init__(self, dialect, lexical_spec):
            assert dialect is None
            self.spec = lexical_spec

        def read(self, sql):
            assert sql == "DROP TABLE t"
            return StatementFacts(
                "DROP", "DDL", target="t", diagnostic=self.spec.name if self.spec else None
            )

    class Quirks(BaseQuirks):
        statement_facts_class = Reader

        def lexical_spec(self):
            return spec

    quirks = Quirks()
    assert quirks.supports_statement_facts
    facts = quirks.statement_facts("DROP TABLE t")
    assert (facts.operation, facts.kind, facts.target) == ("DROP", "DDL", "t")
    assert facts.diagnostic == ("sqlite" if spec else None)


def test_sqlglot_reader_refuses_missing_dialect():
    with pytest.raises(ValueError, match="dialect"):
        SqlglotStatementFactsReader(None)


@pytest.mark.parametrize("quirks_class", [SqliteQuirks, DuckDBQuirks])
def test_existing_plugin_readers_keep_drop_identity(quirks_class):
    facts = quirks_class().statement_facts("DROP TABLE t")
    assert (facts.operation, facts.kind) == ("DROP", "DDL")
    assert [(obj.name, obj.type.value, obj.role) for obj in facts.objects] == [
        ("t", "TABLE", "dropped")
    ]


def test_plugin_without_reader_refuses_facts():
    quirks = BaseQuirks()
    assert not quirks.supports_statement_facts
    with pytest.raises(NotImplementedError, match="no statement facts reader"):
        quirks.statement_facts("DROP TABLE t")


def _no_argument_reader_quirks():
    class Reader:
        def __init__(self):
            pass

        def read(self, sql):
            return StatementFacts("SELECT", "QUERY")

    class Quirks(BaseQuirks):
        statement_facts_class = Reader

    return Quirks()


def test_reader_without_the_constructor_contract_is_named():
    with pytest.raises(TypeError, match=r"must accept \(dialect, spec\)"):
        _no_argument_reader_quirks().statement_facts("SELECT 1")


def test_a_reader_without_an_inspectable_signature_is_named():
    class Quirks(BaseQuirks):
        statement_facts_class = dict

    with pytest.raises(TypeError, match=r"must accept \(dialect, spec\)"):
        Quirks().statement_facts("SELECT 1")


def test_a_type_error_inside_a_conforming_constructor_is_not_relabelled():
    class Reader:
        def __init__(self, dialect, spec=None):
            raise TypeError("inner failure")

    class Quirks(BaseQuirks):
        statement_facts_class = Reader

    with pytest.raises(TypeError, match="inner failure"):
        Quirks().statement_facts("SELECT 1")


def assert_reader_conforms(quirks):
    reader = quirks.statement_facts_reader()
    assert isinstance(reader.read("SELECT 1"), StatementFacts)


def _registered_reader_quirks():
    from dblift.db.provider_registry import ProviderRegistry

    ProviderRegistry.discover_plugins()
    found = [ProviderRegistry.get_quirks(p.name) for p in ProviderRegistry.list_plugins()]
    return [q for q in found if q.supports_statement_facts]


@pytest.mark.parametrize("quirks", _registered_reader_quirks(), ids=lambda q: q.dialect_name)
def test_every_registered_reader_constructs_and_reads(quirks):
    assert_reader_conforms(quirks)


def test_the_reader_check_fails_a_reader_without_the_constructor_contract():
    with pytest.raises(TypeError):
        assert_reader_conforms(_no_argument_reader_quirks())


def test_the_reader_check_fails_a_reader_that_raises():
    class Reader:
        def __init__(self, dialect, spec=None):
            pass

        def read(self, sql):
            raise RuntimeError("crashed")

    class Quirks(BaseQuirks):
        statement_facts_class = Reader

    with pytest.raises(RuntimeError):
        assert_reader_conforms(Quirks())
