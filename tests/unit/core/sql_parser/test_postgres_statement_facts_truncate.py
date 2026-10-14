"""Preparatory PostgreSQL TRUNCATE facts name only explicit table targets."""

import pytest

from dblift.core.sql_model.base import SqlObjectType
from dblift.core.sql_parser.statement_facts import (
    NamedObject,
    SqlglotStatementFactsReader,
    StatementFacts,
)
from dblift.db.plugins.postgresql.quirks import PostgresqlQuirks


@pytest.mark.parametrize(
    "sql,identities",
    [
        ("TRUNCATE items", (("items", None),)),
        ("TRUNCATE TABLE public.items", (("items", "public"),)),
        (
            "TRUNCATE TABLE ONLY public.items, public.logs RESTART IDENTITY CASCADE",
            (("items", "public"), ("logs", "public")),
        ),
        (
            "TRUNCATE public.items *, ONLY public.logs CONTINUE IDENTITY RESTRICT",
            (("items", "public"), ("logs", "public")),
        ),
        (
            'TRUNCATE TABLE "Sales"."Order Items", "a""b"."x.y"',
            (("Order Items", "Sales"), ("x.y", 'a"b')),
        ),
    ],
)
def test_postgres_truncate_facts_name_only_explicit_tables(sql, identities):
    facts = SqlglotStatementFactsReader("postgres").read(sql)

    assert facts == StatementFacts(
        "TRUNCATE",
        "DDL",
        tuple(
            NamedObject(name, SqlObjectType.TABLE, "altered", schema) for name, schema in identities
        ),
    )


@pytest.mark.parametrize(
    "sql",
    [
        "TRUNCATE TABLE (SELECT * FROM items)",
        "TRUNCATE TABLE public.items, read_csv('x')",
        "TRUNCATE TABLE public.items PARTITION (p)",
        "TRUNCATE TABLE IF EXISTS public.items",
        "TRUNCATE DATABASE inventory",
        "TRUNCATE TABLE public.items AS i",
        "TRUNCATE TABLE public.items ON CLUSTER c",
    ],
)
def test_postgres_unmodelled_truncate_targets_and_clauses_stay_opaque(sql):
    facts = SqlglotStatementFactsReader("postgres").read(sql)

    assert facts.operation == "TRUNCATE"
    assert facts.kind == "UNKNOWN"
    assert facts.objects == ()
    assert facts.opaque


@pytest.mark.parametrize("dialect", ["sqlite", "oracle", "mysql", "tsql"])
def test_postgres_truncate_facts_preserve_other_dialect_mappings(dialect):
    facts = SqlglotStatementFactsReader(dialect).read("TRUNCATE TABLE public.items")

    assert facts.operation == "TRUNCATE"
    assert facts.kind == "UNKNOWN"
    assert facts.objects == ()
    assert facts.opaque


def test_postgres_statement_facts_hook_remains_inactive():
    assert not PostgresqlQuirks().supports_statement_facts
