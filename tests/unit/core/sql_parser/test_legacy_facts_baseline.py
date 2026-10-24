"""Legacy parser observations for future per-statement comparison."""

import json
from pathlib import Path

import pytest

from dblift.core.sql_parser.lexical_engine import LexicalEngine
from dblift.core.sql_parser.statement_facts import SqlglotStatementFactsReader
from dblift.db.plugins.sqlite.parser.lexical_spec import SQLITE_SPEC
from tests.support.facts_parser import facts_parser

CORPUS = Path(__file__).with_name("legacy_facts_baseline.json")
CORPUS_DATA = json.loads(CORPUS.read_text(encoding="utf-8"))
CASES = CORPUS_DATA["cases"]
ACCEPTED_DIFFERENCES = {"sqlite": 3, "duckdb": 3, "mysql": 2}
REQUIRED_DIALECTS = {"postgresql", "oracle", "sqlserver", "mysql", "db2", "sqlite", "duckdb"}


def _object(ob):
    return {"type": ob.object_type.value, "name": ob.name, "schema": ob.schema}


def _observe(dialect, script):
    result = facts_parser(dialect).parse_sql(script)
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
    if case["dialect"] == "postgresql":
        assert observed["success"] == case["legacy_observed"]["success"]
        assert observed["errors"] == case["legacy_observed"]["errors"]
        assert len(observed["statements"]) == 5
        for index, (old, new) in enumerate(
            zip(case["legacy_observed"]["statements"], observed["statements"])
        ):
            assert new["sql"] == old["sql"]
            assert new["objects"] == new["affected_objects"]
            if index in (0, 1, 4):
                assert new["affected_objects"] == old["affected_objects"]
            else:
                assert old["objects"] == old["affected_objects"] == []
                assert new["affected_objects"] == [
                    {"type": "TABLE", "name": "child", "schema": None}
                ]
        assert observed["statements"][0]["type"] == "DDL"
        assert case["legacy_observed"]["statements"][0]["type"] == "UNKNOWN"
        assert len(case["accepted_differences"]) == 3
        return
    if case["dialect"] == "db2":
        # Db2 reads statement facts: no invented SYSIBM schema, and DML names its target.
        assert observed["success"] == case["legacy_observed"]["success"]
        assert observed["errors"] == case["legacy_observed"]["errors"]
        assert len(observed["statements"]) == 5
        for index, (old, new) in enumerate(
            zip(case["legacy_observed"]["statements"], observed["statements"])
        ):
            assert (new["sql"], new["type"]) == (old["sql"], old["type"])
            if index in (2, 3):
                assert old["objects"] == old["affected_objects"] == []
                expected = [{"type": "TABLE", "name": "CHILD", "schema": None}]
            else:
                expected = [{**ob, "schema": None} for ob in old["objects"]]
                assert all(ob["schema"] == "SYSIBM" for ob in old["objects"])
            assert new["objects"] == new["affected_objects"] == expected
        return
    if case["dialect"] == "oracle":
        # Oracle reads statement facts: every statement has its kind and the object it acts on,
        # named as Oracle stores it (unquoted names upper-cased); the legacy path read none.
        assert observed["success"] == case["legacy_observed"]["success"]
        assert observed["errors"] == case["legacy_observed"]["errors"]
        expected = [
            ("DDL", "TABLE", "CHILD"),
            ("DDL", "INDEX", "IX_CHILD_PARENT"),
            ("DML", "TABLE", "CHILD"),
            ("DML", "TABLE", "CHILD"),
            ("DDL", "TABLE", "CHILD"),
        ]
        legacy = case["legacy_observed"]["statements"]
        assert len(observed["statements"]) == len(legacy) == len(expected)
        for old, new, (kind, object_type, name) in zip(legacy, observed["statements"], expected):
            assert old["type"] == "UNKNOWN"
            assert old["objects"] == old["affected_objects"] == []
            assert new["sql"] == old["sql"]
            assert new["type"] == kind
            assert new["objects"] == new["affected_objects"]
            assert new["objects"] == [{"type": object_type, "name": name, "schema": None}]
        return
    if case["dialect"] == "sqlserver":
        # The facts path keeps the five executed statements and names proven DML targets.
        # It does not invent dbo for unqualified names.
        assert observed["success"] == case["legacy_observed"]["success"]
        assert observed["errors"] == case["legacy_observed"]["errors"]
        assert len(observed["statements"]) == 5
        for index, (old, new) in enumerate(
            zip(case["legacy_observed"]["statements"], observed["statements"])
        ):
            assert (new["sql"], new["type"]) == (old["sql"], old["type"])
            if index in (2, 3):
                assert old["objects"] == old["affected_objects"] == []
                expected = [{"type": "TABLE", "name": "child", "schema": None}]
            else:
                assert all(obj["schema"] == "dbo" for obj in old["objects"])
                expected = [{**obj, "schema": None} for obj in old["objects"]]
            assert new["objects"] == new["affected_objects"] == expected
        return
    if case["dialect"] in ACCEPTED_DIFFERENCES:
        assert observed["success"] == case["legacy_observed"]["success"]
        assert observed["errors"] == case["legacy_observed"]["errors"]
        assert len(observed["statements"]) == 5
        for index in (0, 1, 4):
            assert observed["statements"][index] == case["legacy_observed"]["statements"][index]
        for index in (2, 3):
            old = case["legacy_observed"]["statements"][index]
            new = observed["statements"][index]
            assert old["objects"] == old["affected_objects"] == []
            assert (
                new["objects"]
                == new["affected_objects"]
                == [{"type": "TABLE", "name": "child", "schema": None}]
            )
        assert len(case["accepted_differences"]) == ACCEPTED_DIFFERENCES[case["dialect"]]
        return
    assert observed == case["legacy_observed"]


@pytest.mark.unit
def test_sqlite_statement_facts_snapshot():
    case = next(case for case in CASES if case["dialect"] == "sqlite")
    observed = []
    reader = SqlglotStatementFactsReader("sqlite", SQLITE_SPEC)
    for sql in LexicalEngine(SQLITE_SPEC).split_for_analysis(case["script"]):
        facts = reader.read(sql)
        observed.append(
            {
                "sql": sql,
                "operation": facts.operation,
                "kind": facts.kind,
                "objects": [
                    {
                        "type": obj.type.value,
                        "name": obj.name,
                        "schema": obj.schema,
                        "role": obj.role,
                    }
                    for obj in facts.objects
                ],
                "target": facts.target,
                "predicate": facts.predicate,
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
                "declared_column_comments": facts.declared_column_comments,
                "affected_columns": list(facts.affected_columns),
                "events": sorted(facts.events) if facts.events else None,
                "diagnostic": facts.diagnostic,
            }
        )
    assert observed == case["facts_observed"]


@pytest.mark.unit
def test_cte_delete_names_affected_target():
    script = CORPUS_DATA["known_gap_inputs"]["cte_delete_target"]
    observed = _observe("postgresql", script)
    assert {ob["name"] for ob in observed["statements"][0]["affected_objects"]} == {"dst"}
