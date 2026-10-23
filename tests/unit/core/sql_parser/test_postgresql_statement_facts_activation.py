"""PostgreSQL-family statement facts activate every consumer."""

from unittest.mock import MagicMock

import pytest

from dblift.core.migration.sql.script_analysis import CHANGES_ROWS, analyse_script
from dblift.core.migration.sql.sql_analyzer import SqlAnalyzer
from dblift.core.migration.sql.sql_execution_service import SqlExecutionService
from dblift.core.sql_parser import SqlParserFactory
from dblift.core.sql_parser.statement_facts import SqlglotStatementFactsReader
from dblift.core.sql_parser.statement_facts_parser import StatementFactsParser
from dblift.db.dml_analysis import (
    analyze_dml,
    dml_where_predicate,
    is_full_table_dml,
    statement_dml_table,
)
from dblift.db.provider_registry import ProviderRegistry

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


def test_analyzer_extracts_objects_from_facts():
    analyzer = SqlAnalyzer("postgresql")

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


def test_data_changing_cte_reports_the_rows_it_changes_in_its_own_table():
    script = (
        "WITH d AS (DELETE FROM src WHERE id = 1 RETURNING id) "
        "INSERT INTO log(msg) SELECT id FROM d"
    )
    cautions = analyse_script(script, "postgresql").cautions
    assert [(c.level, "src" in c.reason) for c in cautions] == [(CHANGES_ROWS, True)]


def test_an_unreadable_data_changing_cte_keeps_the_caution_for_its_outer_target():
    script = (
        "WITH m AS (MERGE INTO src USING s ON src.id = s.id WHEN MATCHED THEN DELETE) "
        "INSERT INTO log(msg) SELECT 1"
    )
    cautions = analyse_script(script, "postgresql").cautions
    assert [(c.level, "log" in c.reason) for c in cautions] == [(CHANGES_ROWS, True)]


def test_read_only_cte_raises_no_caution():
    assert analyse_script("WITH x AS (SELECT 1) SELECT * FROM x", "postgresql").cautions == ()


@pytest.mark.parametrize("sql", ["REPLACE INTO t VALUES (1)", "INSERT INTO t VALUES (1)"])
def test_an_opaque_dml_with_a_target_gets_no_second_caution(sql):
    assert analyse_script(sql, "postgresql").cautions == ()


def test_the_opaque_cte_diagnostic_names_the_dialect_that_read_the_statement():
    from dblift.core.sql_parser.sqlglot_statement_facts import read_statement_facts

    sql = "WITH t AS (SELECT * FROM t) DELETE FROM u"

    assert (
        read_statement_facts(sql, dialect="postgres").diagnostic is None
    )  # an unqualified t in its own body is the table, not the CTE
    assert read_statement_facts(sql, dialect="redshift").diagnostic.startswith("redshift CTE")


@pytest.mark.parametrize(
    ("sql", "kind", "operation"),
    [
        ("ALTER TABLE t ADD c int", "DDL", "ALTER"),
        ("CREATE INDEX i ON t (a)", "DDL", "CREATE"),
        ("DROP TABLE t", "DDL", "DROP"),
        ("DELETE FROM t", "DML", "DELETE"),
        ("WITH x AS (SELECT 1) SELECT * FROM x", "QUERY", "SELECT"),
        # A data-modifying CTE decides nothing: the outer verb does.
        (
            "WITH deleted AS (DELETE FROM src WHERE id = 1 RETURNING id) "
            "INSERT INTO app_logs(msg) SELECT 'removed ' || id FROM deleted",
            "DML",
            "INSERT",
        ),
        # A CTE that writes under a SELECT is not claimed to be a read.
        (
            "WITH x AS (INSERT INTO src VALUES (99) RETURNING id) SELECT * FROM x",
            "UNKNOWN",
            "SELECT",
        ),
    ],
)
def test_statement_kind_and_operation_come_from_the_facts(sql, kind, operation):
    facts = _quirks("postgresql").statement_facts(sql)

    assert (facts.kind, facts.operation) == (kind, operation)


def test_an_unreadable_data_changing_cte_keeps_the_caution_for_its_outer_target():
    script = (
        "WITH m AS (MERGE INTO src USING s ON src.id = s.id WHEN MATCHED THEN DELETE) "
        "INSERT INTO log(msg) SELECT 1"
    )
    cautions = analyse_script(script, "postgresql").cautions
    assert [(c.level, "log" in c.reason) for c in cautions] == [(CHANGES_ROWS, True)]
