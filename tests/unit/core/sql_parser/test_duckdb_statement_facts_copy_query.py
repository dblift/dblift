"""DuckDB query exports report physical reads without database write effects."""

import duckdb
import pytest
from sqlglot import parse_one

from dblift.core.sql_model.base import SqlObjectType
from dblift.core.sql_parser.sqlglot_statement_facts import _copy_facts, read_statement_facts
from dblift.core.sql_parser.statement_facts import NamedObject, StatementFacts


@pytest.mark.parametrize(
    "query,sources",
    [
        ('SELECT id FROM "Sales"."Order Items"', (("Order Items", "Sales"),)),
        ("SELECT id FROM (SELECT id FROM items) AS nested", (("items", None),)),
        ("WITH selected AS (SELECT id FROM items) SELECT * FROM selected", (("items", None),)),
        (
            "SELECT id FROM items UNION ALL SELECT id FROM other_items",
            (("items", None), ("other_items", None)),
        ),
        (
            "WITH items AS (SELECT id FROM other_items) "
            "SELECT id FROM items UNION ALL SELECT id FROM main.items",
            (("other_items", None), ("items", "main")),
        ),
        (
            "SELECT id FROM items UNION ALL "
            "SELECT id FROM (WITH items AS (SELECT id FROM other_items) "
            "SELECT id FROM items) AS nested",
            (("items", None), ("other_items", None)),
        ),
        ("SELECT a.id FROM items a JOIN items b ON a.id=b.id", (("items", None),)),
        ("SELECT 1 AS id", ()),
    ],
    ids=[
        "qualified",
        "nested",
        "cte",
        "union",
        "qualified_cte_name",
        "nested_cte",
        "dedup",
        "constant",
    ],
)
@pytest.mark.parametrize("file_format", ["CSV", "PARQUET"])
def test_query_export_keeps_only_scoped_physical_sources(tmp_path, query, sources, file_format):
    path = tmp_path / f"export.{file_format.lower()}"
    sql = f"COPY ({query}) TO '{path}' (FORMAT {file_format})"
    with duckdb.connect() as connection:
        connection.execute('CREATE SCHEMA "Sales"')
        connection.execute('CREATE TABLE "Sales"."Order Items" AS SELECT 1 AS id')
        connection.execute("CREATE TABLE items AS SELECT 1 AS id")
        connection.execute("CREATE TABLE other_items AS SELECT 2 AS id")
        connection.execute(sql)
    assert path.is_file()

    facts = read_statement_facts(sql, dialect="duckdb")

    assert facts == StatementFacts(
        "COPY",
        "QUERY",
        tuple(
            NamedObject(name, SqlObjectType.TABLE, "referenced", schema) for name, schema in sources
        ),
    )
    assert facts.affected_objects == ()


@pytest.mark.parametrize(
    "sql",
    [
        "COPY (SELECT * FROM read_csv('items.csv')) TO 'out.csv'",
        "COPY (SELECT * FROM range(3)) TO 'out.csv'",
        "COPY (SELECT * FROM items, range(3)) TO 'out.csv'",
        "COPY (WITH source AS (SELECT * FROM read_csv('items.csv')) "
        "SELECT * FROM items, source) TO 'out.csv'",
        "COPY (SELECT * FROM items WHERE id IN (SELECT * FROM range(3))) TO 'out.csv'",
        "COPY (SELECT * FROM unnest([1, 2])) TO 'out.csv'",
        "COPY (SELECT * FROM items) TO ?",
        "COPY (SELECT * FROM items) TO ('out' || '.csv')",
        "COPY (SELECT * FROM items) TO 'out' || '.csv'",
        "COPY (SELECT * FROM items) TO 'a.csv', 'b.csv'",
        "COPY (SELECT * FROM items) 'out.csv'",
        "COPY (SELECT * FROM items) TO STDOUT",
        "COPY (SELECT * FROM items) FROM STDIN",
        "COPY (SELECT * FROM items) FROM 'in.csv'",
        "COPY (SELECT * FROM items) TO 'out.csv' (BATCH_SIZE (SELECT n FROM options))",
    ],
    ids=[
        "read_csv",
        "range",
        "mixed_function",
        "cte_function",
        "predicate_function",
        "unnest",
        "placeholder",
        "dynamic_path",
        "concatenated_path",
        "multiple_paths",
        "missing_direction",
        "stdout",
        "stdin",
        "query_import",
        "option_subquery",
    ],
)
def test_unsupported_query_exports_do_not_invent_objects(sql):
    facts = read_statement_facts(sql, dialect="duckdb")

    assert facts.operation == "COPY"
    assert facts.kind == "UNKNOWN"
    assert facts.objects == ()
    assert facts.target is None
    assert facts.target_sql is None
    assert facts.predicate is None
    assert facts.events is None
    assert facts.affected_columns == ()
    assert facts.opaque


@pytest.mark.parametrize("direction", [None, "TO", 0, 1, True])
def test_query_export_requires_explicit_false_direction(direction):
    sql = "COPY (SELECT * FROM items) TO 'out.csv'"
    node = parse_one(sql, read="duckdb")
    node.set("kind", direction)

    facts = _copy_facts(node, sql)

    assert facts.kind == "UNKNOWN"
    assert facts.objects == ()
    assert facts.target is None
    assert facts.target_sql is None
    assert facts.events is None
    assert facts.affected_columns == ()
    assert facts.opaque
