"""Execution-time object tracking reads statement facts and nothing else.

Every plugin that runs SQL migrations has a statement-facts reader, so the objects a statement
touches are never re-derived from its text. A quirks overlay without a reader tracks nothing.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from dblift.core.migration.sql.sql_analyzer import SqlAnalyzer
from dblift.core.migration.sql.sql_execution_service import SqlExecutionService
from dblift.core.sql_model.base import SqlObject, SqlObjectType
from dblift.db.base_quirks import BaseQuirks
from dblift.db.dml_analysis import DmlMutation
from dblift.db.provider_registry import ProviderRegistry

pytestmark = pytest.mark.unit

CORPUS = Path(__file__).parents[3] / "support" / "facts_corpus"
FAMILY_DIALECTS = {
    "postgresql": "postgresql",
    "mysql": "mysql",
    "oracle": "oracle",
    "sqlserver": "sqlserver",
    "sqlite": "sqlite",
    "duckdb": "duckdb",
    "redshift": "redshift",
    "snowflake": "snowflake",
    "db2": "db2",
}


def _tracked(dialect: str, sql: str, quirks, analyzer=None):
    provider = MagicMock(spec=["execute_query", "execute_statement"])
    provider.execute_statement.return_value = 1
    provider.execute_query.return_value = []
    journal = MagicMock()
    service = SqlExecutionService(
        provider,
        analyzer if analyzer is not None else SqlAnalyzer(dialect),
        logger=MagicMock(),
        journal=journal,
        schema="app",
        quirks=quirks,
    )
    service.execute_statement(sql, 0)
    return [c.args[2] for c in journal.record_object_changes.call_args_list]


def test_dml_target_is_not_guessed_from_text_when_analysis_names_none():
    analyzer = MagicMock()
    analyzer.get_statement_type.return_value = "DML"
    quirks = BaseQuirks()
    quirks.analyze_dml = lambda statement: DmlMutation(None, {"INSERT"}, [])

    assert _tracked("postgresql", "INSERT INTO customers (id) VALUES (1)", quirks, analyzer) == []


def test_dml_target_named_by_analysis_is_tracked():
    analyzer = MagicMock()
    analyzer.get_statement_type.return_value = "DML"
    quirks = BaseQuirks()
    quirks.analyze_dml = lambda statement: DmlMutation("s.customers", {"INSERT"}, [])

    (objects,) = _tracked("postgresql", "INSERT INTO customers (id) VALUES (1)", quirks, analyzer)
    assert [(o["object_name"], o["schema"]) for o in objects] == [("customers", "s")]


def test_ddl_without_a_parser_factory_tracks_nothing():
    analyzer = MagicMock()
    analyzer.get_statement_type.return_value = "DDL"
    del analyzer.parser_factory
    # the analyzer's own extraction is a text model too; a raise would be swallowed, so offer an object
    analyzer.extract_objects.return_value = [
        SqlObject(name="t", object_type=SqlObjectType.TABLE, schema="app")
    ]

    assert _tracked("postgresql", "CREATE TABLE t (id INT)", BaseQuirks(), analyzer) == []


@pytest.mark.parametrize("family", sorted(FAMILY_DIALECTS))
def test_tracking_equals_the_deduplicated_facts_for_every_corpus_statement(family, monkeypatch):
    dialect = FAMILY_DIALECTS[family]
    quirks = ProviderRegistry.get_quirks(dialect)
    analyzer = SqlAnalyzer(dialect)

    def forbidden(*args, **kwargs):
        raise AssertionError("text extraction reached")

    monkeypatch.setattr(analyzer, "_extract_objects_regex", forbidden)
    monkeypatch.setattr(type(quirks), "analyze_dml", forbidden)
    monkeypatch.setattr(analyzer.parser_factory, "extract_objects", forbidden)

    checked = 0
    for line in (CORPUS / f"{family}.jsonl").read_text(encoding="utf-8").splitlines():
        sql = json.loads(line)["sql"]
        tracked = _tracked(dialect, sql, quirks, analyzer)
        facts = quirks.statement_facts(sql)
        seen = {}
        for obj in facts.affected_objects:
            sql_object = obj.as_sql_object("app", quirks.dialect_name)
            key = (
                sql_object.name.lower(),
                sql_object.object_type.value.upper(),
                (sql_object.schema or "").lower(),
            )
            seen.setdefault(key, sql_object.name)
        if tracked:
            assert len(tracked) == 1
            assert [
                (o["object_name"].lower(), o["object_type"].upper(), (o["schema"] or "").lower())
                for o in tracked[0]
            ] == list(seen)
            checked += 1
    assert checked
