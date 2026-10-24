"""Db2 statement facts: DDL families and name reading."""

import pytest

from dblift.db.plugins.db2.parser.statement_facts import (
    COLUMNS_UNAVAILABLE,
    NAME_NOT_READ,
    NOT_CLASSIFIED,
    UNTERMINATED_IDENTIFIER,
    Db2StatementFactsReader,
    fold_name,
)

READ = Db2StatementFactsReader(None).read


@pytest.mark.parametrize(
    ("sql", "operation", "kind", "objects"),
    [
        (
            "CREATE TABLE app.orders (id INT NOT NULL PRIMARY KEY) IN userspace1",
            "CREATE",
            "DDL",
            [("ORDERS", "TABLE", "created", "APP")],
        ),
        ("CREATE TABLE t(id INT)", "CREATE", "DDL", [("T", "TABLE", "created", None)]),
        (
            'CREATE TABLE "App"."Mixed Case" (id INT)',
            "CREATE",
            "DDL",
            [("Mixed Case", "TABLE", "created", "App")],
        ),
        ('CREATE TABLE "a""b".t (id INT)', "CREATE", "DDL", [("T", "TABLE", "created", 'a"b')]),
        (
            "create table lower_t (id integer)",
            "CREATE",
            "DDL",
            [("LOWER_T", "TABLE", "created", None)],
        ),
        ("CREATE TABLE MY@TBL (id INT)", "CREATE", "DDL", [("MY@TBL", "TABLE", "created", None)]),
        (
            "CREATE TABLE app.lk LIKE app.orders",
            "CREATE",
            "DDL",
            [("LK", "TABLE", "created", "APP")],
        ),
        (
            "CREATE GLOBAL TEMPORARY TABLE app.gt (id INT)",
            "CREATE",
            "DDL",
            [("GT", "TABLE", "created", "APP")],
        ),
        (
            "DECLARE GLOBAL TEMPORARY TABLE session.tmp1 (id INT) ON COMMIT PRESERVE ROWS",
            "DECLARE",
            "DDL",
            [("TMP1", "TABLE", "created", "SESSION")],
        ),
        (
            "CREATE OR REPLACE VIEW app.v2 AS SELECT id FROM app.orders",
            "CREATE",
            "DDL",
            [("V2", "VIEW", "created", "APP")],
        ),
        (
            "CREATE UNIQUE INDEX app.ix2 ON app.orders (id) INCLUDE (name)",
            "CREATE",
            "DDL",
            [("IX2", "INDEX", "created", "APP"), ("ORDERS", "TABLE", "referenced", "APP")],
        ),
        (
            "CREATE OR REPLACE ALIAS app.al2 FOR app.orders",
            "CREATE",
            "DDL",
            [("AL2", "SYNONYM", "created", "APP")],
        ),
        (
            "CREATE SEQUENCE app.seq1 AS BIGINT START WITH 1",
            "CREATE",
            "DDL",
            [("SEQ1", "SEQUENCE", "created", "APP")],
        ),
        (
            "CREATE SCHEMA app AUTHORIZATION dbadm",
            "CREATE",
            "DDL",
            [("APP", "SCHEMA", "created", None)],
        ),
        (
            "CREATE OR REPLACE PROCEDURE app.p2 (IN a INT, OUT b INT) LANGUAGE SQL BEGIN SET b = a; END",
            "CREATE",
            "DDL",
            [("P2", "PROCEDURE", "created", "APP")],
        ),
        (
            "CREATE FUNCTION app.f1 (a INT) RETURNS INT LANGUAGE SQL RETURN a + 1",
            "CREATE",
            "DDL",
            [("F1", "FUNCTION", "created", "APP")],
        ),
        (
            "CREATE OR REPLACE TRIGGER app.trg2 NO CASCADE BEFORE UPDATE ON app.orders REFERENCING NEW AS n FOR EACH ROW SET n.name = UPPER(n.name)",
            "CREATE",
            "DDL",
            [("TRG2", "TRIGGER", "created", "APP")],
        ),
        (
            "ALTER TABLE app.orders ALTER COLUMN name SET DATA TYPE VARCHAR(100)",
            "ALTER",
            "DDL",
            [("ORDERS", "TABLE", "altered", "APP")],
        ),
        (
            "ALTER SEQUENCE app.seq1 RESTART WITH 500",
            "ALTER",
            "DDL",
            [("SEQ1", "SEQUENCE", "altered", "APP")],
        ),
        ("DROP TABLE IF EXISTS app.orders", "DROP", "DDL", [("ORDERS", "TABLE", "dropped", "APP")]),
        ("DROP INDEX app.ix1", "DROP", "DDL", [("IX1", "INDEX", "dropped", "APP")]),
        ("DROP SCHEMA app RESTRICT", "DROP", "DDL", [("APP", "SCHEMA", "dropped", None)]),
        ("DROP ALIAS app.al1", "DROP", "DDL", [("AL1", "SYNONYM", "dropped", "APP")]),
        (
            "RENAME TABLE app.old_t TO new_t",
            "RENAME",
            "DDL",
            [("OLD_T", "TABLE", "altered", "APP")],
        ),
        ("RENAME app.old_t TO new_t", "RENAME", "DDL", [("OLD_T", "TABLE", "altered", "APP")]),
        ("RENAME INDEX app.ix1 TO ix9", "RENAME", "DDL", [("IX1", "INDEX", "altered", "APP")]),
        (
            "COMMENT ON TABLE app.orders IS 'Orders table'",
            "COMMENT",
            "DDL",
            [("ORDERS", "TABLE", "altered", "APP")],
        ),
        (
            "COMMENT ON COLUMN app.orders.name IS 'The name'",
            "COMMENT",
            "DDL",
            [("ORDERS", "TABLE", "altered", "APP")],
        ),
        (
            "COMMENT ON COLUMN orders.name IS 'The name'",
            "COMMENT",
            "DDL",
            [("ORDERS", "TABLE", "altered", None)],
        ),
        (
            "ALTER SCHEMA app DATA CAPTURE NONE",
            "ALTER",
            "DDL",
            [("APP", "SCHEMA", "altered", None)],
        ),
        (
            "TRUNCATE TABLE app.orders IMMEDIATE",
            "TRUNCATE",
            "DDL",
            [("ORDERS", "TABLE", "altered", "APP")],
        ),
        ("TRUNCATE app.orders", "TRUNCATE", "DDL", [("ORDERS", "TABLE", "altered", "APP")]),
        (
            "GRANT SELECT, INSERT ON TABLE app.orders TO USER bob",
            "GRANT",
            "DDL",
            [("ORDERS", "TABLE", "referenced", "APP")],
        ),
        (
            "GRANT EXECUTE ON PROCEDURE app.p1 TO PUBLIC",
            "GRANT",
            "DDL",
            [("P1", "PROCEDURE", "referenced", "APP")],
        ),
        (
            "REVOKE ALL ON app.orders FROM USER bob",
            "REVOKE",
            "DDL",
            [("ORDERS", "TABLE", "referenced", "APP")],
        ),
        (
            "LOCK TABLE app.orders IN EXCLUSIVE MODE",
            "LOCK",
            "UNKNOWN",
            [("ORDERS", "TABLE", "referenced", "APP")],
        ),
        (
            "CALL SYSPROC.ADMIN_CMD('REORG TABLE app.orders')",
            "CALL",
            "UNKNOWN",
            [("ADMIN_CMD", "PROCEDURE", "referenced", "SYSPROC")],
        ),
        ("CALL app.p1(1)", "CALL", "UNKNOWN", [("P1", "PROCEDURE", "referenced", "APP")]),
        (
            "CREATE TABLE t (id INT) -- trailing comment",
            "CREATE",
            "DDL",
            [("T", "TABLE", "created", None)],
        ),
    ],
)
def test_ddl_heads_name_their_target(sql, operation, kind, objects):
    facts = READ(sql)
    assert (facts.operation, facts.kind) == (operation, kind)
    assert [(o.name, o.type.value, o.role, o.schema) for o in facts.objects] == objects


