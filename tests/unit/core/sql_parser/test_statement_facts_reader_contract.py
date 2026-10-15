"""Plugin facts readers own their grammar requirements."""

import pytest

from dblift.core.sql_parser.hybrid_parser import HybridParser
from dblift.core.sql_parser.statement_facts import SqlglotStatementFactsReader, StatementFacts
from dblift.db.base_quirks import BaseQuirks
from dblift.db.plugins.db2.parser.db2_regex_parser import DB2RegexParser
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


@pytest.mark.parametrize("quirks_class", [BaseQuirks, Db2Quirks])
def test_plugin_without_reader_refuses_facts(quirks_class):
    quirks = quirks_class()
    assert not quirks.supports_statement_facts
    with pytest.raises(NotImplementedError, match="no statement facts reader"):
        quirks.statement_facts("DROP TABLE t")


def test_db2_parser_routes_remain_available_without_statement_facts():
    quirks = Db2Quirks()
    assert quirks.parser_class("regex") is DB2RegexParser
    assert quirks.parser_class("hybrid") is HybridParser
    assert quirks.parser_class("sqlglot") is None
