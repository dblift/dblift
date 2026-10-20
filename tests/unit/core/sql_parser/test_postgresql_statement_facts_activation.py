"""PostgreSQL-family statement facts activate every consumer."""

from unittest.mock import MagicMock

import pytest

from dblift.core.migration.scripting.undo_script_generator import UndoScriptGenerator
from dblift.core.migration.sql.script_analysis import CHANGES_ROWS, analyse_script
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
from dblift.db.provider_registry import ProviderRegistry
from tests.unit._migration_factory import make_migration

_quirks = ProviderRegistry.get_quirks

FAMILY = [
    "postgresql",
    "cockroachdb",
    "yugabytedb",
    "aurora-postgresql",
    "alloydb",
    "citus",
    "neon",
    "supabase",
    "timescaledb",
]
CTE_UPDATE = "WITH x AS (SELECT 1) UPDATE child SET id = 2"
COPY_FROM = "COPY child FROM 'input.csv'"
TRIGGER = "CREATE TRIGGER tg AFTER INSERT ON t FOR EACH ROW EXECUTE FUNCTION f()"
FUNCTION = "CREATE OR REPLACE FUNCTION f() RETURNS int AS $$ SELECT 1 $$ LANGUAGE sql"


def _undo(sql, dialect="postgresql"):
    migration = make_migration(script_name="V1__x.sql", content=sql)
    return UndoScriptGenerator(dialect)._generate_undo_statements(migration)


@pytest.mark.parametrize("dialect", FAMILY)
def test_family_plugins_read_statement_facts(dialect):
    quirks = _quirks(dialect)

    assert quirks.supports_statement_facts
    assert isinstance(quirks.statement_facts_reader(), SqlglotStatementFactsReader)


@pytest.mark.parametrize("dialect", FAMILY)
def test_hybrid_factory_serves_the_facts_parser(dialect):
    factory = SqlParserFactory(dialect, "hybrid")
    parser = factory.get_parser()

    assert isinstance(parser, StatementFactsParser)
    assert parser.dialect_name == dialect
    for sql in (CTE_UPDATE, COPY_FROM):
        assert [obj.name for obj in factory.extract_objects(sql)] == ["child"]
        assert factory.parse_sql(sql).success
        assert factory.validate_sql(sql)["valid"]


@pytest.mark.parametrize("dialect", FAMILY)
def test_regex_factory_type_keeps_the_regex_parser(dialect):
    assert isinstance(SqlParserFactory(dialect, "regex").get_parser(), PostgreSqlRegexParser)


@pytest.mark.parametrize("dialect", FAMILY)
def test_sqlglot_factory_type_is_refused(dialect):
    with pytest.raises(ValueError, match="StatementFactsParser"):
        SqlParserFactory(dialect, "sqlglot").get_parser()


@pytest.mark.parametrize("parser_class", [HybridParser, SqlGlotParser])
def test_direct_generic_parser_construction_rejects_postgresql(parser_class):
    with pytest.raises(ValueError, match="StatementFactsParser"):
        parser_class("postgresql")


@pytest.mark.parametrize("dialect", ["postgresql", "cockroachdb"])
def test_script_analysis_goes_through_facts(dialect):
    trigger = analyse_script(TRIGGER, dialect)
    assert trigger.errors == ()
    assert "tg" in [(obj.name) for obj in trigger.statements[0].objects]

    comment = analyse_script("COMMENT ON TABLE t IS 'x'", dialect)
    assert [obj.name for obj in comment.statements[0].objects] == ["t"]

    update = analyse_script("UPDATE child SET id = 2", dialect)
    assert [caution.code for caution in update.cautions] == ["dml-no-where"]

    drop = analyse_script("DROP SCHEMA s CASCADE", dialect)
    assert [caution.code for caution in drop.cautions] == ["drop-schema"]

    comment_only = analyse_script("-- note\n/* more */", dialect)
    assert comment_only.statements == ()
    assert comment_only.errors == ()


