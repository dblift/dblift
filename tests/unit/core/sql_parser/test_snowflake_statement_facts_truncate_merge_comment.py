"""Snowflake TRUNCATE, MERGE and COMMENT ON read their plain forms and leave the rest unread."""

import pytest

from dblift.core.sql_parser.sqlglot_statement_facts import read_statement_facts


def _facts(sql):
    return read_statement_facts(sql, dialect="snowflake")


def _objects(facts):
    return [(o.name, o.type.value, o.role, o.schema) for o in facts.objects]


@pytest.mark.parametrize(
    ("sql", "objects"),
    [
        ("TRUNCATE t", [("T", "TABLE", "altered", None)]),
        ("TRUNCATE TABLE t", [("T", "TABLE", "altered", None)]),
        ("TRUNCATE TABLE IF EXISTS s.t", [("T", "TABLE", "altered", "S")]),
        ("truncate table db.s.t", [("T", "TABLE", "altered", "DB.S")]),
        ('TRUNCATE TABLE "a b"', [("a b", "TABLE", "altered", None)]),
        ('TRUNCATE TABLE "s"."t"', [("t", "TABLE", "altered", "s")]),
    ],
)
def test_a_plain_truncate_names_the_table_it_empties(sql, objects):
    facts = _facts(sql)

    assert (facts.operation, facts.kind) == ("TRUNCATE", "DDL")
    assert _objects(facts) == objects
    assert facts.diagnostic is None


@pytest.mark.parametrize(
    "sql",
    [
        "TRUNCATE TABLE IDENTIFIER($t)",
        "TRUNCATE TABLE IDENTIFIER('t')",
        "TRUNCATE TABLE $t",
        "TRUNCATE TABLE IF",
        "TRUNCATE TABLE t, u",
        "TRUNCATE TABLE t CASCADE",
        "TRUNCATE MATERIALIZED VIEW mv",
        "TRUNCATE TABLE é",
        "TRUNCATE TABLE t{c}",
    ],
)
def test_a_truncate_that_is_not_plain_stays_unread(sql):
    facts = _facts(sql)

    assert facts.operation == "TRUNCATE"
    assert facts.objects == ()
    assert facts.diagnostic


def test_merge_names_the_target_the_sources_and_the_events():
    facts = _facts(
        "MERGE INTO db.s.t AS x USING u ON x.id = u.id "
        "WHEN MATCHED THEN UPDATE SET a = u.a "
        "WHEN NOT MATCHED THEN INSERT (id) VALUES (u.id)"
    )

    assert (facts.operation, facts.kind) == ("MERGE", "DML")
    assert _objects(facts) == [
        ("T", "TABLE", "altered", "DB.S"),
        ("U", "TABLE", "referenced", None),
    ]
    assert facts.target == "DB.S.T"
    assert facts.events == frozenset({"UPDATE", "INSERT"})
    assert facts.affected_columns == ("a",)
    assert facts.diagnostic is None


def test_merge_with_a_delete_action_and_a_subquery_source():
    facts = _facts(
        'MERGE INTO "t" USING (SELECT * FROM u) y ON "t".id = y.id WHEN MATCHED THEN DELETE'
    )

    assert _objects(facts) == [("t", "TABLE", "altered", None), ("U", "TABLE", "referenced", None)]
    assert facts.events == frozenset({"DELETE"})


@pytest.mark.parametrize(
    "sql",
    [
        "MERGE INTO IDENTIFIER($t) USING s ON t.id = s.id WHEN MATCHED THEN DELETE",
        "MERGE INTO t USING IDENTIFIER($s) ON t.id = s.id WHEN MATCHED THEN DELETE",
        "MERGE INTO t USING s ON t.id = s.id",
        "MERGE INTO t{c} USING s ON t.id = s.id WHEN MATCHED THEN DELETE",
        "MERGE INTO if USING s ON t.id = s.id WHEN MATCHED THEN DELETE",
        "WITH c AS (SELECT 1 AS id) MERGE INTO t USING c ON t.id = c.id WHEN MATCHED THEN DELETE",
    ],
)
def test_a_merge_with_an_unread_name_or_no_action_stays_unread(sql):
    facts = _facts(sql)

    assert facts.operation == "MERGE"
    assert facts.objects == ()
    assert facts.target is None
    assert facts.diagnostic


@pytest.mark.parametrize(
    ("sql", "objects"),
    [
        ("COMMENT ON TABLE t IS 'x'", [("T", "TABLE", "altered", None)]),
        ("COMMENT IF EXISTS ON TABLE s.t IS 'x'", [("T", "TABLE", "altered", "S")]),
        ("COMMENT ON VIEW v IS 'x'", [("V", "VIEW", "altered", None)]),
        ("COMMENT ON MATERIALIZED VIEW m IS 'x'", [("M", "MATERIALIZED_VIEW", "altered", None)]),
        ("COMMENT ON SEQUENCE q IS 'x'", [("Q", "SEQUENCE", "altered", None)]),
        ("COMMENT ON COLUMN s.t.c IS 'x'", [("T", "TABLE", "altered", "S")]),
        ("COMMENT ON COLUMN db.s.t.c IS 'x'", [("T", "TABLE", "altered", "DB.S")]),
        ("COMMENT ON TABLE \"a b\" IS 'x'", [("a b", "TABLE", "altered", None)]),
    ],
)
def test_a_plain_comment_on_names_the_object_it_changes(sql, objects):
    facts = _facts(sql)

    assert (facts.operation, facts.kind) == ("COMMENT", "DDL")
    assert _objects(facts) == objects
    assert facts.diagnostic is None


@pytest.mark.parametrize(
    "sql",
    [
        "COMMENT ON TABLE IDENTIFIER($t) IS 'x'",
        "COMMENT ON TABLE IDENTIFIER('t') IS 'x'",
        "COMMENT ON COLUMN t.c{c} IS 'x'",
        "COMMENT ON COLUMN a.b.c.d.e IS 'x'",
        "COMMENT ON FUNCTION f(int) IS 'x'",
        "COMMENT ON DATABASE d IS 'x'",
        "COMMENT ON SCHEMA s IS 'x'",
        "COMMENT ON TABLE if IS 'x'",
        "COMMENT ON COLUMN c IS 'x'",
    ],
)
def test_a_comment_on_an_unread_name_or_kind_stays_unread(sql):
    facts = _facts(sql)

    assert facts.operation == "COMMENT"
    assert facts.objects == ()
    assert facts.diagnostic