@pytest.mark.parametrize(
    ("sql", "name", "schema"),
    [
        ("CALL proc()", "PROC", None),
        ("CALL app.p1(1)", "P1", "APP"),
        ('CALL "App"."Proc"(1)', "Proc", "App"),
    ],
)
def test_call_keeps_its_proven_head_identity_but_reports_unknown_effects(sql, name, schema):
    facts = READ(sql)

    assert (facts.operation, facts.kind) == ("CALL", "UNKNOWN")
    assert [(o.name, o.type.value, o.role, o.schema) for o in facts.objects] == [
        (name, "PROCEDURE", "referenced", schema)
    ]
    assert facts.opaque and facts.diagnostic and facts.error is None
    assert facts.affected_objects == ()
    assert (facts.target, facts.predicate, facts.events, facts.affected_columns) == (
        None,
        None,
        None,
        (),
    )


@pytest.mark.parametrize("sql", ["CALL", "CALL .proc()", 'CALL ""()', 'CALL "unterminated()'])
def test_call_with_unreadable_head_names_no_procedure(sql):
    facts = READ(sql)

    assert (facts.operation, facts.kind, facts.objects) == ("CALL", "UNKNOWN", ())
    assert facts.opaque


@pytest.mark.parametrize(
    ("sql", "diagnostic"),
    [
        ("CREATE TABLE a.b.c (id INT)", NAME_NOT_READ.format(operation="CREATE", type="TABLE")),
        ("CREATE TABLE (id INT)", NAME_NOT_READ.format(operation="CREATE", type="TABLE")),
        ("CREATE TABLE app. (id INT)", NAME_NOT_READ.format(operation="CREATE", type="TABLE")),
        ("DROP TABLE", NAME_NOT_READ.format(operation="DROP", type="TABLE")),
        ("CREATE INDEX ix ON (a)", NAME_NOT_READ.format(operation="CREATE", type="INDEX")),
        ("CREATE SCHEMA a.b", NAME_NOT_READ.format(operation="CREATE", type="SCHEMA")),
        ("TRUNCATE TABLE ONLY users", NAME_NOT_READ.format(operation="TRUNCATE", type="TABLE")),
        (
            "GRANT USAGE ON FOREIGN SERVER srv TO bob",
            NAME_NOT_READ.format(operation="GRANT", type="TABLE"),
        ),
        ("CREATE TABLE `t` (id INT)", NAME_NOT_READ.format(operation="CREATE", type="TABLE")),
    ],
)
def test_a_name_the_head_cannot_read_leaves_the_statement_opaque(sql, diagnostic):
    facts = READ(sql)
    assert facts.objects == () and facts.diagnostic == diagnostic


