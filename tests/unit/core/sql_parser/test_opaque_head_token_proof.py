"""Opaque statement heads name an object only when its source tokens prove that name."""

from __future__ import annotations

import pytest
from sqlglot import Dialect

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
    # The shared reader must not merge the two source tokens into "ab". DuckDB's plugin
    # blanks the comment to a space before forwarding SQL, leaving "a b" as its input.
    suffix = " (id INT)" if verb == "CREATE" else ""
    facts = _facts(provider, grammar, f"{verb} TABLE a/*x*/b{suffix}", route)

    assert facts.opaque
    if provider == "duckdb" and route == "plugin":
        assert tuple((o.type.value, o.name, o.role) for o in facts.objects) == (
            ("TABLE", "a", "created" if verb == "CREATE" else "dropped"),
        )
    else:
        assert facts.objects == ()


ALTER_X = 'ALTER TABLE /* outer /* inner */ x */ "s"."orders" ADD COLUMN c INT'
ALTER_ONLY = 'ALTER TABLE ONLY /* a /* b */ c */ "s"."orders" ADD COLUMN x INT'
VICTIM = "/* L1 /* L2 /* L3 */ DROP TABLE victim; still L3 */ still L2 */\nSELECT 1"
T_KEEP = "/* a /* b */ DROP TABLE t_keep; */ CREATE TABLE t_after (x INT) /* tail */"


@pytest.mark.parametrize("route", ("common", "plugin"))
@pytest.mark.parametrize(
    "sql", (ALTER_X, ALTER_ONLY, VICTIM, T_KEEP), ids=("x", "only", "victim", "t-keep")
)
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
def test_nested_comment_ast_target_remains_intact(
    provider, grammar, sql, operation, objects, route
):
    # A blanket rejection of every commented head would erase these AST-proven identities.
    facts = _facts(provider, grammar, sql, route)

    assert facts.operation == operation
    assert not facts.opaque
    assert tuple((o.type.value, o.schema, o.name, o.role) for o in facts.objects) == objects


