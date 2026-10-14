"""DuckDB statement facts retain effects without changing parser dispatch."""

import json
from pathlib import Path

import pytest
from sqlglot import exp

from dblift.core.sql_parser.hybrid_parser import HybridParser
from dblift.core.sql_parser.sqlglot_parser import SqlGlotParser
from dblift.core.sql_parser.sqlglot_statement_facts import _copy_facts, read_statement_facts
from dblift.db.plugins.duckdb.parser._script import scan_script
from dblift.db.plugins.duckdb.parser.duckdb_regex_parser import DuckDBRegexParser
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


def test_duckdb_facts_do_not_activate_parser_consumers():
    quirks = DuckDBQuirks()
    assert not quirks.supports_statement_facts
    assert quirks.parser_class("regex") is DuckDBRegexParser
    assert quirks.parser_class("hybrid") is HybridParser
    assert quirks.parser_class("sqlglot") is SqlGlotParser


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

    facts = _copy_facts(node)

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
