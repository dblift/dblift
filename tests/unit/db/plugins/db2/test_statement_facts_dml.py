"""Db2 statement facts: DML targets, predicate, events and assigned columns."""

import pytest

from dblift.db.plugins.db2.parser.statement_facts import (
    DATA_CHANGE_QUERY,
    NAME_NOT_READ,
    Db2StatementFactsReader,
)

READ = Db2StatementFactsReader(None).read


@pytest.mark.parametrize(
    ("sql", "operation", "target", "target_sql", "events", "predicate", "columns"),
    [
        (
            "INSERT INTO app.orders (id, name) VALUES (1, 'a')",
            "INSERT",
            "APP.ORDERS",
            "app.orders",
            {"INSERT"},
            None,
            (),
        ),
        (
            'INSERT INTO "App"."Orders X" (id) VALUES (1)',
            "INSERT",
            "App.Orders X",
            '"App"."Orders X"',
            {"INSERT"},
            None,
            (),
        ),
        (
            "insert into app.orders select * from app.orders2",
            "INSERT",
            "APP.ORDERS",
            "app.orders",
            {"INSERT"},
            None,
            (),
        ),
        (
            "INSERT INTO app.orders (id) VALUES (1) WITH UR",
            "INSERT",
            "APP.ORDERS",
            "app.orders",
            {"INSERT"},
            None,
            (),
        ),
        ("INSERT INTO t(a) VALUES (1)", "INSERT", "T", "t", {"INSERT"}, None, ()),
        (
            "UPDATE app.orders SET name = 'b' WHERE id = 1",
            "UPDATE",
            "APP.ORDERS",
            "app.orders",
            {"UPDATE"},
            "id = 1",
            ("name",),
        ),
        (
            "UPDATE app.orders AS o SET name = 'b', qty = 2 WHERE o.id = 1 WITH RS",
            "UPDATE",
            "APP.ORDERS",
            "app.orders",
            {"UPDATE"},
            "o.id = 1 WITH RS",
            ("name", "qty"),
        ),
        (
            "UPDATE app.orders o SET o.name = 'b' WHERE o.id = 1",
            "UPDATE",
            "APP.ORDERS",
            "app.orders",
            {"UPDATE"},
            "o.id = 1",
            ("name",),
        ),
        (
            "UPDATE t SET (a, b) = (1, 2) WHERE id = 2",
            "UPDATE",
            "T",
            "t",
            {"UPDATE"},
            "id = 2",
            ("a", "b"),
        ),
        (
            "UPDATE app.orders SET v = 1 WHERE CURRENT OF c1",
            "UPDATE",
            "APP.ORDERS",
            "app.orders",
            {"UPDATE"},
            "CURRENT OF c1",
            ("v",),
        ),
        (
            "UPDATE t SET note = 'WHERE x' WHERE id = 1; -- c",
            "UPDATE",
            "T",
            "t",
            {"UPDATE"},
            "id = 1",
            ("note",),
        ),
        ('UPDATE t SET "Qty" = 1', "UPDATE", "T", "t", {"UPDATE"}, None, ("Qty",)),
        (
            "DELETE FROM app.orders WHERE id = 1",
            "DELETE",
            "APP.ORDERS",
            "app.orders",
            {"DELETE"},
            "id = 1",
            (),
        ),
        ("DELETE FROM app.orders", "DELETE", "APP.ORDERS", "app.orders", {"DELETE"}, None, ()),
        (
            "DELETE FROM app.orders AS o WHERE o.id = 1",
            "DELETE",
            "APP.ORDERS",
            "app.orders",
            {"DELETE"},
            "o.id = 1",
            (),
        ),
        (
            'DELETE FROM "App"."Orders X" WHERE a = 1',
            "DELETE",
            "App.Orders X",
            '"App"."Orders X"',
            {"DELETE"},
            "a = 1",
            (),
        ),
        (
            "MERGE INTO app.target t USING app.source s ON t.id = s.id WHEN MATCHED THEN UPDATE SET t.v = s.v WHEN NOT MATCHED THEN INSERT (id, v) VALUES (s.id, s.v)",
            "MERGE",
            "APP.TARGET",
            "app.target",
            {"UPDATE", "INSERT"},
            None,
            ("v",),
        ),
        (
            "MERGE INTO t USING s ON t.id = s.id WHEN MATCHED THEN DELETE",
            "MERGE",
            "T",
            "t",
            {"DELETE"},
            None,
            (),
        ),
    ],
)
def test_dml_targets(sql, operation, target, target_sql, events, predicate, columns):
    facts = READ(sql)
    source_unenumerated = (
        operation == "MERGE" or sql == "insert into app.orders select * from app.orders2"
    )
    assert (facts.operation, facts.kind, facts.opaque) == (
        operation,
        "DML",
        source_unenumerated,
    )
    if source_unenumerated:
        assert facts.diagnostic == (f"db2 {operation}: source table references are not enumerated")
    else:
        assert facts.diagnostic is None
    assert (facts.target, facts.target_sql, facts.predicate) == (target, target_sql, predicate)
    assert facts.events == frozenset(events)
    assert facts.affected_columns == columns
    assert [(o.type.value, o.role) for o in facts.objects] == [("TABLE", "altered")]


