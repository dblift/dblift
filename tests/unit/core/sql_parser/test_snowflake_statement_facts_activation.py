"""Snowflake reads statement facts and every consumer takes the facts path for it."""

from unittest.mock import MagicMock

import pytest

from dblift.core.migration.sql.script_analysis import analyse_script
from dblift.core.migration.sql.sql_execution_service import SqlExecutionService
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

UPDATE_ALIAS = "UPDATE child AS c SET id = 2 WHERE c.id = 1"
CTE_UPDATE = "WITH x AS (SELECT 1 AS a) UPDATE child SET id = 2 FROM x WHERE child.id = x.a"
FUNCTION = "CREATE OR REPLACE FUNCTION s.f(a INT) RETURNS INT LANGUAGE SQL AS 'a + 1'"


def test_snowflake_reads_statement_facts():
    quirks = _quirks("snowflake")

    assert quirks.supports_statement_facts
    assert isinstance(quirks.statement_facts_reader(), SqlglotStatementFactsReader)
    assert quirks.statement_facts_reader().dialect == "snowflake"


def test_the_facts_parser_reads_the_dialect():
    factory = facts_parser("snowflake")
    parser = factory

    assert isinstance(parser, StatementFactsParser)
    assert parser.dialect_name == "snowflake"
    assert [obj.name for obj in factory.extract_objects(CTE_UPDATE)] == ["CHILD"]
    assert factory.parse_sql(CTE_UPDATE).success
    assert factory.validate_sql(CTE_UPDATE)["valid"]


def test_regex_factory_type_serves_the_facts_parser_on_the_lexical_spec():
    from tests.support.facts_parser import facts_parser

    assert isinstance(facts_parser("snowflake"), StatementFactsParser)
    assert isinstance(facts_parser("snowflake"), StatementFactsParser)
    assert facts_parser("snowflake").split_statements("SELECT 1; SELECT 2;") == [
        "SELECT 1",
        "SELECT 2",
    ]


def test_script_analysis_goes_through_facts():
    update = analyse_script("UPDATE child SET id = 2", "snowflake")
    assert [caution.code for caution in update.cautions] == ["dml-no-where"]

    drop = analyse_script("DROP SCHEMA s CASCADE", "snowflake")
    assert [caution.code for caution in drop.cautions] == ["drop-schema"]
    assert [(obj.name, obj.type) for obj in drop.statements[0].objects] == [("S", "SCHEMA")]

    view = analyse_script(
        'CREATE MATERIALIZED VIEW "S"."MV" AS SELECT id FROM "S"."T"', "snowflake"
    )
    assert ("MV", "MATERIALIZED_VIEW") in [
        (obj.name, obj.type) for obj in view.statements[0].objects
    ]

    comment_only = analyse_script("-- note\n/* more */", "snowflake")
    assert comment_only.statements == ()
    assert comment_only.errors == ()


def test_analyzer_extracts_objects_from_facts():
    analyzer = StatementReader("snowflake")

    assert [obj["object_name"] for obj in analyzer.extract_objects(CTE_UPDATE)] == [
        "default_schema.CHILD"
    ]
    assert analyzer.analyze_statement(CTE_UPDATE)["parsed_with"] == "facts"


def test_dml_helpers_take_the_facts_path_through_the_plugin():
    quirks = _quirks("snowflake")

    assert analyze_dml(UPDATE_ALIAS, quirks=quirks).table == "CHILD"
    assert statement_dml_table(UPDATE_ALIAS, quirks=quirks) == "child"
    assert dml_where_predicate(UPDATE_ALIAS, quirks=quirks) == "c.id = 1"
    assert not is_full_table_dml(UPDATE_ALIAS, quirks=quirks)
    assert is_full_table_dml("DELETE FROM child", quirks=quirks)


@pytest.mark.parametrize(
    "sql, expected",
    [
        ('CREATE TABLE "S"."T" (a INT)', ("TABLE", "T")),
        ("UPDATE child SET id = 2", ("TABLE", "CHILD")),
        ("CREATE SCHEMA app", ("SCHEMA", "APP")),
        ("DROP MATERIALIZED VIEW mv", ("MATERIALIZED_VIEW", "MV")),
    ],
)
def test_execution_journal_receives_the_facts_objects(sql, expected):
    provider = MagicMock(spec=["execute_statement"])
    provider.execute_statement.return_value = 1
    journal = MagicMock()
    service = SqlExecutionService(
        provider, StatementReader("snowflake"), journal=journal, quirks=_quirks("snowflake")
    )

    service.execute_statement(sql)

    objects = journal.record_object_changes.call_args.args[2]
    assert [(obj["object_type"], obj["object_name"]) for obj in objects] == [expected]


@pytest.mark.parametrize(
    "sql",
    ["CREATE STAGE st", "CREATE TAG tg", 'DROP FILE FORMAT IF EXISTS "S"."F"'],
)
def test_unmodelled_object_kinds_reach_no_journal_object(sql):
    provider = MagicMock(spec=["execute_statement"])
    provider.execute_statement.return_value = 1
    journal = MagicMock()
    service = SqlExecutionService(
        provider, StatementReader("snowflake"), journal=journal, quirks=_quirks("snowflake")
    )

    service.execute_statement(sql)

    provider.execute_statement.assert_called_once()
    assert not journal.record_object_changes.called or not (
        journal.record_object_changes.call_args.args[2]
    )


@pytest.mark.parametrize(
    "unquoted, quoted",
    [
        ("CREATE SCHEMA app", 'CREATE SCHEMA "app"'),
        ("CREATE TABLE app.t (id INT)", 'CREATE TABLE "app"."t" (id INT)'),
        ("DROP TABLE app.t", 'DROP TABLE "app"."t"'),
        ("CREATE MATERIALIZED VIEW log AS SELECT 1", 'CREATE MATERIALIZED VIEW "log" AS SELECT 1'),
    ],
)
def test_unquoted_and_quoted_names_are_told_apart(unquoted, quoted):
    """Measured on Snowflake 10.38.100 with QUOTED_IDENTIFIERS_IGNORE_CASE = FALSE: an unquoted
    schema or materialized view is stored in upper case and a quoted one as written, so
    ``DB.SCH`` and ``DB."sch"`` (or ``LOG`` and ``"log"``) are two objects."""
    from dblift.core.sql_parser.sqlglot_statement_facts import read_statement_facts

    first = read_statement_facts(unquoted, dialect="snowflake")
    second = read_statement_facts(quoted, dialect="snowflake")

    assert first.objects != second.objects
    assert all(obj.name == obj.name.upper() for obj in first.objects)
    assert all(obj.name == obj.name.lower() for obj in second.objects)
