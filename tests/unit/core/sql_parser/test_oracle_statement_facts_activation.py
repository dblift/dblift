"""Oracle statement facts activate every consumer."""

from dblift.core.migration.sql.script_analysis import analyse_script
from dblift.core.migration.sql.statement_reader import StatementReader
from dblift.core.sql_parser.statement_facts import SqlglotStatementFactsReader
from dblift.core.sql_parser.statement_facts_parser import StatementFactsParser
from dblift.db.dml_analysis import (
    analyze_dml,
    dml_where_predicate,
    is_full_table_dml,
    statement_dml_table,
)
from dblift.db.provider_registry import ProviderRegistry
from tests.support.facts_parser import facts_parser

_quirks = ProviderRegistry.get_quirks

CTE_UPDATE = "WITH x AS (SELECT 1 a FROM dual) UPDATE child SET id = 2"
UPDATE = "UPDATE child SET id = 2 WHERE id = 1"


def test_oracle_plugin_reads_statement_facts():
    quirks = _quirks("oracle")

    assert quirks.supports_statement_facts
    assert quirks.sqlglot_dialect == "oracle"
    assert isinstance(quirks.statement_facts_reader(), SqlglotStatementFactsReader)


def test_the_facts_parser_reads_the_dialect():
    factory = facts_parser("oracle")
    parser = factory

    assert isinstance(parser, StatementFactsParser)
    assert parser.dialect_name == "oracle"
    assert [obj.name for obj in factory.extract_objects(UPDATE)] == ["CHILD"]
    assert factory.parse_sql(UPDATE).success


def test_script_analysis_goes_through_facts():
    update = analyse_script("UPDATE child SET id = 2", "oracle")
    assert [caution.code for caution in update.cautions] == ["dml-no-where"]

    comment = analyse_script("COMMENT ON TABLE t IS 'x'", "oracle")
    assert comment.errors == ()
    assert [obj.name for obj in comment.statements[0].objects] == ["T"]


def test_analyzer_extracts_objects_from_facts():
    analyzer = StatementReader("oracle")

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