def test_analyzer_extracts_objects_from_facts_only(monkeypatch):
    analyzer = SqlAnalyzer("postgresql")

    def forbidden(*args, **kwargs):
        raise AssertionError("text extraction reached")

    monkeypatch.setattr(analyzer, "_extract_objects_regex", forbidden)

    assert [obj["object_name"] for obj in analyzer.extract_objects(CTE_UPDATE)] == [
        "default_schema.child"
    ]
    assert analyzer.analyze_statement(CTE_UPDATE)["parsed_with"] == "facts"


UPDATE_ONLY = "UPDATE ONLY child SET id = 2 WHERE id = 1"


def test_dml_helpers_take_the_facts_path_through_the_plugin():
    quirks = _quirks("postgresql")

    assert analyze_dml(UPDATE_ONLY, quirks=quirks).table == "child"
    assert statement_dml_table(UPDATE_ONLY, quirks=quirks) == "child"
    assert dml_where_predicate(UPDATE_ONLY, quirks=quirks) == "id = 1"
    assert not is_full_table_dml(UPDATE_ONLY, quirks=quirks)
    assert is_full_table_dml("UPDATE ONLY child SET id = 2", quirks=quirks)


def test_dml_helpers_resolve_the_deprecated_dialect_keyword_to_the_plugin():
    assert analyze_dml(UPDATE_ONLY, sqlglot_dialect="postgres").table == "child"
    assert dml_where_predicate(UPDATE_ONLY, sqlglot_dialect="postgres") == "id = 1"
    assert is_full_table_dml("DELETE FROM ONLY child", sqlglot_dialect="postgres")


@pytest.mark.parametrize(
    "sql",
    ["CREATE TABLE s.t (a int)", "UPDATE child SET id = 2"],
)
def test_execution_journal_receives_the_facts_objects(sql):
    provider = MagicMock(spec=["execute_statement"])
    provider.execute_statement.return_value = 1
    journal = MagicMock()
    service = SqlExecutionService(
        provider, SqlAnalyzer("postgresql"), journal=journal, quirks=_quirks("postgresql")
    )

    service.execute_statement(sql)

    objects = journal.record_object_changes.call_args.args[2]
    expected = "t" if sql.startswith("CREATE") else "child"
    assert [(obj["object_type"], obj["object_name"]) for obj in objects] == [("TABLE", expected)]


@pytest.mark.parametrize(
    "sql",
    [
        "CREATE TABLE s.t (a int)",
        "ALTER TABLE t ADD COLUMN c INT",
        "ALTER TABLE t ADD CONSTRAINT uq UNIQUE (c)",
        "CREATE INDEX ix ON t (c)",
        "CREATE VIEW v AS SELECT 1",
        "CREATE SEQUENCE q",
        "COMMENT ON TABLE t IS 'x'",
        "INSERT INTO t VALUES (1)",
        TRIGGER,
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


@pytest.mark.parametrize(
    "sql", [TRIGGER, "CREATE TRIGGER tg BEFORE UPDATE ON t EXECUTE FUNCTION f()"]
)
def test_undo_never_emits_a_drop_trigger_without_its_table(sql):
    assert not [s for s in _undo(sql) if s.sql.startswith("DROP TRIGGER")]


def test_data_changing_cte_keeps_the_changes_rows_caution_for_its_outer_target():
    script = (
        "WITH d AS (DELETE FROM src WHERE id = 1 RETURNING id) "
        "INSERT INTO log(msg) SELECT id FROM d"
    )
    cautions = analyse_script(script, "postgresql").cautions
    assert [(c.level, "log" in c.reason) for c in cautions] == [(CHANGES_ROWS, True)]


def test_read_only_cte_raises_no_caution():
    assert analyse_script("WITH x AS (SELECT 1) SELECT * FROM x", "postgresql").cautions == ()


@pytest.mark.parametrize("sql", ["REPLACE INTO t VALUES (1)", "INSERT INTO t VALUES (1)"])
def test_an_opaque_dml_with_a_target_gets_no_second_caution(sql):
    assert analyse_script(sql, "postgresql").cautions == ()
