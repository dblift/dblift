"""DuckDB macros are opaque until statement facts can represent their identity."""

import pytest

from dblift.core.sql_model.base import SqlObjectType
from dblift.core.sql_parser.sqlglot_statement_facts import read_statement_facts
from dblift.core.sql_parser.statement_facts import NamedObject, StatementFacts


@pytest.mark.parametrize(
    "sql,operation",
    [
        ("CREATE MACRO increment(x) AS x + 1", "CREATE"),
        ("CREATE OR REPLACE MACRO increment(x) AS x + 1", "CREATE"),
        ("CREATE TEMP MACRO increment(x) AS x + 1", "CREATE"),
        ("CREATE MACRO IF NOT EXISTS increment(x) AS x + 1", "CREATE"),
        ('CREATE MACRO "main"."Increment"(x) AS x + 1', "CREATE"),
        ("CREATE MACRO rows() AS TABLE SELECT * FROM source", "CREATE"),
        ("CREATE FUNCTION increment(x) AS x + 1", "CREATE"),
        ("CREATE FUNCTION rows() AS TABLE SELECT * FROM source", "CREATE"),
        ("DROP MACRO increment", "DROP"),
        ("DROP MACRO IF EXISTS increment", "DROP"),
        ('DROP MACRO "main"."Increment"', "DROP"),
        ("DROP FUNCTION increment", "DROP"),
    ],
)
def test_macro_facts_do_not_claim_object_identity_or_body_references(sql, operation):
    facts = read_statement_facts(sql, dialect="duckdb")

    assert facts.opaque
    assert facts.operation == operation
    assert facts.kind == "DDL"
    assert facts.diagnostic and "macro" in facts.diagnostic.lower()
    assert facts.error is None
    assert facts.objects == ()
    assert facts.affected_objects == ()
    assert facts.target is None
    assert facts.target_sql is None
    assert facts.events is None
    assert facts.declared_columns == ()
    assert facts.declared_constraints == ()
    assert facts.affected_columns == ()


def test_drop_table_macro_keeps_existing_opaque_fallback():
    facts = read_statement_facts("DROP MACRO TABLE rows", dialect="duckdb")

    assert facts.opaque
    assert facts.operation == "DROP"
    assert facts.kind == "DDL"
    assert facts.objects == ()
    assert facts.error is None


@pytest.mark.parametrize("operation", ["CREATE", "DROP"])
def test_other_duckdb_ddl_keeps_table_identity(operation):
    sql = "CREATE TABLE items (id INT)" if operation == "CREATE" else "DROP TABLE items"
    facts = read_statement_facts(sql, dialect="duckdb")

    assert facts == StatementFacts(
        operation,
        "DDL",
        (
            NamedObject(
                "items", SqlObjectType.TABLE, "created" if operation == "CREATE" else "dropped"
            ),
        ),
        declared_columns=("id",) if operation == "CREATE" else (),
    )


@pytest.mark.parametrize(
    "sql,operation,role",
    [
        (
            "CREATE FUNCTION increment(x INT) RETURNS INT AS 'SELECT x + 1' LANGUAGE SQL",
            "CREATE",
            "created",
        ),
        ("DROP FUNCTION increment", "DROP", "dropped"),
    ],
)
def test_postgres_function_facts_keep_function_identity(sql, operation, role):
    facts = read_statement_facts(sql, dialect="postgres")

    assert facts == StatementFacts(
        operation, "DDL", (NamedObject("increment", SqlObjectType.FUNCTION, role),)
    )
