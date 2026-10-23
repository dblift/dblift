"""A statement led or fed by a CTE names its own target, its events and every table a CTE writes.

PostgreSQL accepts ``INSERT``, ``UPDATE`` and ``DELETE`` inside a top-level ``WITH``, so one
statement can change several tables. The expectations are what PostgreSQL 16.14 runs (row counts
checked on a throwaway server): the outer statement changes its own table, each writing CTE
changes the table it names, and a name inside a CTE body resolves to the CTE only when the lexical
scope says so. MySQL 8.4, SQLite 3.51 and DuckDB 1.5 accept a CTE before ``INSERT``, ``UPDATE`` or
``DELETE`` (MariaDB 11 only after ``INSERT INTO t``), and none of them accepts a CTE that writes.
"""

import pytest

from dblift.core.migration.scripting.undo_script_generator import UndoScriptGenerator
from dblift.core.migration.sql.script_analysis import CHANGES_ROWS, DESTROYS, analyse_script
from dblift.core.sql_model.base import SqlObjectType
from dblift.core.sql_parser.sqlglot_statement_facts import read_statement_facts
from dblift.core.sql_parser.statement_facts import DmlEffect, NamedObject
from dblift.db.dml_analysis import analyze_dml
from dblift.db.provider_registry import ProviderRegistry
from tests.unit._migration_factory import make_migration

T = SqlObjectType
PG = "postgres"  # lint: allow-dialect-string: test
DELETE_INTO_LOG = (
    "WITH d AS (DELETE FROM src WHERE id > 1 RETURNING *) INSERT INTO log SELECT * FROM d"
)
INSERT_WITH = "INSERT INTO t WITH x AS (SELECT a FROM r) SELECT a FROM x"
UPDATE_THEN_DELETE = (
    "WITH u AS (UPDATE a SET v = 1 RETURNING id) DELETE FROM b WHERE id IN (SELECT id FROM u)"
)


def _altered(*names):
    return tuple(NamedObject(n, T.TABLE, "altered") for n in names)


def _referenced(*names):
    return tuple(NamedObject(n, T.TABLE, "referenced") for n in names)


def test_a_delete_in_a_cte_and_the_insert_it_feeds_are_both_read():
    facts = read_statement_facts(DELETE_INTO_LOG, dialect=PG)

    assert (facts.operation, facts.kind, facts.diagnostic) == ("INSERT", "DML", None)
    assert facts.objects == _altered("log", "src")
    assert (facts.target, facts.target_sql, facts.predicate) == ("log", "log", None)
    assert facts.events == frozenset({"INSERT"})
    assert facts.cte_writes == (DmlEffect("DELETE", "src", "src", "id > 1", frozenset({"DELETE"})),)
    assert facts.affected_objects == _altered("log", "src")


def test_a_read_only_cte_inside_the_insert_contributes_its_sources():
    facts = read_statement_facts(INSERT_WITH, dialect=PG)

    assert (facts.operation, facts.kind, facts.diagnostic) == ("INSERT", "DML", None)
    assert facts.objects == _altered("t") + _referenced("r")
    assert (facts.target, facts.events, facts.cte_writes) == ("t", frozenset({"INSERT"}), ())


def test_an_update_in_a_cte_and_the_delete_it_feeds_are_both_read():
    facts = read_statement_facts(UPDATE_THEN_DELETE, dialect=PG)

    assert (facts.operation, facts.kind, facts.diagnostic) == ("DELETE", "DML", None)
    assert facts.objects == _altered("b", "a")
    assert (facts.target, facts.predicate) == ("b", "id IN (SELECT id FROM u)")
    assert facts.events == frozenset({"DELETE"})
    assert facts.cte_writes == (DmlEffect("UPDATE", "a", "a", None, frozenset({"UPDATE"}), ("v",)),)


def test_every_writing_cte_is_listed_in_order_and_chained_ctes_resolve():
    facts = read_statement_facts(
        "WITH d AS (INSERT INTO a VALUES (1) RETURNING id), "
        "e AS (UPDATE s.b SET z = 1 FROM q WHERE b.id = q.id RETURNING b.id), "
        "f AS (SELECT id FROM d UNION ALL SELECT id FROM e) "
        "INSERT INTO c SELECT id FROM f ON CONFLICT (id) DO UPDATE SET id = 0",
        dialect=PG,
    )

    assert facts.diagnostic is None
    assert facts.objects == (
        NamedObject("c", T.TABLE, "altered"),
        NamedObject("a", T.TABLE, "altered"),
        NamedObject("b", T.TABLE, "altered", "s"),
        NamedObject("q", T.TABLE, "referenced"),
    )
    assert facts.events == frozenset({"INSERT", "UPDATE"})
    assert [(w.operation, w.target, sorted(w.events)) for w in facts.cte_writes] == [
        ("INSERT", "a", ["INSERT"]),
        ("UPDATE", "s.b", ["UPDATE"]),
    ]


