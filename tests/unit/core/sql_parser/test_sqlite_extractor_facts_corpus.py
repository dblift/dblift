"""Reviewed SQLite facts for every distinct input in migrated extractor tests."""

import json
from pathlib import Path

import pytest

from dblift.core.sql_parser.lexical_engine import LexicalEngine
from dblift.core.sql_parser.statement_facts import SqlglotStatementFactsReader
from dblift.db.plugins.sqlite.parser.lexical_spec import SQLITE_SPEC
from tests.support.facts_parser import facts_parser

CASES = json.loads(
    Path(__file__).with_name("sqlite_extractor_facts_corpus.json").read_text(encoding="utf-8")
)["cases"]


@pytest.mark.unit
@pytest.mark.parametrize("case", CASES, ids=[str(i) for i in range(len(CASES))])
def test_removed_extractor_inputs_have_reviewed_facts(case):
    assert case["source_tests"]
    assert case["reviewed_difference"] is None or case["reviewed_difference"]
    parser = facts_parser("sqlite")
    if "parse_expected" in case:
        result = parser.parse_sql(case["sql"])
        expected = case["parse_expected"]
        assert result.success is expected["success"]
        assert [obj.name for stmt in result.statements for obj in stmt.objects] == expected[
            "objects"
        ]
        if "error_contains" in expected:
            assert any(expected["error_contains"] in error for error in result.errors)
            return
    reader = SqlglotStatementFactsReader("sqlite", SQLITE_SPEC)
    observed = []
    for sql in LexicalEngine(SQLITE_SPEC).split_for_analysis(case["sql"]):
        facts = reader.read(sql)
        observed.append(
            {
                "operation": facts.operation,
                "kind": facts.kind,
                "objects": [
                    {
                        "type": obj.type.value,
                        "name": obj.name,
                        "role": obj.role,
                        "schema": obj.schema,
                    }
                    for obj in facts.objects
                ],
                "declared_columns": list(facts.declared_columns),
                "indexed_table": facts.indexed_table,
                "indexed_columns": (
                    list(facts.indexed_columns) if facts.indexed_columns is not None else None
                ),
                "declared_constraints": [
                    {
                        "kind": constraint.kind,
                        "columns": list(constraint.columns),
                        "name": constraint.name,
                        "referenced_table": constraint.referenced_table,
                        "referenced_columns": list(constraint.referenced_columns),
                    }
                    for constraint in facts.declared_constraints
                ],
                "affected_columns": list(facts.affected_columns),
                "target": facts.target,
                "predicate": facts.predicate,
                "diagnostic": facts.diagnostic,
            }
        )
    assert observed == case["facts"]
    if "projected_objects" in case:
        objects = parser.extract_objects(case["sql"])
        assert [
            {"type": obj.object_type.value, "name": obj.name, "schema": obj.schema}
            for obj in objects
        ] == case["projected_objects"]
