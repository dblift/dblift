"""A statement cannot publish a relation identity after dropping a source name part."""

import pytest

from dblift.core.sql_parser.sqlglot_statement_facts import read_statement_facts
from dblift.db.provider_registry import ProviderRegistry

ACTIVE = (
    ("postgresql", "postgres"),
    ("redshift", "redshift"),
    ("mysql", "mysql"),
    ("mariadb", "mysql"),
    ("duckdb", "duckdb"),
    ("sqlite", "sqlite"),
    ("oracle", "oracle"),
)

STATEMENTS = (
    ("CREATE TABLE a.b.c.d (x INT)", "CREATE", "DDL"),
    ("DROP TABLE a.b.c.d", "DROP", "DDL"),
    ("ALTER TABLE a.b.c.d ADD COLUMN y INT", "ALTER", "DDL"),
    ("CREATE VIEW a.b.c.d AS SELECT 1", "CREATE", "DDL"),
    ("DROP VIEW a.b.c.d", "DROP", "DDL"),
    ("CREATE MATERIALIZED VIEW a.b.c.d AS SELECT x FROM t", "CREATE", "DDL"),
    ("DROP MATERIALIZED VIEW a.b.c.d", "DROP", "DDL"),
    ("UPDATE a.b.c.d SET x=1", "UPDATE", "DML"),
    ("SELECT * FROM a.b.c.d", "SELECT", "QUERY"),
    ("INSERT INTO a.b.c.d SELECT 1", "INSERT", "DML"),
    ("DELETE FROM a.b.c.d", "DELETE", "DML"),
    ("CREATE VIEW v AS SELECT * FROM a.b.c.d", "CREATE", "DDL"),
    ("CREATE TABLE t AS SELECT * FROM a.b.c.d", "CREATE", "DDL"),
)


def _facts(provider, grammar, route, sql):
    if route == "plugin":
        return ProviderRegistry.get_quirks(provider).statement_facts(sql)
    return read_statement_facts(sql, dialect=grammar)


@pytest.mark.parametrize("route", ("common", "plugin"))
@pytest.mark.parametrize("provider,grammar", ACTIVE)
@pytest.mark.parametrize("sql,operation,kind", STATEMENTS)
def test_four_part_relation_does_not_publish_an_incomplete_identity(
    provider, grammar, route, sql, operation, kind
):
    facts = _facts(provider, grammar, route, sql)

    assert (facts.operation, facts.kind) == (operation, kind)
    assert facts.objects == ()
    assert facts.target is None
    assert facts.target_sql is None
    assert facts.predicate is None
    assert facts.opaque
    assert facts.diagnostic
    assert facts.error is None


@pytest.mark.parametrize("route", ("common", "plugin"))
@pytest.mark.parametrize("provider,grammar", ACTIVE)
@pytest.mark.parametrize("sql,operation,kind", STATEMENTS)
def test_three_part_relation_keeps_its_full_identity(
    provider, grammar, route, sql, operation, kind
):
    sql = sql.replace("a.b.c.d", "a.b.c")
    facts = _facts(provider, grammar, route, sql)

    assert (facts.operation, facts.kind) == (operation, kind)
    assert not facts.opaque
    name, schema = ("C", "A.B") if provider == "oracle" else ("c", "a.b")
    assert any(obj.name == name and obj.schema == schema for obj in facts.objects)


@pytest.mark.parametrize("route", ("common", "plugin"))
@pytest.mark.parametrize("sql,operation,kind", STATEMENTS)
def test_tsql_four_part_relation_remains_opaque(sql, operation, kind, route):
    facts = _facts("sqlserver", "tsql", route, sql)

    assert (facts.operation, facts.kind) == (operation, kind)
    assert facts.objects == ()
    assert facts.opaque


@pytest.mark.parametrize("route", ("common", "plugin"))
@pytest.mark.parametrize("provider,grammar", ACTIVE)
@pytest.mark.parametrize(
    "sql,operation", (("\0CREATE TABLE b(y)", "CREATE"), ("\0DROP TABLE child", "DROP"))
)
def test_unproven_source_verb_does_not_publish_a_table(provider, grammar, sql, operation, route):
    if provider == "duckdb" and route == "plugin":
        pytest.skip("DuckDB plugin rejects a NUL at its splitter boundary")
    facts = _facts(provider, grammar, route, sql)

    assert (facts.operation, facts.kind) == (operation, "DDL")
    assert facts.objects == ()
    assert facts.opaque
    assert facts.diagnostic
    assert facts.error is None