def test_a_select_led_by_a_writing_cte_is_data_changing():
    facts = read_statement_facts(
        "WITH d AS (DELETE FROM src RETURNING *) SELECT * FROM d", dialect=PG
    )

    assert (facts.operation, facts.kind, facts.diagnostic) == ("SELECT", "DML", None)
    assert facts.objects == _altered("src")
    assert (facts.target, facts.events) == (None, None)
    assert [(w.operation, w.target, w.predicate) for w in facts.cte_writes] == [
        ("DELETE", "src", None)
    ]


@pytest.mark.parametrize(
    "sql,objects",
    [
        # a recursive CTE sees itself and its siblings, in any order
        (
            "WITH RECURSIVE n(i) AS (SELECT 1 UNION ALL SELECT i + 1 FROM n WHERE i < 3) "
            "INSERT INTO t SELECT i FROM n",
            _altered("t"),
        ),
        (
            "WITH RECURSIVE a AS (SELECT * FROM b), b AS (SELECT 1 AS v) INSERT INTO t SELECT * FROM a",
            _altered("t"),
        ),
        # without RECURSIVE a body sees only the CTEs before it: ``bb`` and ``tt`` are real tables
        (
            "WITH a AS (SELECT * FROM bb), bb AS (SELECT 1 AS v) INSERT INTO t SELECT * FROM a",
            _altered("t") + _referenced("bb"),
        ),
        (
            "WITH tt AS (SELECT v FROM tt) INSERT INTO t SELECT * FROM tt",
            _altered("t") + _referenced("tt"),
        ),
        # an inner WITH shadows the outer name, and does not leak out of its subquery
        (
            "WITH tt AS (SELECT 1 AS v) INSERT INTO t SELECT * FROM "
            "(WITH tt AS (SELECT 2 AS v) SELECT * FROM tt) q",
            _altered("t"),
        ),
        (
            "WITH tt AS (SELECT 1 AS v) INSERT INTO t SELECT * FROM "
            "(WITH zz AS (SELECT 2 AS v) SELECT * FROM tt) q",
            _altered("t"),
        ),
        # unquoted names fold to lower case, a quoted one is exact
        (
            'WITH "X1" AS (SELECT 1 AS v) INSERT INTO t SELECT * FROM x1',
            _altered("t") + _referenced("x1"),
        ),
        (
            'WITH x1 AS (SELECT 1 AS v) INSERT INTO t SELECT * FROM "X1"',
            _altered("t") + _referenced("X1"),
        ),
        ("WITH X1 AS (SELECT 1 AS v) INSERT INTO t SELECT * FROM x1", _altered("t")),
        # a schema-qualified name is never a CTE, and a write target is never one
        (
            "WITH tt AS (SELECT 1 AS v) INSERT INTO t SELECT * FROM public.tt",
            (
                NamedObject("t", T.TABLE, "altered"),
                NamedObject("tt", T.TABLE, "referenced", "public"),
            ),
        ),
        ("WITH ww AS (SELECT 1 AS v) INSERT INTO ww SELECT v FROM ww", _altered("ww")),
        # MATERIALIZED hints and VALUES bodies are plain bodies
        (
            "WITH s AS MATERIALIZED (SELECT 1 AS i), v(i) AS (VALUES (1)) "
            "INSERT INTO t SELECT * FROM s, v",
            _altered("t"),
        ),
    ],
)
def test_a_name_resolves_to_a_cte_only_where_the_scope_says_so(sql, objects):
    facts = read_statement_facts(sql, dialect=PG)

    assert facts.diagnostic is None
    assert facts.objects == objects


@pytest.mark.parametrize(
    "sql,clause",
    [
        # PostgreSQL 16: "WITH clause containing a data-modifying statement must be at the top level"
        (
            "INSERT INTO t WITH d AS (DELETE FROM r RETURNING a) SELECT a FROM d",
            "data-modifying",
        ),
        (
            "SELECT * FROM (WITH d AS (DELETE FROM src RETURNING *) SELECT * FROM d) z",
            "data-modifying",
        ),
        # a MERGE in a CTE is PostgreSQL 17 grammar: not read
        (
            "WITH m AS (MERGE INTO t USING s ON t.id = s.id WHEN MATCHED THEN DELETE) SELECT 1",
            "MERGE",
        ),
    ],
)
def test_a_cte_body_that_cannot_be_read_keeps_a_diagnostic_naming_why(sql, clause):
    facts = read_statement_facts(sql, dialect=PG)

    assert facts.diagnostic is not None and clause in facts.diagnostic
    assert facts.cte_writes == ()


