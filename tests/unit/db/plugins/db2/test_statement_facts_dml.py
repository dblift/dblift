"""Db2 statement facts: DML targets, predicate, events and assigned columns."""

import pytest

from dblift.db.plugins.db2.parser.statement_facts import NAME_NOT_READ, Db2StatementFactsReader

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
            "app.orders AS o",
            {"UPDATE"},
            "o.id = 1 WITH RS",
            ("name", "qty"),
        ),
        (
            "UPDATE app.orders o SET o.name = 'b' WHERE o.id = 1",
            "UPDATE",
            "APP.ORDERS",
            "app.orders o",
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
            "UPDATE t SET v = (SELECT 1 FROM x WHERE a = 1) WHERE id = 2",
            "UPDATE",
            "T",
            "t",
            {"UPDATE"},
            "id = 2",
            ("v",),
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
            "app.orders AS o",
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
            "app.target t",
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
    assert (facts.operation, facts.kind, facts.opaque) == (operation, "DML", False)
    assert (facts.target, facts.target_sql, facts.predicate) == (target, target_sql, predicate)
    assert facts.events == frozenset(events)
    assert facts.affected_columns == columns
    assert [(o.type.value, o.role) for o in facts.objects] == [("TABLE", "altered")]


@pytest.mark.parametrize(
    ("sql", "operation"),
    [
        ("DELETE FROM (SELECT * FROM t) WHERE 1 = 1", "DELETE"),
        ("UPDATE (SELECT * FROM t) SET a = 1", "UPDATE"),
        ("UPDATE t WHERE id = 1", "UPDATE"),
        ("INSERT INTO FINAL TABLE (x) VALUES (1)", "INSERT"),
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
    assert (facts.target_sql, facts.predicate) == ("t o", "o.x = 1")


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
