"""DuckDB MERGE facts retain mutation details without changing parser dispatch."""

import json
from pathlib import Path

import pytest

from dblift.core.sql_parser.hybrid_parser import HybridParser
from dblift.core.sql_parser.sqlglot_parser import SqlGlotParser
from dblift.core.sql_parser.sqlglot_statement_facts import read_statement_facts
from dblift.db.plugins.duckdb.parser._script import scan_script
from dblift.db.plugins.duckdb.parser.duckdb_regex_parser import DuckDBRegexParser
from dblift.db.plugins.duckdb.quirks import DuckDBQuirks

CASES = json.loads(
    Path(__file__).with_name("duckdb_statement_facts_corpus.json").read_text(encoding="utf-8")
)["cases"]


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["id"])
def test_merge_facts_keep_targets_references_and_branch_effects(case):
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