@pytest.mark.parametrize(
    "dialect", ["postgresql", "cockroachdb", "yugabytedb", "aurora-postgresql", "citus", "neon"]
)
def test_the_postgresql_family_reads_the_three_forms(dialect):
    quirks = ProviderRegistry.get_quirks(dialect)

    for sql, target in [(DELETE_INTO_LOG, "log"), (INSERT_WITH, "t"), (UPDATE_THEN_DELETE, "b")]:
        facts = quirks.statement_facts(sql)
        assert (facts.kind, facts.target, facts.diagnostic) == ("DML", target, None), sql


def test_redshift_reads_insert_into_with_but_rejects_a_writing_cte():
    # Redshift 1.0.485645 accepts INSERT INTO t WITH ... SELECT and rejects a CTE that writes
    # (docs/sql-parsing/redshift.md)
    facts = read_statement_facts(INSERT_WITH, dialect="redshift")
    assert facts.diagnostic is None
    assert facts.objects == _altered("t") + _referenced("r")
    assert facts.events == frozenset({"INSERT"})

    rejected = read_statement_facts(DELETE_INTO_LOG, dialect="redshift")
    assert rejected.diagnostic is not None and "data-modifying" in rejected.diagnostic
    assert rejected.cte_writes == ()


def test_redshift_leaves_a_scope_it_did_not_measure_unread():
    sql = "WITH tt AS (SELECT v FROM tt) INSERT INTO t SELECT * FROM tt"

    assert read_statement_facts(sql, dialect="redshift").diagnostic.startswith("redshift CTE")


def test_the_diagnostic_of_an_unreadable_cte_names_the_dialect_that_read_it():
    sql = "WITH m AS (MERGE INTO t USING s ON t.id = s.id WHEN MATCHED THEN DELETE) SELECT 1"

    assert read_statement_facts(sql, dialect=PG).diagnostic.startswith("postgres CTE")


# --- dialects whose CTE-led DML was already read: pinned with the engine evidence --------------


@pytest.mark.parametrize("dialect", ["sqlite", "duckdb", "mysql", "mariadb"])
@pytest.mark.parametrize(
    "sql,operation,events",
    [
        ("WITH x AS (SELECT a FROM r) INSERT INTO t SELECT a FROM x", "INSERT", {"INSERT"}),
        ("INSERT INTO t WITH x AS (SELECT a FROM r) SELECT a FROM x", "INSERT", {"INSERT"}),
        (
            "WITH x AS (SELECT a FROM r) DELETE FROM t WHERE a IN (SELECT a FROM x)",
            "DELETE",
            {"DELETE"},
        ),
        (
            "WITH x AS (SELECT a FROM r) UPDATE t SET a = 1 WHERE a IN (SELECT a FROM x)",
            "UPDATE",
            {"UPDATE"},
        ),
    ],
)
def test_engines_whose_ctes_only_read_name_target_events_and_sources(
    dialect, sql, operation, events
):
    facts = ProviderRegistry.get_quirks(dialect).statement_facts(sql)

    assert (facts.operation, facts.kind, facts.diagnostic) == (operation, "DML", None)
    assert facts.target == "t" and facts.events == events
    assert [(o.name, o.role) for o in facts.objects] == [("t", "altered"), ("r", "referenced")]
    assert facts.cte_writes == ()


@pytest.mark.parametrize("dialect", ["snowflake", "sqlserver"])
def test_snowflake_and_sql_server_read_the_cte_before_insert_update_delete(dialect):
    quirks = ProviderRegistry.get_quirks(dialect)
    insert = quirks.statement_facts("WITH x AS (SELECT a FROM r) INSERT INTO t SELECT a FROM x")
    delete = quirks.statement_facts(
        "WITH x AS (SELECT a FROM r) DELETE FROM t WHERE a IN (SELECT a FROM x)"
    )

    assert (insert.kind, insert.events, insert.diagnostic) == ("DML", {"INSERT"}, None)
    assert (delete.kind, delete.events, delete.diagnostic) == ("DML", {"DELETE"}, None)
    assert len(insert.affected_objects) == len(delete.affected_objects) == 1


