"""Opaque statement heads name an object only when its source tokens prove that name."""

from __future__ import annotations

import pytest

from dblift.core.sql_parser.sqlglot_statement_facts import read_statement_facts
from dblift.db.provider_registry import ProviderRegistry


DIALECTS = (
    ("postgresql", "postgres"),
    ("mysql", "mysql"),
    ("sqlserver", "tsql"),
    ("oracle", "oracle"),
    ("redshift", "redshift"),
    ("duckdb", "duckdb"),
    ("sqlite", "sqlite"),
)


def _facts(provider: str, grammar: str, sql: str, route: str):
    if route == "plugin":
        return ProviderRegistry.get_quirks(provider).statement_facts(sql)
    return read_statement_facts(sql, dialect=grammar)


@pytest.mark.parametrize("route", ("common", "plugin"))
@pytest.mark.parametrize("provider,grammar", DIALECTS)
def test_incomplete_drop_index_if_exists_does_not_name_exists(provider, grammar, route):
    # Changing the fallback to trust a keyword-sized regex match would reintroduce INDEX EXISTS.
    facts = _facts(provider, grammar, "DROP INDEX IF EXISTS", route)

    assert (facts.operation, facts.kind) == ("DROP", "DDL")
    assert facts.opaque
    assert facts.objects == ()


@pytest.mark.parametrize("route", ("common", "plugin"))
@pytest.mark.parametrize("verb", ("CREATE", "DROP"))
@pytest.mark.parametrize("provider,grammar", DIALECTS)
def test_comment_between_name_tokens_does_not_create_a_merged_name(provider, grammar, verb, route):
    # The blanked regex sees "ab", but the original SQL has two name tokens.
    suffix = " (id INT)" if verb == "CREATE" else ""
    facts = _facts(provider, grammar, f"{verb} TABLE a/*x*/b{suffix}", route)

    assert facts.opaque
    assert facts.objects == ()


ALTER_X = 'ALTER TABLE /* outer /* inner */ x */ "s"."orders" ADD COLUMN c INT'
ALTER_ONLY = 'ALTER TABLE ONLY /* a /* b */ c */ "s"."orders" ADD COLUMN x INT'
VICTIM = '/* L1 /* L2 /* L3 */ DROP TABLE victim; still L3 */ still L2 */\nSELECT 1'
T_KEEP = '/* a /* b */ DROP TABLE t_keep; */ CREATE TABLE t_after (x INT) /* tail */'


@pytest.mark.parametrize("route", ("common", "plugin"))
@pytest.mark.parametrize("sql", (ALTER_X, ALTER_ONLY, VICTIM, T_KEEP), ids=("x", "only", "victim", "t-keep"))
@pytest.mark.parametrize("provider,grammar", (DIALECTS[1], DIALECTS[3], DIALECTS[6]))
def test_ambiguous_opaque_head_does_not_invent_a_target(provider, grammar, sql, route):
    # These dialects do not nest block comments. Their malformed tails leave no proven
    # single-statement head; this does not claim the DROP text is hidden from the engine.
    facts = _facts(provider, grammar, sql, route)

    assert facts.opaque
    assert facts.objects == ()


@pytest.mark.parametrize("route", ("common", "plugin"))
@pytest.mark.parametrize(
    "sql,operation,objects",
    (
        (ALTER_X, "ALTER", (("TABLE", "s", "orders", "altered"),)),
        (ALTER_ONLY, "ALTER", (("TABLE", "s", "orders", "altered"),)),
        (VICTIM, "SELECT", ()),
        (T_KEEP, "CREATE", (("TABLE", None, "t_after", "created"),)),
    ),
    ids=("x", "only", "victim", "t-keep"),
)
@pytest.mark.parametrize("provider,grammar", (DIALECTS[0], DIALECTS[2], DIALECTS[4], DIALECTS[5]))
def test_nested_comment_ast_target_remains_intact(provider, grammar, sql, operation, objects, route):
    # A blanket rejection of every commented head would erase these AST-proven identities.
    facts = _facts(provider, grammar, sql, route)

    assert facts.operation == operation
    assert not facts.opaque
    assert tuple((o.type.value, o.schema, o.name, o.role) for o in facts.objects) == objects


