"""Contain PostgreSQL CTE facts whose scopes or effects are not represented."""

import pytest

from dblift.core.sql_model.base import SqlObjectType
from dblift.core.sql_parser.sqlglot_statement_facts import read_statement_facts
from dblift.core.sql_parser.statement_facts import NamedObject, StatementFacts


@pytest.mark.parametrize(
    "query",
    [
        "SELECT * FROM items UNION ALL SELECT * FROM "
        "(WITH items AS (SELECT * FROM other_items) SELECT * FROM items) nested",
        "WITH first AS (SELECT * FROM items), items AS (SELECT * FROM other_items) "
        "SELECT * FROM first JOIN items USING (id)",
        "WITH items AS (SELECT * FROM items) SELECT * FROM items",
        'WITH "Items" AS (SELECT * FROM other_items) '
        'SELECT * FROM items JOIN "Items" USING (id)',
        "WITH items AS (SELECT * FROM other_items) " 'SELECT * FROM "Items" JOIN items USING (id)',
        "WITH RECURSIVE items AS (SELECT * FROM seed UNION ALL "
        "SELECT seed.* FROM seed JOIN items USING (id)) SELECT * FROM items",
    ],
    ids=["nested", "sibling", "self", "quoted_alias", "quoted_source", "recursive"],
)
def test_unproven_cte_sources_are_explicitly_opaque(query):
    facts = read_statement_facts(f"CREATE VIEW reporting.mv AS {query}", dialect="postgres")

    assert facts.opaque
    assert facts.diagnostic and "CTE" in facts.diagnostic
    assert facts.error is None
    assert facts.operation == "CREATE"
    assert facts.kind == "DDL"
    assert facts.objects == (NamedObject("mv", SqlObjectType.VIEW, "created", "reporting"),)


@pytest.mark.parametrize(
    "body",
    [
        "DELETE FROM items RETURNING *",
        "UPDATE items SET id = 1 RETURNING *",
        "INSERT INTO items VALUES (1) RETURNING *",
    ],
    ids=["delete", "update", "insert"],
)
def test_mutating_cte_is_not_reported_as_a_read_only_query(body):
    facts = read_statement_facts(
        f"WITH changed AS ({body}) SELECT * FROM changed", dialect="postgres"
    )

    assert facts.opaque
    assert facts.diagnostic and "CTE" in facts.diagnostic
    assert facts.error is None
    assert facts.kind == "UNKNOWN"
    assert facts.objects == ()
    assert facts.events is None


def test_opaque_cte_preserves_only_the_reliable_outer_mutation_identity():
    facts = read_statement_facts(
        "WITH removed AS (DELETE FROM old_items RETURNING *) "
        "INSERT INTO reporting.items SELECT * FROM removed",
        dialect="postgres",
    )

    assert facts.opaque
    assert facts.operation == "INSERT"
    assert facts.kind == "DML"
    assert facts.objects == (NamedObject("items", SqlObjectType.TABLE, "altered", "reporting"),)
    assert facts.events is None


@pytest.mark.parametrize(
    "query",
    [
        "SELECT * FROM source_items",
        "WITH items AS (SELECT * FROM source_items) SELECT * FROM items",
        "WITH items AS (SELECT * FROM public.items) SELECT * FROM items",
        "WITH a AS (SELECT * FROM source_items), b AS (SELECT * FROM source_items) "
        "SELECT * FROM a JOIN b USING (id)",
    ],
    ids=["ordinary", "simple_cte", "qualified_source", "independent_ctes"],
)
def test_proven_read_only_sources_remain_precise(query):
    source = (
        NamedObject("items", SqlObjectType.TABLE, "referenced", "public")
        if "public.items" in query
        else NamedObject("source_items", SqlObjectType.TABLE, "referenced")
    )

    assert read_statement_facts(query, dialect="postgres") == StatementFacts(
        "SELECT", "QUERY", (source,)
    )


def test_opaque_cte_keeps_materialized_view_identity():
    facts = read_statement_facts(
        "CREATE MATERIALIZED VIEW reporting.mv AS "
        "WITH items AS (SELECT * FROM items) SELECT * FROM items",
        dialect="postgres",
    )

    assert facts.opaque
    assert facts.objects == (
        NamedObject("mv", SqlObjectType.MATERIALIZED_VIEW, "created", "reporting"),
    )


def test_opaque_cte_keeps_ctas_identity_with_declared_column_names():
    facts = read_statement_facts(
        "CREATE TABLE reporting.items_copy (id) AS "
        "WITH items AS (SELECT * FROM items) SELECT * FROM items",
        dialect="postgres",
    )

    assert facts.opaque
    assert facts.objects == (
        NamedObject("items_copy", SqlObjectType.TABLE, "created", "reporting"),
    )