@pytest.mark.parametrize(
    ("sql", "operation"),
    [
        (
            "UPDATE app.target SET v = 1 WHERE EXISTS (SELECT 1 FROM app.source)",
            "UPDATE",
        ),
        (
            "DELETE FROM app.target WHERE EXISTS (SELECT 1 FROM app.source)",
            "DELETE",
        ),
        (
            "INSERT INTO app.target (id) SELECT id FROM app.source",
            "INSERT",
        ),
        (
            "MERGE INTO app.target t USING app.source s ON t.id=s.id "
            "WHEN MATCHED THEN UPDATE SET v=s.v",
            "MERGE",
        ),
    ],
)
def test_dml_with_unenumerated_source_tables_is_opaque(sql, operation):
    facts = READ(sql)

    assert facts.operation == operation
    assert facts.target == "APP.TARGET"
    assert [(obj.schema, obj.name, obj.role) for obj in facts.objects] == [
        ("APP", "TARGET", "altered")
    ]
    assert facts.opaque
    assert facts.diagnostic is not None
    assert "source" in facts.diagnostic.lower() or "reference" in facts.diagnostic.lower()


def test_update_with_scalar_subquery_source_is_opaque():
    facts = READ("UPDATE t SET v = (SELECT 1 FROM x WHERE a = 1) WHERE id = 2")

    assert facts.target == "T"
    assert facts.opaque
    assert facts.diagnostic == "db2 UPDATE: source table references are not enumerated"


def test_update_from_source_is_opaque_when_target_is_named():
    facts = READ("UPDATE t SET v = s.v FROM s WHERE t.id = s.id")

    assert facts.target == "T"
    assert facts.opaque
    assert facts.diagnostic == "db2 UPDATE: source table references are not enumerated"


def test_delete_with_constant_scalar_subquery_remains_readable():
    facts = READ("DELETE FROM t WHERE id = (SELECT 1)")

    assert (facts.target, facts.opaque, facts.diagnostic) == ("T", False, None)


def test_simple_dml_without_source_tables_remains_readable():
    facts = READ("UPDATE app.target SET v = 1 WHERE id = 1")

    assert (facts.target, facts.opaque, facts.diagnostic) == ("APP.TARGET", False, None)


@pytest.mark.parametrize(
    "sql",
    [
        "UPDATE app.target SET note = 'SELECT 1 FROM app.source' WHERE id = 1",
        "UPDATE app.target SET v = 1 /* SELECT 1 FROM app.source */ WHERE id = 1",
    ],
)
def test_select_text_in_literal_or_comment_does_not_hide_unread_references(sql):
    facts = READ(sql)

    assert (facts.target, facts.opaque, facts.diagnostic) == ("APP.TARGET", False, None)