@pytest.mark.parametrize("route", ("common", "plugin"))
@pytest.mark.parametrize(
    "provider,grammar,sql,object_identity",
    (
        ("oracle", "oracle", 'CREATE PUBLIC DATABASE LINK "DbLink" CONNECT TO u IDENTIFIED BY p',
         ("DATABASE_LINK", None, "DbLink", "created")),
        ("oracle", "oracle", "CREATE OR REPLACE PACKAGE pkg AS PROCEDURE a; END;",
         ("PACKAGE", None, "PKG", "created")),
        ("oracle", "oracle", 'CREATE OR REPLACE PACKAGE "EXISTS" AS PROCEDURE a; END;',
         ("PACKAGE", None, "EXISTS", "created")),
        ("postgresql", "postgres", 'CREATE EXTENSION IF NOT EXISTS "EXISTS"',
         ("EXTENSION", None, "EXISTS", "created")),
        ("sqlite", "sqlite", 'CREATE TRIGGER main."tr" AFTER INSERT ON t BEGIN SELECT 1; END',
         ("TRIGGER", "main", "tr", "created")),
        ("sqlite", "sqlite", 'CREATE TRIGGER "EXISTS" AFTER INSERT ON t BEGIN SELECT 1; END',
         ("TRIGGER", None, "EXISTS", "created")),
    ),
    ids=("oracle-quoted", "oracle-semicolon-body", "oracle-quoted-keyword",
         "postgres-quoted-keyword", "sqlite-qualified", "sqlite-quoted-keyword"),
)
def test_proven_opaque_head_still_names_its_object(provider, grammar, sql, object_identity, route):
    # Rejecting all opaque names would break documented fallback identities.
    facts = _facts(provider, grammar, sql, route)

    assert facts.opaque
    assert tuple((o.type.value, o.schema, o.name, o.role) for o in facts.objects) == (
        object_identity,
    )


@pytest.mark.parametrize("route", ("common", "plugin"))
def test_mysql_backtick_keyword_in_an_opaque_trigger_head_stays_a_name(route):
    facts = _facts(
        "mysql", "mysql",
        "CREATE TRIGGER `EXISTS` BEFORE INSERT ON t FOR EACH ROW SET NEW.x = 1", route,
    )

    assert facts.opaque
    assert tuple((o.type.value, o.schema, o.name, o.role) for o in facts.objects) == (
        ("TRIGGER", None, "EXISTS", "created"),
        ("TABLE", None, "t", "referenced"),
    )


@pytest.mark.parametrize("route", ("common", "plugin"))
def test_mysql_backtick_keyword_is_a_name_on_the_ast_path(route):
    facts = _facts("mysql", "mysql", "DROP INDEX `EXISTS` ON t", route)

    assert not facts.opaque
    assert tuple((o.type.value, o.schema, o.name, o.role) for o in facts.objects) == (
        ("INDEX", None, "EXISTS", "dropped"),
        ("TABLE", None, "t", "referenced"),
    )


@pytest.mark.parametrize("route", ("common", "plugin"))
def test_oracle_index_keeps_its_proven_name_without_an_unproven_on_relation(route):
    facts = _facts("oracle", "oracle", "CREATE INDEX ix ON a/*x*/b(c)", route)

    assert facts.opaque
    assert tuple((o.type.value, o.schema, o.name, o.role) for o in facts.objects) == (
        ("INDEX", None, "IX", "created"),
    )


@pytest.mark.parametrize("route", ("common", "plugin"))
def test_postgres_update_only_without_a_table_has_no_opaque_target(route):
    # ONLY is a modifier in this grammar; SET cannot stand in for the missing table.
    facts = _facts("postgresql", "postgres", "UPDATE ONLY SET c=1", route)

    assert (facts.operation, facts.kind) == ("UPDATE", "DML")
    assert facts.opaque
    assert facts.objects == ()
