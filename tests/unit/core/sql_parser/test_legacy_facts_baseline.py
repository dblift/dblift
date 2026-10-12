"""Legacy parser observations for future per-statement comparison."""

import json
from pathlib import Path

import pytest

from dblift.core.sql_parser import SqlParserFactory

CORPUS = Path(__file__).with_name("legacy_facts_baseline.json")
CORPUS_DATA = json.loads(CORPUS.read_text(encoding="utf-8"))
CASES = CORPUS_DATA["cases"]
REQUIRED_DIALECTS = {"postgresql", "oracle", "sqlserver", "mysql", "db2", "sqlite", "duckdb"}


def _object(ob):
    return {"type": ob.object_type.value, "name": ob.name, "schema": ob.schema}


def _observe(dialect, script):
    result = SqlParserFactory(dialect, parser_type="hybrid").parse_sql(script)
    return {
        "success": result.success,
        "errors": result.errors,
        "statements": [
            {
                "sql": statement.sql_text,
                "type": statement.statement_type.value,
                "objects": [_object(ob) for ob in statement.objects],
                "affected_objects": [_object(ob) for ob in statement.affected_objects],
            }
            for statement in result.statements
        ],
    }


@pytest.mark.unit
def test_legacy_facts_corpus_shape():
    dialects = [case["dialect"] for case in CASES]
    assert set(dialects) == REQUIRED_DIALECTS
    assert len(dialects) == len(set(dialects))
    assert all(case["script"].strip() for case in CASES)
    assert all(len(case["legacy_observed"]["statements"]) == 5 for case in CASES)
    assert CORPUS_DATA["known_gap_inputs"]["cte_delete_target"].strip()


@pytest.mark.unit
@pytest.mark.parametrize("case", CASES, ids=[case["dialect"] for case in CASES])
def test_legacy_facts_corpus(case):
    observed = _observe(case["dialect"], case["script"])
    assert observed == case["legacy_observed"]


@pytest.mark.unit
@pytest.mark.xfail(strict=True, reason="Known legacy target loss: dblift/dblift#560")
def test_cte_delete_names_affected_target():
    script = CORPUS_DATA["known_gap_inputs"]["cte_delete_target"]
    observed = _observe("postgresql", script)
    assert {ob["name"] for ob in observed["statements"][0]["affected_objects"]} == {"dst"}