@pytest.mark.parametrize(
    ("sql", "operation"),
    [
        ("DELETE FROM (SELECT * FROM t) WHERE 1 = 1", "DELETE"),
        ("UPDATE (SELECT * FROM t) SET a = 1", "UPDATE"),
        ("UPDATE t WHERE id = 1", "UPDATE"),
        ("DELETE FROM t USING s WHERE t.id = s.id", "DELETE"),
        ("DELETE FROM t WHERE", "DELETE"),
    ],
)
def test_a_dml_target_that_is_not_a_plain_name_is_opaque(sql, operation):
    facts = READ(sql)
    assert (facts.objects, facts.target, facts.diagnostic) == (
        (),
        None,
        NAME_NOT_READ.format(operation=operation, type="TABLE"),
    )


@pytest.mark.parametrize(
    ("sql", "columns"),
    [
        ("UPDATE t SET a = CASE WHEN b = 1 THEN 2 ELSE 3 END, c = 4", ("a", "c")),
        ("UPDATE t SET a = CASE b WHEN 1 THEN 2 END, c = 4 WHERE id = 1", ("a", "c")),
        (
            "MERGE INTO t USING s ON t.id = s.id WHEN MATCHED THEN UPDATE SET a = CASE WHEN s.b = 1 THEN 2 ELSE 3 END, c = 4 WHEN NOT MATCHED THEN INSERT (id) VALUES (s.id)",
            ("a", "c"),
        ),
        (
            "MERGE INTO t USING s ON t.id = s.id WHEN MATCHED AND s.k = 1 THEN UPDATE SET a = 1 WHEN MATCHED THEN UPDATE SET b = 2",
            ("a", "b"),
        ),
    ],
)
def test_a_case_expression_does_not_end_the_set_list(sql, columns):
    assert READ(sql).affected_columns == columns


def test_a_leading_byte_order_mark_does_not_shift_the_source_text():
    facts = READ("\ufeffDELETE FROM t o WHERE o.x = 1")
    assert (facts.target_sql, facts.predicate) == ("t", "o.x = 1")


@pytest.mark.parametrize(
    ("sql", "operation"),
    [
        ("UPDATE t AS SET a = 1", "UPDATE"),
        ("INSERT INTO t x VALUES (1)", "INSERT"),
        ("INSERT INTO t AS x VALUES (1)", "INSERT"),
    ],
)
def test_dml_target_followers_the_head_does_not_allow_are_opaque(sql, operation):
    facts = READ(sql)
    assert (facts.objects, facts.target) == ((), None)
    assert facts.diagnostic == NAME_NOT_READ.format(operation=operation, type="TABLE")


def test_an_empty_delimited_identifier_is_not_a_dml_target():
    facts = READ('INSERT INTO "" VALUES (1)')
    assert (facts.objects, facts.target) == ((), None)
    assert facts.diagnostic == NAME_NOT_READ.format(operation="INSERT", type="TABLE")


@pytest.mark.parametrize(
    "sql",
    [
        "INSERT INTO FINAL TABLE (x) VALUES (1)",
        "INSERT INTO t (a) SELECT * FROM FINAL TABLE (INSERT INTO u VALUES (1))",
        "INSERT INTO t SELECT * FROM NEW TABLE (UPDATE u SET a = 1)",
        "INSERT INTO t SELECT * FROM OLD TABLE (DELETE FROM u)",
        "UPDATE t SET a = (SELECT a FROM FINAL TABLE (INSERT INTO u VALUES (1)))",
        "DELETE FROM t WHERE a IN (SELECT a FROM OLD TABLE (DELETE FROM u))",
        "MERGE INTO t USING (SELECT * FROM NEW TABLE (UPDATE u SET a = 1)) s ON t.a = s.a WHEN MATCHED THEN DELETE",
    ],
)
def test_a_dml_holding_a_data_change_table_is_opaque(sql):
    facts = READ(sql)
    assert (facts.objects, facts.target, facts.diagnostic) == ((), None, DATA_CHANGE_QUERY)


