"""Redshift reads statement facts and every consumer takes the facts path for it."""

from unittest.mock import MagicMock

import pytest

from dblift.core.migration.scripting.undo_script_generator import UndoScriptGenerator
from dblift.core.migration.sql.script_analysis import analyse_script
from dblift.core.migration.sql.sql_analyzer import SqlAnalyzer
from dblift.core.migration.sql.sql_execution_service import SqlExecutionService
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
from dblift.db.plugins.postgresql.parser.postgresql_regex_parser import PostgreSqlRegexParser
from dblift.db.plugins.redshift.parser.redshift_regex_parser import RedshiftRegexParser
from dblift.db.provider_registry import ProviderRegistry
from tests.unit._migration_factory import make_migration

_quirks = ProviderRegistry.get_quirks

CTE_UPDATE = "WITH x AS (SELECT 1 AS a) UPDATE child SET id = 2 FROM x WHERE child.id = x.a"
COPY_FROM = "COPY child FROM 's3://bucket/prefix' IAM_ROLE default CSV"
FUNCTION = (
    "CREATE OR REPLACE FUNCTION f(a int) RETURNS int IMMUTABLE AS $$ SELECT $1 $$ LANGUAGE sql"
)
UPDATE_ALIAS = "UPDATE child AS c SET id = 2 WHERE c.id = 1"


def _undo(sql):
    migration = make_migration(script_name="V1__x.sql", content=sql)
    return UndoScriptGenerator("redshift")._generate_undo_statements(migration)


def test_redshift_reads_statement_facts():
    quirks = _quirks("redshift")

    assert quirks.supports_statement_facts
    assert isinstance(quirks.statement_facts_reader(), SqlglotStatementFactsReader)
    assert quirks.statement_facts_reader().dialect == "redshift"
    assert not quirks.undo_reverses_statement_facts


def test_hybrid_factory_serves_the_facts_parser():
    factory = SqlParserFactory("redshift", "hybrid")
    parser = factory.get_parser()

    assert isinstance(parser, StatementFactsParser)
    assert parser.dialect_name == "redshift"
    for sql in (CTE_UPDATE, COPY_FROM):
        assert [obj.name for obj in factory.extract_objects(sql)] == ["child"]
        assert factory.parse_sql(sql).success
        assert factory.validate_sql(sql)["valid"]


def test_regex_factory_type_keeps_the_regex_parser():
    parser = SqlParserFactory("redshift", "regex").get_parser()

    assert isinstance(parser, RedshiftRegexParser)
    assert isinstance(parser, PostgreSqlRegexParser)


def test_sqlglot_factory_type_is_refused():
    with pytest.raises(ValueError, match="StatementFactsParser"):
        SqlParserFactory("redshift", "sqlglot").get_parser()


@pytest.mark.parametrize("parser_class", [HybridParser, SqlGlotParser])
def test_direct_generic_parser_construction_rejects_redshift(parser_class):
    with pytest.raises(ValueError, match="StatementFactsParser"):
        parser_class("redshift")


def test_script_analysis_goes_through_facts():
    comment = analyse_script("COMMENT ON TABLE t IS 'x'", "redshift")
    assert [obj.name for obj in comment.statements[0].objects] == ["t"]

    update = analyse_script("UPDATE child SET id = 2", "redshift")
    assert [caution.code for caution in update.cautions] == ["dml-no-where"]

    drop = analyse_script("DROP SCHEMA s CASCADE", "redshift")
    assert [caution.code for caution in drop.cautions] == ["drop-schema"]

    created = analyse_script("SELECT a INTO TEMP t2 FROM t", "redshift")
    assert [(obj.name, obj.type) for obj in created.statements[0].objects] == [("t2", "TABLE")]

    comment_only = analyse_script("-- note\n/* more */", "redshift")
    assert comment_only.statements == ()
    assert comment_only.errors == ()


def test_analyzer_extracts_objects_from_facts_only(monkeypatch):
    analyzer = SqlAnalyzer("redshift")

    def forbidden(*args, **kwargs):
        raise AssertionError("text extraction reached")

    monkeypatch.setattr(analyzer, "_extract_objects_regex", forbidden)

    assert [obj["object_name"] for obj in analyzer.extract_objects(CTE_UPDATE)] == [
        "default_schema.child"
    ]
    assert analyzer.analyze_statement(CTE_UPDATE)["parsed_with"] == "facts"


def test_dml_helpers_take_the_facts_path_through_the_plugin():
    quirks = _quirks("redshift")

    assert analyze_dml(UPDATE_ALIAS, quirks=quirks).table == "child"
    assert statement_dml_table(UPDATE_ALIAS, quirks=quirks) == "child"
    assert dml_where_predicate(UPDATE_ALIAS, quirks=quirks) == "c.id = 1"
    assert not is_full_table_dml(UPDATE_ALIAS, quirks=quirks)
    assert is_full_table_dml("DELETE FROM child", quirks=quirks)


@pytest.mark.parametrize(
    "sql, expected",
    [
        ("CREATE TABLE s.t (a int) DISTKEY(a)", ("TABLE", "t")),
        ("UPDATE child SET id = 2", ("TABLE", "child")),
        ("SELECT a INTO TEMP made FROM child", ("TABLE", "made")),
    ],
)
def test_execution_journal_receives_the_facts_objects(sql, expected):
    provider = MagicMock(spec=["execute_statement"])
    provider.execute_statement.return_value = 1
    journal = MagicMock()
    service = SqlExecutionService(
        provider, SqlAnalyzer("redshift"), journal=journal, quirks=_quirks("redshift")
    )

    service.execute_statement(sql)

    objects = journal.record_object_changes.call_args.args[2]
    assert [(obj["object_type"], obj["object_name"]) for obj in objects] == [expected]


@pytest.mark.parametrize(
    "sql",
    [
        "CREATE TABLE s.t (a int)",
        "ALTER TABLE t ADD COLUMN c INT",
        "CREATE VIEW v AS SELECT 1",
        "COMMENT ON TABLE t IS 'x'",
        "INSERT INTO t VALUES (1)",
        FUNCTION,
    ],
)
def test_undo_asks_for_a_hand_written_reversal(sql):
    undo = _undo(sql)

    assert len(undo) == 1
    assert undo[0].requires_manual_review
    assert undo[0].sql.startswith("-- WARNING")


@pytest.mark.parametrize("sql", ["SELECT 1", "-- note\n/* more */"])
def test_undo_of_a_read_or_a_comment_is_empty(sql):
    assert _undo(sql) == []
