"""A DuckDB ``CREATE MACRO`` (or its ``CREATE FUNCTION`` alias) names the function it creates."""

import pytest

from dblift.core.migration.sql.script_analysis import analyse_script
from dblift.core.sql_model.base import SqlObjectType
from dblift.db.plugins.duckdb.quirks import DuckDBQuirks


def _created(sql):
    facts = DuckDBQuirks().statement_facts(sql)
    return facts, [(o.name, o.type, o.role, o.schema) for o in facts.objects]


@pytest.mark.parametrize(
    "sql, name, schema",
    [
        ("CREATE MACRO add1(a) AS a + 1", "add1", None),
        ("CREATE OR REPLACE MACRO add1(a, b := 2) AS a + b", "add1", None),
        ("CREATE MACRO IF NOT EXISTS add1(a) AS a + 1", "add1", None),
        ("CREATE TEMP MACRO add1(a) AS a + 1", "add1", None),
        ("CREATE TEMPORARY MACRO add1(a) AS a + 1", "add1", None),
        ("CREATE MACRO main.add1(a) AS a + 1", "add1", "main"),
        ("CREATE MACRO memory.main.add1(a) AS a + 1", "add1", "main"),
        ('CREATE MACRO "My Mac"."Add;1"(a) AS a + 1', "Add;1", "My Mac"),
        ("CREATE MACRO tbl(x) AS TABLE SELECT x", "tbl", None),
        ("CREATE FUNCTION add1(a) AS a + 1", "add1", None),
        ("/* c */ CREATE MACRO add1(a) AS a + 1", "add1", None),
    ],
)
def test_a_created_macro_is_a_created_function_object(sql, name, schema):
    facts, objects = _created(sql)

    assert (facts.operation, facts.kind) == ("CREATE", "DDL")
    assert objects == [(name, SqlObjectType.FUNCTION, "created", schema)]
    assert not facts.opaque


def test_the_script_analysis_reads_the_macro_as_an_object():
    analysis = analyse_script("CREATE MACRO add1(a) AS a + 1;", "duckdb")

    assert [(o.type, o.name) for o in analysis.statements[0].objects] == [("FUNCTION", "add1")]


@pytest.mark.parametrize("sql", ["DROP MACRO add1", "CREATE MACRO"])
def test_statements_without_a_readable_macro_head_stay_as_they_were(sql):
    facts, objects = _created(sql)

    assert objects == []