def test_insert_select_names_its_target_but_marks_source_unenumerated():
    facts = READ("INSERT INTO t SELECT * FROM u")
    assert facts.target == "T"
    assert facts.opaque
    assert facts.diagnostic == "db2 INSERT: source table references are not enumerated"


def test_insert_select_without_from_remains_readable():
    facts = READ("INSERT INTO t SELECT 1, 'a' || chr(10) || '-- b'")

    assert (facts.target, facts.opaque, facts.diagnostic) == ("T", False, None)


def test_supported_data_change_cte_records_the_inner_update():
    facts = READ(
        "WITH changed_rows AS ("
        "SELECT id FROM FINAL TABLE ("
        "UPDATE app.orders SET status = 'done' WHERE id = 1"
        ")) SELECT id FROM changed_rows"
    )

    assert facts.operation == "SELECT"
    assert facts.kind == "DML"
    assert not facts.opaque
    assert [(obj.schema, obj.name, obj.role) for obj in facts.objects] == [
        ("APP", "ORDERS", "altered")
    ]
    assert len(facts.cte_writes) == 1
    assert (facts.cte_writes[0].operation, facts.cte_writes[0].target) == (
        "UPDATE",
        "APP.ORDERS",
    )


def test_data_change_cte_accepts_matching_declared_column():
    facts = READ(
        "WITH changed_rows (id) AS ("
        "SELECT id FROM FINAL TABLE (UPDATE app.orders SET status = 'done' WHERE id = 1)"
        ") SELECT id FROM changed_rows"
    )

    assert not facts.opaque
    assert [(write.operation, write.target) for write in facts.cte_writes] == [
        ("UPDATE", "APP.ORDERS")
    ]


@pytest.mark.parametrize(
    "sql",
    [
        "WITH AS (SELECT id FROM FINAL TABLE (UPDATE t SET id = 1)) SELECT id FROM c",
        "WITH c (id, status) AS (SELECT id FROM FINAL TABLE (UPDATE t SET id = 1)) SELECT id FROM c",
        "WITH c (SELECT) AS (SELECT id FROM FINAL TABLE (UPDATE t SET id = 1)) SELECT id FROM c",
        "WITH c (id) AS (SELECT status FROM FINAL TABLE (UPDATE t SET id = 1)) SELECT status FROM c",
        "WITH c AS SELECT id FROM FINAL TABLE (UPDATE t SET id = 1) SELECT id FROM c",
        "WITH c AS () SELECT id FROM FINAL TABLE (UPDATE t SET id = 1)",
        "WITH c AS (SELECT * FROM FINAL TABLE (UPDATE t SET id = 1)) SELECT id FROM c",
        "WITH c AS (SELECT id FROM FINAL TABLE (UPDATE t SET id = 1) WHERE id = 1) SELECT id FROM c",
        "WITH c AS (SELECT id FROM FINAL TABLE (INSERT INTO t VALUES (1))) SELECT id FROM c",
        "WITH c AS (SELECT id FROM FINAL TABLE (UPDATE t SET id = 1 FROM u)) SELECT id FROM c",
        "WITH c AS (SELECT id FROM FINAL TABLE (UPDATE t SET id = 1 JOIN u ON t.id = u.id)) SELECT id FROM c",
        "WITH c AS (SELECT id FROM FINAL TABLE (UPDATE SET id = 1)) SELECT id FROM c",
        "WITH c AS (SELECT id FROM FINAL TABLE (UPDATE t SET id = 1)) SELECT id FROM other_c",
        "WITH c AS (SELECT id FROM FINAL TABLE (UPDATE t SET id = 1)) SELECT status FROM c",
    ],
)
def test_unsupported_data_change_cte_stays_opaque(sql):
    facts = READ(sql)

    assert facts.opaque
    assert facts.cte_writes == ()
    assert facts.diagnostic == DATA_CHANGE_QUERY