def test_snowflake_reads_a_merge_behind_a_cte():
    facts = ProviderRegistry.get_quirks("snowflake").statement_facts(
        "WITH x AS (SELECT * FROM r) MERGE INTO t USING x ON t.id = x.id "
        "WHEN MATCHED THEN UPDATE SET a = 1 WHEN NOT MATCHED THEN INSERT (id) VALUES (x.id)"
    )

    assert (facts.operation, facts.kind, facts.diagnostic) == ("MERGE", "DML", None)
    assert [(o.name, o.role) for o in facts.objects] == [("T", "altered"), ("R", "referenced")]
    assert (facts.target, facts.events) == ("T", frozenset({"UPDATE", "INSERT"}))


@pytest.mark.parametrize(
    "sql",
    [
        # the target is the CTE: which table it names is not decided by the text
        "WITH t AS (SELECT * FROM r) MERGE INTO t USING s ON t.id = s.id WHEN MATCHED THEN DELETE",
        "WITH T AS (SELECT * FROM r) MERGE INTO t USING s ON t.id = s.id WHEN MATCHED THEN DELETE",
    ],
)
def test_snowflake_keeps_a_merge_unread_when_its_cte_scope_decides_the_target(sql):
    facts = ProviderRegistry.get_quirks("snowflake").statement_facts(sql)

    assert facts.diagnostic is not None and "CTE" in facts.diagnostic
    assert facts.affected_objects == ()


# --- consumers ---------------------------------------------------------------------------------


def test_dml_no_where_fires_on_a_writing_cte_without_where():
    analysis = analyse_script(
        "WITH d AS (DELETE FROM src RETURNING *) INSERT INTO log SELECT * FROM d", "postgresql"
    )

    assert [(c.level, c.code) for c in analysis.cautions] == [(DESTROYS, "dml-no-where")]
    assert "src" in analysis.cautions[0].reason and analysis.statements[0].full_table


def test_dml_no_where_is_quiet_on_a_writing_cte_with_where():
    analysis = analyse_script(DELETE_INTO_LOG, "postgresql")

    assert [(c.level, c.code) for c in analysis.cautions] == [(CHANGES_ROWS, None)]
    assert "src" in analysis.cautions[0].reason and not analysis.statements[0].full_table


def test_the_update_of_a_writing_cte_without_where_is_a_full_table_update():
    analysis = analyse_script(
        "WITH u AS (UPDATE a SET v = 1 RETURNING id) SELECT id FROM u", "postgresql"
    )

    assert [(c.level, c.code) for c in analysis.cautions] == [(DESTROYS, "dml-no-where")]


def test_the_lint_rule_reports_the_writing_cte_and_a_new_table_exempts_only_when_all_are_new():
    from dblift.core.migration.sql.lint_rules import find_issues

    script = "WITH d AS (DELETE FROM src RETURNING *) INSERT INTO log SELECT * FROM d"
    assert [f.code for f in find_issues(analyse_script(script, "postgresql"), "postgresql")] == [
        "dml-no-where"
    ]
    after_create = f"CREATE TABLE log (id int); {script}"
    assert "dml-no-where" in [
        f.code for f in find_issues(analyse_script(after_create, "postgresql"), "postgresql")
    ]


def test_the_data_mutation_carries_the_events_of_the_cte_writes():
    mutation = analyze_dml(DELETE_INTO_LOG, quirks=ProviderRegistry.get_quirks("postgresql"))

    assert (mutation.table, mutation.events) == ("log", {"INSERT"})
    assert [(w.table, w.events, w.updated_columns) for w in mutation.cte_writes] == [
        ("src", {"DELETE"}, [])
    ]


def test_undo_asks_for_review_of_every_statement_that_writes_through_a_cte():
    for sql in (
        DELETE_INTO_LOG,
        "WITH d AS (DELETE FROM src RETURNING *) SELECT * FROM d",
        UPDATE_THEN_DELETE,
    ):
        migration = make_migration(script_name="V1__x.sql", content=sql)
        undo = UndoScriptGenerator("postgresql")._generate_undo_statements(migration)

        assert [u.requires_manual_review for u in undo] == [True], sql


def test_select_into_behind_a_writing_cte_says_why_it_is_unread():
    facts = read_statement_facts(
        "WITH d AS (DELETE FROM src RETURNING *) SELECT * INTO newt FROM d", dialect=PG
    )

    assert facts.diagnostic == "postgres SELECT INTO behind a data-modifying CTE is not read"