@pytest.mark.parametrize("route", ("common", "plugin"))
@pytest.mark.parametrize(
    "provider,grammar,sql,object_identity",
    (
        (
            "oracle",
            "oracle",
            'CREATE PUBLIC DATABASE LINK "DbLink" CONNECT TO u IDENTIFIED BY p',
            ("DATABASE_LINK", None, "DbLink", "created"),
        ),
        (
            "oracle",
            "oracle",
            "CREATE OR REPLACE PACKAGE pkg AS PROCEDURE a; END;",
            ("PACKAGE", None, "PKG", "created"),
        ),
        (
            "oracle",
            "oracle",
            'CREATE OR REPLACE PACKAGE "EXISTS" AS PROCEDURE a; END;',
            ("PACKAGE", None, "EXISTS", "created"),
        ),
        (
            "postgresql",
            "postgres",
            'CREATE EXTENSION IF NOT EXISTS "EXISTS"',
            ("EXTENSION", None, "EXISTS", "created"),
        ),
        (
            "sqlite",
            "sqlite",
            'CREATE TRIGGER main."tr" AFTER INSERT ON t BEGIN SELECT 1; END',
            ("TRIGGER", "main", "tr", "created"),
        ),
        (
            "sqlite",
            "sqlite",
            'CREATE TRIGGER "EXISTS" AFTER INSERT ON t BEGIN SELECT 1; END',
            ("TRIGGER", None, "EXISTS", "created"),
        ),
    ),
    ids=(
        "oracle-quoted",
        "oracle-semicolon-body",
        "oracle-quoted-keyword",
        "postgres-quoted-keyword",
        "sqlite-qualified",
        "sqlite-quoted-keyword",
    ),
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
        "mysql",
        "mysql",
        "CREATE TRIGGER `EXISTS` BEFORE INSERT ON t FOR EACH ROW SET NEW.x = 1",
        route,
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


@pytest.mark.parametrize("route", ("common", "plugin"))
@pytest.mark.parametrize(
    "provider,grammar,sql",
    (
        ("mysql", "mysql", "/* header */ REPLACE INTO t VALUES(1)"),
        ("sqlite", "sqlite", "/* header */ REPLACE INTO t(a) VALUES(1)"),
        ("mysql", "mysql", "-- header\nREPLACE INTO t VALUES(1)"),
        ("sqlite", "sqlite", "-- header\nREPLACE INTO t(a) VALUES(1)"),
    ),
)
def test_replace_after_a_comment_still_proves_its_target(provider, grammar, sql, route):
    facts = _facts(provider, grammar, sql, route)

    assert (facts.operation, facts.kind) == ("REPLACE", "DML")
    assert facts.opaque
    assert tuple((o.type.value, o.name, o.role) for o in facts.objects) == (
        ("TABLE", "t", "altered"),
    )


@pytest.mark.parametrize("route", ("common", "plugin"))
@pytest.mark.parametrize(
    "sql,target",
    (
        ("WITH c AS (SELECT 1) DELETE FROM t WHERE x=1 BOGUS (", "t"),
        (
            "WITH c AS (DELETE FROM shadow RETURNING *) " "DELETE FROM outer_t WHERE x=1 BOGUS (",
            "outer_t",
        ),
    ),
)
def test_opaque_cte_proves_only_its_top_level_delete_target(sql, target, route):
    facts = _facts(
        "postgresql",
        "postgres",
        sql,
        route,
    )

    assert (facts.operation, facts.kind) == ("DELETE", "DML")
    assert facts.opaque
    assert tuple((o.type.value, o.name, o.role) for o in facts.objects) == (
        ("TABLE", target, "altered"),
    )


@pytest.mark.parametrize("route", ("common", "plugin"))
@pytest.mark.parametrize(
    "sql",
    (
        "WITH c AS (DELETE FROM victim RETURNING *) SELECT 1 BOGUS (",
        "WITH c AS (SELECT 1); DELETE FROM victim WHERE x=1 BOGUS (",
    ),
)
def test_cte_inner_or_later_unit_does_not_prove_an_outer_target(sql, route):
    facts = _facts("postgresql", "postgres", sql, route)

    assert facts.opaque
    assert facts.objects == ()


@pytest.mark.parametrize("route", ("common", "plugin"))
@pytest.mark.parametrize("provider,grammar", DIALECTS)
@pytest.mark.parametrize(
    "sql",
    (
        "DROP TABLE a . b . c BOGUS (",
        "UPDATE a . b . c SET x=1 BOGUS (",
    ),
)
def test_third_name_part_cannot_publish_a_truncated_target(provider, grammar, sql, route):
    facts = _facts(provider, grammar, sql, route)

    assert facts.opaque
    assert facts.objects == ()
    assert facts.target is None


@pytest.mark.parametrize("route", ("common", "plugin"))
@pytest.mark.parametrize("provider,grammar", (DIALECTS[0], DIALECTS[3], DIALECTS[6]))
def test_quoted_dot_inside_one_name_remains_proven(provider, grammar, route):
    facts = _facts(provider, grammar, 'DROP TABLE "a.b" BOGUS (', route)

    assert facts.opaque
    assert tuple((o.type.value, o.name, o.role) for o in facts.objects) == (
        ("TABLE", "a.b", "dropped"),
    )


@pytest.mark.parametrize("route", ("common", "plugin"))
def test_oracle_index_does_not_claim_a_three_part_on_relation(route):
    facts = _facts("oracle", "oracle", "CREATE INDEX ix ON a . b . c (x) BOGUS (", route)

    assert facts.opaque
    assert tuple((o.type.value, o.name, o.role) for o in facts.objects) == (
        ("INDEX", "IX", "created"),
    )


@pytest.mark.parametrize("route", ("common", "plugin"))
@pytest.mark.parametrize("provider,grammar", DIALECTS)
@pytest.mark.parametrize(
    "sql",
    (
        "DROP TABLE a . b . c '",
        "DROP TABLE a . b /* gap */ . c '",
    ),
)
def test_broken_tail_cannot_hide_a_third_name_part(provider, grammar, sql, route):
    facts = _facts(provider, grammar, sql, route)

    assert facts.opaque
    assert facts.objects == ()


@pytest.mark.parametrize("route", ("common", "plugin"))
@pytest.mark.parametrize(
    "provider,grammar,schema,name",
    (
        ("postgresql", "postgres", "a", "b"),
        ("mysql", "mysql", "a", "b"),
        ("oracle", "oracle", "A", "B"),
        ("redshift", "redshift", "a", "b"),
        ("duckdb", "duckdb", "a", "b"),
        ("sqlite", "sqlite", "a", "b"),
    ),
)
@pytest.mark.parametrize("tail", ("/*unterminated", "'"))
def test_broken_tail_after_proven_name_keeps_the_head_identity(
    provider, grammar, schema, name, tail, route
):
    facts = _facts(provider, grammar, f"DROP TABLE a . b {tail}", route)

    assert facts.opaque
    assert tuple((o.type.value, o.schema, o.name, o.role) for o in facts.objects) == (
        ("TABLE", schema, name, "dropped"),
    )


@pytest.mark.parametrize("route", ("common", "plugin"))
@pytest.mark.parametrize(
    "sql,operation",
    (
        ("CREATE PROCEDURE a/*gap*/b() SELECT 1", "CREATE"),
        ("DROP EVENT IF EXISTS", "DROP"),
        ("CREATE TRIGGER a/*gap*/b BEFORE INSERT ON t FOR EACH ROW SET NEW.x=1", "CREATE"),
    ),
)
def test_mysql_program_head_does_not_publish_an_unproven_name(sql, operation, route):
    facts = _facts("mysql", "mysql", sql, route)

    assert (facts.operation, facts.kind) == (operation, "DDL")
    assert facts.opaque
    assert facts.objects == ()


@pytest.mark.parametrize("route", ("common", "plugin"))
def test_mysql_trigger_keeps_its_name_without_a_merged_on_relation(route):
    facts = _facts(
        "mysql",
        "mysql",
        "CREATE TRIGGER tr BEFORE INSERT ON a/*gap*/b FOR EACH ROW SET NEW.x=1",
        route,
    )

    assert facts.opaque
    assert tuple((o.type.value, o.name, o.role) for o in facts.objects) == (
        ("TRIGGER", "tr", "created"),
    )


@pytest.mark.parametrize("route", ("common", "plugin"))
@pytest.mark.parametrize(
    "provider,grammar",
    (DIALECTS[0], DIALECTS[1], DIALECTS[6]),
)
def test_opaque_cte_replace_keeps_its_outer_target(provider, grammar, route):
    facts = _facts(
        provider,
        grammar,
        "WITH c AS (SELECT 1) REPLACE INTO t SELECT * FROM c",
        route,
    )

    assert (facts.operation, facts.kind) == ("REPLACE", "DML")
    assert facts.opaque
    assert tuple((o.type.value, o.name, o.role) for o in facts.objects) == (
        ("TABLE", "t", "altered"),
    )


@pytest.mark.parametrize("route", ("common", "plugin"))
@pytest.mark.parametrize(
    "sql",
    (
        "WITH DELETE FROM victim AS (SELECT 1) SELECT 1 BOGUS (",
        "WITH c (x) DELETE FROM victim AS (SELECT 1) SELECT 1 BOGUS (",
        "WITH c AS DELETE FROM victim (SELECT 1) SELECT 1 BOGUS (",
    ),
)
def test_malformed_cte_header_does_not_publish_its_keyword_as_outer_write(sql, route):
    facts = _facts("postgresql", "postgres", sql, route)

    assert facts.opaque
    assert facts.objects == ()
    assert facts.target is None


@pytest.mark.parametrize("route", ("common", "plugin"))
def test_mysql_fulltext_index_name_is_not_merged_across_a_comment(route):
    facts = _facts("mysql", "mysql", "CREATE FULLTEXT INDEX a/*gap*/b ON t(c)", route)

    assert (facts.operation, facts.kind) == ("CREATE", "DDL")
    assert facts.opaque
    assert facts.objects == ()
    assert facts.indexed_table is None


@pytest.mark.parametrize("route", ("common", "plugin"))
def test_mysql_fulltext_index_retains_index_without_unproven_on_relation(route):
    facts = _facts("mysql", "mysql", "CREATE FULLTEXT INDEX ix ON a/*gap*/b(c)", route)

    assert facts.opaque
    assert tuple((o.type.value, o.name, o.role) for o in facts.objects) == (
        ("INDEX", "ix", "created"),
    )
    assert facts.indexed_table is None


@pytest.mark.parametrize("route", ("common", "plugin"))
def test_mysql_fulltext_index_keeps_proven_quoted_and_qualified_names(route):
    facts = _facts("mysql", "mysql", "CREATE FULLTEXT INDEX `i.x` ON `s`.`t`(c)", route)

    assert facts.opaque
    assert tuple((o.type.value, o.schema, o.name, o.role) for o in facts.objects) == (
        ("INDEX", None, "i.x", "created"),
        ("TABLE", "s", "t", "referenced"),
    )
    assert facts.indexed_table == "s.t"


@pytest.mark.parametrize("route", ("common", "plugin"))
def test_mysql_rename_rejects_a_merged_source_name(route):
    facts = _facts("mysql", "mysql", "RENAME TABLE a/*gap*/b TO c", route)

    assert (facts.operation, facts.kind) == ("RENAME", "DDL")
    assert facts.opaque
    assert facts.objects == ()


@pytest.mark.parametrize("route", ("common", "plugin"))
def test_mysql_rename_preserves_a_proven_qualified_source(route):
    facts = _facts("mysql", "mysql", "RENAME TABLE `s`.`a` TO `s`.`b`", route)

    assert not facts.opaque
    assert tuple((o.type.value, o.schema, o.name, o.role) for o in facts.objects) == (
        ("TABLE", "s", "a", "altered"),
    )


@pytest.mark.parametrize("route", ("common", "plugin"))
@pytest.mark.parametrize(
    "sql",
    (
        "RENAME TABLE a TO b, c/*gap*/d TO e",
        "RENAME TABLE a TO b, c TO d/*gap*/e",
    ),
)
def test_mysql_rename_rejects_any_later_unproven_name(sql, route):
    facts = _facts("mysql", "mysql", sql, route)

    assert (facts.operation, facts.kind) == ("RENAME", "DDL")
    assert facts.opaque
    assert facts.objects == ()


def test_mysql_rename_proof_tokenizes_a_long_command_a_bounded_number_of_times(monkeypatch):
    mysql = type(Dialect.get_or_raise("mysql"))
    tokenize = mysql.tokenize
    lengths = []

    def counted(self, sql, *args, **kwargs):
        lengths.append(len(sql))
        return tokenize(self, sql, *args, **kwargs)

    monkeypatch.setattr(mysql, "tokenize", counted)

    def measured(pair_count):
        lengths.clear()
        sql = "RENAME TABLE " + ", ".join(
            f"`s`.`old_{index}` TO `s`.`new_{index}`" for index in range(pair_count)
        )
        facts = _facts("mysql", "mysql", sql, "common")
        assert len(facts.objects) == pair_count
        return len(lengths), sum(lengths)

    short_calls, short_chars = measured(5)
    long_calls, long_chars = measured(20)

    assert long_calls <= short_calls + 4
    assert long_chars <= short_chars * 5


@pytest.mark.parametrize("route", ("common", "plugin"))
@pytest.mark.parametrize(
    "cte",
    (
        "WITH c(x, y) AS (SELECT 1, 2)",
        "WITH a AS (SELECT * FROM shadow), b AS (SELECT * FROM a)",
        "WITH RECURSIVE c AS (SELECT 1 UNION ALL SELECT x+1 FROM c)",
        "WITH c AS MATERIALIZED (SELECT 1)",
        "WITH c AS NOT MATERIALIZED (SELECT 1)",
        "WITH c AS (SELECT (SELECT 1) AS x)",
    ),
    ids=("columns", "multiple", "recursive", "materialized", "not-materialized", "nested-body"),
)
def test_supported_cte_headers_preserve_only_proven_outer_opaque_target(cte, route):
    sql = f"{cte} DELETE FROM live_t WHERE x=1 BOGUS ("
    facts = _facts("postgresql", "postgres", sql, route)

    assert (facts.operation, facts.kind) == ("DELETE", "DML")
    assert facts.opaque
    assert tuple((o.type.value, o.name, o.role) for o in facts.objects) == (
        ("TABLE", "live_t", "altered"),
    )
    assert facts.target == "live_t"
    assert facts.error is None


@pytest.mark.parametrize("route", ("common", "plugin"))
@pytest.mark.parametrize(
    "sql",
    (
        "WITH c() AS (SELECT 1) DELETE FROM victim WHERE x=1 BOGUS (",
        "WITH c(x,) AS (SELECT 1) DELETE FROM victim WHERE x=1 BOGUS (",
        "WITH c(x y) AS (SELECT 1) DELETE FROM victim WHERE x=1 BOGUS (",
        "WITH c AS NOT (SELECT 1) DELETE FROM victim WHERE x=1 BOGUS (",
    ),
    ids=("empty-columns", "trailing-comma", "missing-column-separator", "invalid-materialization"),
)
def test_malformed_cte_headers_do_not_attribute_outer_opaque_target(sql, route):
    facts = _facts("postgresql", "postgres", sql, route)

    assert facts.opaque
    assert facts.objects == ()
    assert facts.target is None
    assert facts.error is None


@pytest.mark.parametrize("route", ("common", "plugin"))
def test_mysql_rename_keyword_cannot_be_invented_as_source_table(route):
    facts = _facts("mysql", "mysql", "RENAME TABLE EXISTS TO b", route)

    assert (facts.operation, facts.kind) == ("RENAME", "DDL")
    assert facts.opaque
    assert facts.objects == ()
    assert facts.error is None


@pytest.mark.parametrize("route", ("common", "plugin"))
@pytest.mark.parametrize("header", ("/* header */ ", "-- header\n"))
@pytest.mark.parametrize("tail,expected", (("BOGUS (", "t"), ("'", None)))
def test_leading_comment_keeps_only_tokenizable_opaque_head(header, tail, expected, route):
    facts = _facts("postgresql", "postgres", f"{header}DROP TABLE t {tail}", route)

    assert (facts.operation, facts.kind) == ("DROP", "DDL")
    assert facts.opaque
    assert tuple(o.name for o in facts.objects) == ((expected,) if expected else ())
    assert facts.target is None
    assert (facts.error is None) == bool(expected)