def test_column_bearing_statements_state_columns_unavailable():
    for sql in (
        "CREATE TABLE t (id INT)",
        "ALTER TABLE t ADD COLUMN c INT",
        "CREATE INDEX ix ON t (a)",
        "DECLARE GLOBAL TEMPORARY TABLE tmp (id INT)",
    ):
        facts = READ(sql)
        assert facts.opaque and facts.objects and facts.diagnostic == COLUMNS_UNAVAILABLE
        assert (facts.declared_columns, facts.declared_constraints, facts.indexed_columns) == (
            (),
            (),
            None,
        )


def test_index_names_its_table():
    assert READ("CREATE INDEX app.ix1 ON app.orders (name)").indexed_table == "APP.ORDERS"


def test_statements_without_column_facts_are_not_opaque():
    for sql in (
        "DROP TABLE t",
        "CREATE VIEW v AS SELECT 1 FROM sysibm.sysdummy1",
        "COMMENT ON TABLE t IS 'x'",
        "CREATE SEQUENCE s",
        "GRANT SELECT ON t TO PUBLIC",
        "TRUNCATE t",
    ):
        assert not READ(sql).opaque, sql


def test_truncate_has_no_dml_target():
    facts = READ("TRUNCATE TABLE app.orders IMMEDIATE")
    assert (facts.target, facts.events, facts.predicate) == (None, None, None)


def test_folding_reads_the_quirks_case():
    assert (fold_name("orders"), fold_name('"Orders"'), fold_name('"a""b"')) == (
        "ORDERS",
        "Orders",
        'a"b',
    )


@pytest.mark.parametrize(
    "sql",
    ["LABEL ON TABLE app.orders IS 'Orders'", "LABEL ON COLUMN app.orders.name IS 'The name'"],
)
def test_label_on_is_not_a_db2_statement_and_stays_opaque(sql):
    facts = READ(sql)
    assert (facts.operation, facts.kind, facts.objects) == ("LABEL", "UNKNOWN", ())
    assert facts.diagnostic == NOT_CLASSIFIED.format(word="LABEL")


def test_alter_schema_names_one_part_only():
    assert READ("ALTER SCHEMA a.b DATA CAPTURE NONE").objects == ()


