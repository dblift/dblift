"""DuckDB statement facts retain effects through scanner-backed parser projections."""

import json
from pathlib import Path

import pytest
from sqlglot import exp

from dblift.core.sql_model.base import SqlObjectType
from dblift.core.sql_parser.sqlglot_statement_facts import _copy_facts, read_statement_facts
from dblift.core.sql_parser.statement_facts import NamedObject
from dblift.db.plugins.duckdb.parser._script import scan_script
from dblift.db.plugins.duckdb.parser.duckdb_facts_parser import DuckDBFactsParser
from dblift.db.plugins.duckdb.quirks import DuckDBQuirks

CASES = json.loads(
    Path(__file__).with_name("duckdb_statement_facts_corpus.json").read_text(encoding="utf-8")
)["cases"]


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["id"])
def test_duckdb_facts_keep_targets_references_and_effects(case):
    statements = scan_script(case["sql"])
    assert len(statements) == 1
    facts = read_statement_facts(statements[0].text, dialect="duckdb")

    assert {
        "operation": facts.operation,
        "kind": facts.kind,
        "objects": [
            {"name": obj.name, "type": obj.type.value, "role": obj.role, "schema": obj.schema}
            for obj in facts.objects
        ],
        "target": facts.target,
        "predicate": facts.predicate,
        "affected_columns": list(facts.affected_columns),
        "events": sorted(facts.events) if facts.events else None,
        "diagnostic": facts.diagnostic,
        "error": facts.error,
    } == case["facts"]
    assert facts.action is None
    assert [obj.name for obj in facts.affected_objects] == [
        obj["name"] for obj in case["facts"]["objects"] if obj["role"] != "referenced"
    ]


def test_duckdb_facts_activate_parser_consumers():
    quirks = DuckDBQuirks()
    assert quirks.supports_statement_facts
    assert quirks.parser_class("regex") is DuckDBFactsParser
    assert quirks.parser_class("hybrid") is DuckDBFactsParser
    assert quirks.parser_class("sqlglot") is DuckDBFactsParser


@pytest.mark.parametrize("dialect", ["sqlite", "postgres", "oracle", "snowflake", "tsql"])
def test_merge_facts_remain_opaque_for_other_dialects(dialect):
    facts = read_statement_facts(CASES[0]["sql"], dialect=dialect)

    assert facts.kind == "UNKNOWN"
    assert facts.target is None
    assert facts.objects == ()
    assert facts.events is None
    assert facts.affected_columns == ()
    assert facts.opaque


@pytest.mark.parametrize("dialect", ["sqlite", "postgres", "oracle", "snowflake", "tsql"])
def test_copy_facts_remain_opaque_for_other_dialects(dialect):
    facts = read_statement_facts("COPY items FROM '/tmp/items.csv'", dialect=dialect)

    assert facts.operation == "COPY"
    assert facts.kind == "UNKNOWN"
    assert facts.target is None
    assert facts.target_sql is None
    assert facts.objects == ()
    assert facts.events is None
    assert facts.affected_columns == ()
    assert facts.action is None
    assert facts.opaque


def test_copy_from_preserves_quoted_target_sql():
    facts = read_statement_facts(
        'COPY "Sales"."Order Items" (id) FROM \'/tmp/items.csv\'', dialect="duckdb"
    )

    assert facts.target_sql == '"Sales"."Order Items"'


@pytest.mark.parametrize("direction", [None, "FROM", 0, 1])
def test_copy_unknown_direction_does_not_claim_read_or_write_effects(direction):
    node = exp.Copy(
        this=exp.to_table("items"), kind=direction, files=[exp.Literal.string("items.csv")]
    )

    facts = _copy_facts(node, "COPY items FROM 'items.csv'")

    assert facts.operation == "COPY"
    assert facts.kind == "UNKNOWN"
    assert facts.objects == ()
    assert facts.target is None
    assert facts.target_sql is None
    assert facts.events is None
    assert facts.affected_columns == ()
    assert facts.opaque


@pytest.mark.parametrize("update", ["UPDATE", "UPDATE SET *"])
def test_merge_implicit_update_columns_keep_the_target_and_event(update):
    facts = read_statement_facts(
        f"MERGE INTO t USING s ON t.id=s.id WHEN MATCHED THEN {update}", dialect="duckdb"
    )

    assert facts.target == "t"
    assert facts.events == frozenset({"UPDATE"})
    # The statement declares no individual columns; their names need the database catalogue.
    assert facts.affected_columns == ()
    assert not facts.opaque


@pytest.mark.parametrize(
    ("sql", "name", "schema"),
    [
        ("TRUNCATE t", "t", None),
        ("TRUNCATE TABLE t", "t", None),
        ("TRUNCATE TABLE main.t", "t", "main"),
        ('TRUNCATE TABLE "main"."Order Items"', "Order Items", "main"),
    ],
)
def test_duckdb_truncate_facts_name_the_altered_table(sql, name, schema):
    facts = read_statement_facts(sql, dialect="duckdb")

    assert facts.operation == "TRUNCATE"
    assert facts.kind == "DDL"
    assert facts.objects == (NamedObject(name, SqlObjectType.TABLE, "altered", schema),)
    assert not facts.opaque


@pytest.mark.parametrize(
    "sql",
    [
        "TRUNCATE TABLE (SELECT * FROM t)",
        "TRUNCATE TABLE read_csv('x')",
        "TRUNCATE t,u",
    ],
)
def test_duckdb_truncate_non_table_targets_are_opaque(sql):
    facts = read_statement_facts(sql, dialect="duckdb")

    assert facts.operation == "TRUNCATE"
    assert facts.objects == ()
    assert facts.opaque


def test_duckdb_truncate_facts_do_not_change_other_mappings():
    delete = read_statement_facts("DELETE FROM t WHERE id = 1", dialect="duckdb")
    drop = read_statement_facts("DROP TABLE t", dialect="duckdb")
    oracle_truncate = read_statement_facts("TRUNCATE TABLE t", dialect="oracle")

    assert delete.operation == "DELETE"
    assert delete.kind == "DML"
    assert delete.objects == (NamedObject("t", SqlObjectType.TABLE, "altered"),)
    assert drop.operation == "DROP"
    assert drop.kind == "DDL"
    assert drop.objects == (NamedObject("t", SqlObjectType.TABLE, "dropped"),)
    assert oracle_truncate.operation == "TRUNCATE"
    assert oracle_truncate.kind == "UNKNOWN"
    assert oracle_truncate.objects == ()
    assert oracle_truncate.opaque
