"""PostgreSQL materialized view facts retain the declared object kind."""

import pytest

from dblift.core.sql_model.base import SqlObjectType
from dblift.core.sql_parser.sqlglot_statement_facts import read_statement_facts
from dblift.core.sql_parser.statement_facts import NamedObject, StatementFacts
from dblift.db.plugins.postgresql.quirks import PostgresqlQuirks


@pytest.mark.parametrize(
    "identifier,name,schema",
    [
        ("public.mv", "mv", "public"),
        ("mv", "mv", None),
        ('"Sales"."Monthly View"', "Monthly View", "Sales"),
        ('"a""b"."m""v"', 'm"v', 'a"b'),
    ],
    ids=["qualified", "unqualified", "quoted", "escaped_quotes"],
)
@pytest.mark.parametrize("operation,role", [("CREATE", "created"), ("DROP", "dropped")])
def test_postgres_materialized_view_identity(operation, role, identifier, name, schema):
    sql = f"{operation} MATERIALIZED VIEW {identifier}"
    source = ()
    if operation == "CREATE":
        sql += " AS SELECT * FROM public.items"
        source = (NamedObject("items", SqlObjectType.TABLE, "referenced", "public"),)

    facts = read_statement_facts(sql, dialect="postgres")

    identity = NamedObject(name, SqlObjectType.MATERIALIZED_VIEW, role, schema)
    assert facts == StatementFacts(operation, "DDL", (identity,) + source)
    assert facts.affected_objects == (identity,)


@pytest.mark.parametrize("dialect", ["postgres", "sqlite", "duckdb"])
@pytest.mark.parametrize("operation,role", [("CREATE", "created"), ("DROP", "dropped")])
def test_ordinary_view_facts_preserve_the_view_kind(dialect, operation, role):
    sql = f'{operation} VIEW "Sales"."Monthly View"'
    source = ()
    if operation == "CREATE":
        sql += " AS SELECT * FROM public.items"
        source = (NamedObject("items", SqlObjectType.TABLE, "referenced", "public"),)

    assert read_statement_facts(sql, dialect=dialect) == StatementFacts(
        operation,
        "DDL",
        (NamedObject("Monthly View", SqlObjectType.VIEW, role, "Sales"),) + source,
    )


@pytest.mark.parametrize("dialect", ["sqlite", "duckdb"])
@pytest.mark.parametrize("operation,role", [("CREATE", "created"), ("DROP", "dropped")])
def test_postgres_materialized_view_mapping_preserves_other_dialects(dialect, operation, role):
    sql = f"{operation} MATERIALIZED VIEW public.mv"
    source = ()
    if operation == "CREATE":
        sql += " AS SELECT * FROM public.items"
        source = (NamedObject("items", SqlObjectType.TABLE, "referenced", "public"),)

    assert read_statement_facts(sql, dialect=dialect) == StatementFacts(
        operation,
        "DDL",
        (NamedObject("mv", SqlObjectType.VIEW, role, "public"),) + source,
    )


@pytest.mark.parametrize(
    "sql,operation",
    [
        ("REFRESH MATERIALIZED VIEW CONCURRENTLY public.mv", "REFRESH"),
        ("DO $$ BEGIN PERFORM 1; END $$", "DO"),
    ],
)
def test_postgres_refresh_and_procedural_block_remain_opaque(sql, operation):
    facts = read_statement_facts(sql, dialect="postgres")

    assert facts.operation == operation
    assert facts.kind == "UNKNOWN"
    assert facts.objects == facts.affected_objects == ()
    assert facts.opaque
    assert facts.diagnostic is not None
    assert facts.error is None


def test_materialized_view_facts_are_read_by_the_postgres_plugin():
    assert PostgresqlQuirks().supports_statement_facts