@pytest.mark.parametrize(
    "sql",
    [
        "DROP TABLE HIERARCHY root_t",
        "DROP VIEW HIERARCHY v",
        "DROP FUNCTION MAPPING fm",
        "DROP INDEX EXTENSION ext RESTRICT",
        "CREATE FUNCTION MAPPING fm FOR s.f",
        "ALTER TABLE HIERARCHY t",
        "CREATE INDEX EXTENSION ext (p INT)",
    ],
)
def test_a_second_word_is_not_taken_for_the_name(sql):
    facts = READ(sql)
    assert facts.objects == () and facts.opaque
    assert facts.diagnostic.startswith("db2 ") and "name not read" in facts.diagnostic


@pytest.mark.parametrize(
    ("sql", "name"),
    [
        ("CREATE TABLE mapping (id INT)", "MAPPING"),
        ("DROP TABLE hierarchy", "HIERARCHY"),
        ("DROP TABLE hierarchy CASCADE", "HIERARCHY"),
        ("DROP TABLE extension RESTRICT", "EXTENSION"),
        ('DROP TABLE "HIERARCHY"', "HIERARCHY"),
    ],
)
def test_a_second_word_alone_is_still_a_name(sql, name):
    assert [o.name for o in READ(sql).objects] == [name]


@pytest.mark.parametrize(
    "sql",
    [
        "GRANT USAGE ON VARIABLE v TO u",
        "GRANT SELECT ON TABLE t",
        "GRANT SELECT TO u",
        "GRANT ROLE_A TO u",
        "RENAME TABLESPACE a TO b",
        "COMMENT ON TABLE t",
        "CREATE INDEX ix (a)",
        "CREATE INDEX ix t (a)",
    ],
)
def test_head_guards_leave_the_statement_opaque(sql):
    facts = READ(sql)
    assert facts.objects == () and facts.opaque


@pytest.mark.parametrize(
    "sql",
    [
        'CREATE TABLE "test (id INTEGER PRIMARY KEY)',
        'DROP TABLE "t',
        'INSERT INTO "t VALUES (1)',
        'CREATE TABLE "a""b (id INT)',
    ],
)
def test_an_unterminated_quoted_identifier_names_nothing(sql):
    facts = READ(sql)
    assert facts.objects == ()
    assert facts.error == UNTERMINATED_IDENTIFIER
    assert facts.opaque


def test_a_doubled_quote_inside_a_closed_identifier_is_one_character_of_the_name():
    facts = READ('CREATE TABLE "a""b" (id INT)')
    assert [o.name for o in facts.objects] == ['a"b']


@pytest.mark.parametrize(
    ("sql", "operation", "type_"),
    [
        ("DROP INDEX CONCURRENTLY idx", "DROP", "INDEX"),
        ("DROP TABLE t{", "DROP", "TABLE"),
        ("DROP TABLE t}", "DROP", "TABLE"),
        ("CREATE SEQUENCE q[", "CREATE", "SEQUENCE"),
        ("CREATE SEQUENCE q]", "CREATE", "SEQUENCE"),
        ("CREATE SEQUENCE q`", "CREATE", "SEQUENCE"),
        ("CREATE TRIGGER tr{ AFTER INSERT ON t FOR EACH ROW BEGIN END", "CREATE", "TRIGGER"),
        ("CREATE SEQUENCE q=1", "CREATE", "SEQUENCE"),
        ("CREATE SEQUENCE q @", "CREATE", "SEQUENCE"),
    ],
)
def test_a_name_followed_by_what_the_form_does_not_allow_is_not_named(sql, operation, type_):
    facts = READ(sql)
    assert facts.objects == ()
    assert facts.diagnostic == NAME_NOT_READ.format(operation=operation, type=type_)


@pytest.mark.parametrize(
    ("sql", "name"),
    [
        ("DROP TABLE t RESTRICT", "T"),
        ("DROP PROCEDURE p (INT)", "P"),
        ("DROP TABLE t -- c", "T"),
        ("CREATE SEQUENCE q AS BIGINT", "Q"),
        ("CREATE TABLE t(id INT)", "T"),
    ],
)
def test_a_name_followed_by_what_the_form_allows_is_named(sql, name):
    assert [o.name for o in READ(sql).objects] == [name]


def test_an_empty_delimited_identifier_is_not_a_name():
    facts = READ('CREATE TABLE "" (x INT)')
    assert facts.objects == ()
    assert facts.diagnostic == NAME_NOT_READ.format(operation="CREATE", type="TABLE")
