"""Oracle statement facts activate every consumer."""

import pytest

from dblift.core.migration.scripting.undo_script_generator import UndoScriptGenerator
from dblift.core.migration.sql.script_analysis import analyse_script
from dblift.core.migration.sql.sql_analyzer import SqlAnalyzer
from dblift.core.sql_parser import SqlParserFactory
from dblift.core.sql_parser.hybrid_parser import HybridParser
from dblift.core.sql_parser.sqlglot_parser import SqlGlotParser
from dblift.core.sql_parser.statement_facts import SqlglotStatementFactsReader
from dblift.core.sql_parser.statement_facts_parser import StatementFactsParser
from dblift.db.dml_analysis import (
    analyze_dml,
    dml_where_predicate,
    is_full_table_dml,
    statement_dml_table,
)
from dblift.db.plugins.oracle.parser.oracle_parser import OracleParser
from dblift.db.provider_registry import ProviderRegistry
from tests.unit._migration_factory import make_migration

_quirks = ProviderRegistry.get_quirks

CTE_UPDATE = "WITH x AS (SELECT 1 a FROM dual) UPDATE child SET id = 2"
UPDATE = "UPDATE child SET id = 2 WHERE id = 1"


def _undo(sql):
    migration = make_migration(script_name="V1__x.sql", content=sql)
    return UndoScriptGenerator("oracle")._generate_undo_statements(migration)


def test_oracle_plugin_reads_statement_facts():
    quirks = _quirks("oracle")

    assert quirks.supports_statement_facts
    assert quirks.sqlglot_dialect == "oracle"
    assert isinstance(quirks.statement_facts_reader(), SqlglotStatementFactsReader)


def test_hybrid_factory_serves_the_facts_parser():
    factory = SqlParserFactory("oracle", "hybrid")
    parser = factory.get_parser()

    assert isinstance(parser, StatementFactsParser)
    assert parser.dialect_name == "oracle"
    assert [obj.name for obj in factory.extract_objects(UPDATE)] == ["CHILD"]
    assert factory.parse_sql(UPDATE).success


def test_regex_factory_type_keeps_the_regex_parser():
    assert isinstance(SqlParserFactory("oracle", "regex").get_parser(), OracleParser)


def test_sqlglot_factory_type_is_refused():
    with pytest.raises(ValueError, match="StatementFactsParser"):
        SqlParserFactory("oracle", "sqlglot").get_parser()


@pytest.mark.parametrize("parser_class", [HybridParser, SqlGlotParser])
def test_direct_generic_parser_construction_rejects_oracle(parser_class):
    with pytest.raises(ValueError, match="StatementFactsParser"):
        parser_class("oracle")


def test_script_analysis_goes_through_facts():
    update = analyse_script("UPDATE child SET id = 2", "oracle")
    assert [caution.code for caution in update.cautions] == ["dml-no-where"]

    comment = analyse_script("COMMENT ON TABLE t IS 'x'", "oracle")
    assert comment.errors == ()
    assert [obj.name for obj in comment.statements[0].objects] == ["T"]


def test_analyzer_extracts_objects_from_facts():
    analyzer = SqlAnalyzer("oracle")

    assert [obj["object_name"] for obj in analyzer.extract_objects(UPDATE)] == [
        "default_schema.CHILD"
    ]
    assert analyzer.analyze_statement(UPDATE)["parsed_with"] == "facts"


def test_dml_helpers_take_the_facts_path_through_the_plugin():
    quirks = _quirks("oracle")

    assert analyze_dml(UPDATE, quirks=quirks).table == "CHILD"
    assert statement_dml_table(UPDATE, quirks=quirks) == "child"  # as the statement writes it
    assert dml_where_predicate(UPDATE, quirks=quirks) == "id = 1"
    assert not is_full_table_dml(UPDATE, quirks=quirks)
    assert is_full_table_dml("DELETE FROM child", quirks=quirks)


@pytest.mark.parametrize(
    "sql",
    ["CREATE TABLE s.t (a NUMBER)", "ALTER TABLE t ADD (c NUMBER)", "INSERT INTO t VALUES (1)"],
)
def test_undo_asks_for_a_hand_written_reversal(sql):
    undo = _undo(sql)

    assert len(undo) == 1
    assert undo[0].requires_manual_review
    assert undo[0].sql.startswith("-- WARNING")


@pytest.mark.parametrize("sql", ["SELECT 1 FROM dual", "-- note\n/* more */"])
def test_undo_of_a_read_or_a_comment_is_empty(sql):
    assert _undo(sql) == []
