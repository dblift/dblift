"""Oracle statement facts: names as Oracle stores them, COMMENT ON, TRUNCATE, PL/SQL units and
the statements the grammar cannot read.

Every expectation is built by hand from what Oracle 23.26 (Free) runs: an unquoted name is stored
upper-cased and a quoted one exactly as written (``user_objects``); ``COMMENT ON`` accepts TABLE,
COLUMN and MATERIALIZED VIEW and rejects VIEW, INDEX and SEQUENCE (ORA-32594); ``TRUNCATE`` takes one
``TABLE`` (a bare ``TRUNCATE t`` is ORA-03290, a list is ORA-03291). The other dialects keep their
facts: the negative tests pin them.
"""

import pytest

from dblift.core.sql_model.base import SqlObjectType
from dblift.core.sql_parser.sqlglot_statement_facts import read_statement_facts
from dblift.core.sql_parser.statement_facts import NamedObject, StatementFacts

T = SqlObjectType


def _ora(sql):
    return read_statement_facts(sql, dialect="oracle")  # lint: allow-dialect-string: test


def _objects(sql):
    return [(o.name, o.type, o.role, o.schema) for o in _ora(sql).objects]


@pytest.mark.parametrize(
    "sql,expected",
    [
        ("CREATE TABLE mixedCase (a NUMBER)", [("MIXEDCASE", T.TABLE, "created", None)]),
        ('CREATE TABLE "mixedQ" (a NUMBER)', [("mixedQ", T.TABLE, "created", None)]),
        ("CREATE TABLE hr.emp (a NUMBER)", [("EMP", T.TABLE, "created", "HR")]),
        ('CREATE TABLE "Hr".emp (a NUMBER)', [("EMP", T.TABLE, "created", "Hr")]),
        ("CREATE TABLE a#b (a NUMBER)", [("A#B", T.TABLE, "created", None)]),
        ("DROP TABLE hr.emp CASCADE CONSTRAINTS", [("EMP", T.TABLE, "dropped", "HR")]),
        ("ALTER TABLE emp ADD (c NUMBER)", [("EMP", T.TABLE, "altered", None)]),
        (
            "CREATE INDEX ix ON emp (a)",
            [("IX", T.INDEX, "created", None), ("EMP", T.TABLE, "referenced", None)],
        ),
        ("CREATE SEQUENCE seq1", [("SEQ1", T.SEQUENCE, "created", None)]),
    ],
)
def test_unquoted_names_are_upper_case_and_quoted_names_exact(sql, expected):
    assert _objects(sql) == expected


def test_a_data_change_target_is_folded_in_its_objects_and_target():
    facts = _ora("UPDATE hr.emp SET a = 1 WHERE b = 2")

    assert [(o.name, o.schema) for o in facts.objects] == [("EMP", "HR")]
    assert facts.target == "HR.EMP"
    assert facts.predicate == "b = 2"
    assert facts.affected_columns == ("a",)


@pytest.mark.parametrize(
    "sql,expected",
    [
        ("COMMENT ON TABLE t IS 'x'", NamedObject("T", T.TABLE, "altered")),
        ("COMMENT ON TABLE hr.t IS 'x'", NamedObject("T", T.TABLE, "altered", "HR")),
        ("COMMENT ON COLUMN hr.t.c IS 'x'", NamedObject("T", T.TABLE, "altered", "HR")),
        ("COMMENT ON COLUMN t.c IS 'x'", NamedObject("T", T.TABLE, "altered")),
        (
            "COMMENT ON MATERIALIZED VIEW mv IS 'x'",
            NamedObject("MV", T.MATERIALIZED_VIEW, "altered"),
        ),
    ],
)
def test_comment_on_names_the_object_it_changes(sql, expected):
    assert _ora(sql) == StatementFacts("COMMENT", "DDL", (expected,))


@pytest.mark.parametrize(
    "sql",
    [
        "COMMENT ON VIEW v IS 'x'",
        "COMMENT ON INDEX i IS 'x'",
        "COMMENT ON SEQUENCE q IS 'x'",
    ],
)
def test_comment_on_a_kind_oracle_rejects_names_nothing(sql):
    facts = _ora(sql)

    assert facts.objects == ()
    assert facts.opaque


def test_a_materialized_view_is_created_as_one():
    assert _objects("CREATE MATERIALIZED VIEW mv AS SELECT 1 a FROM dual") == [
        ("MV", T.MATERIALIZED_VIEW, "created", None),
        ("DUAL", T.TABLE, "referenced", None),
    ]
    assert _objects("CREATE VIEW v AS SELECT 1 a FROM dual")[0] == ("V", T.VIEW, "created", None)


@pytest.mark.parametrize(
    "sql,expected",
    [
        ("TRUNCATE TABLE t", NamedObject("T", T.TABLE, "altered")),
        ("TRUNCATE TABLE hr.t", NamedObject("T", T.TABLE, "altered", "HR")),
        ('TRUNCATE TABLE "t"', NamedObject("t", T.TABLE, "altered")),
    ],
)
def test_truncate_names_its_table(sql, expected):
    assert _ora(sql) == StatementFacts("TRUNCATE", "DDL", (expected,))


@pytest.mark.parametrize(
    "sql",
    [
        "TRUNCATE TABLE t CASCADE",  # also truncates the child tables, which only a catalogue names
        "TRUNCATE TABLE a, b",  # ORA-03291
        "TRUNCATE CLUSTER c",
    ],
)
def test_truncate_forms_without_one_proven_table_name_nothing(sql):
    facts = _ora(sql)

    assert facts.objects == ()
    assert facts.opaque


@pytest.mark.parametrize(
    "sql,expected",
    [
        (
            "CREATE OR REPLACE FUNCTION hr.f RETURN NUMBER IS BEGIN RETURN 1; END;",
            ("F", T.FUNCTION, "created", "HR"),
        ),
        (
            "CREATE OR REPLACE PROCEDURE p AS BEGIN NULL; END;",
            ("P", T.PROCEDURE, "created", None),
        ),
        (
            "CREATE OR REPLACE PACKAGE pk AS PROCEDURE a; END pk;",
            ("PK", T.PACKAGE, "created", None),
        ),
        (
            "CREATE OR REPLACE PACKAGE BODY pk AS PROCEDURE a IS BEGIN NULL; END; END pk;",
            ("PK", T.PACKAGE_BODY, "created", None),
        ),
        (
            "CREATE OR REPLACE EDITIONABLE TRIGGER hr.trg AFTER UPDATE ON hr.t BEGIN NULL; END;",
            ("TRG", T.TRIGGER, "created", "HR"),
        ),
        (
            'CREATE OR REPLACE NONEDITIONABLE FUNCTION "f#" RETURN NUMBER IS BEGIN RETURN 1; END;',
            ("f#", T.FUNCTION, "created", None),
        ),
        ("CREATE TYPE ty AS OBJECT (a NUMBER)", ("TY", T.TYPE, "created", None)),
        ("CREATE SYNONYM syn FOR hr.t", ("SYN", T.SYNONYM, "created", None)),
        ("CREATE PUBLIC SYNONYM syn FOR hr.t", ("SYN", T.SYNONYM, "created", None)),
        ("DROP PACKAGE pk", ("PK", T.PACKAGE, "dropped", None)),
        (
            "CREATE DATABASE LINK dl CONNECT TO u IDENTIFIED BY p USING 'x'",
            ("DL", T.DATABASE_LINK, "created", None),
        ),
        (
            "CREATE PUBLIC DATABASE LINK dl CONNECT TO u IDENTIFIED BY p",
            ("DL", T.DATABASE_LINK, "created", None),
        ),
        ("DROP DATABASE LINK dl", ("DL", T.DATABASE_LINK, "dropped", None)),
    ],
)
def test_a_unit_the_grammar_returns_as_a_command_is_named_from_its_head_and_stays_opaque(
    sql, expected
):
    facts = _ora(sql)

    assert _objects(sql) == [expected]
    assert facts.opaque


@pytest.mark.parametrize(
    "sql",
    [
        "CREATE OR REPLACE TYPE BODY ty AS MEMBER FUNCTION f RETURN NUMBER IS BEGIN RETURN 1; END; END;",
        "CREATE PACKAGE body AS PROCEDURE a; END;",
        "CREATE USER u IDENTIFIED BY x",
        "CREATE ROLE r",
        "CREATE TABLESPACE ts DATAFILE 'x.dbf' SIZE 10M",
        "CREATE DATABASE LINK a.b CONNECT TO u IDENTIFIED BY p USING 'x'",
        "ALTER SESSION SET CURRENT_SCHEMA = hr",
    ],
)
def test_a_statement_whose_object_the_head_does_not_prove_names_nothing(sql):
    facts = _ora(sql)

    assert facts.objects == ()
    assert facts.opaque


@pytest.mark.parametrize(
    "sql",
    [
        "CREATE MATERIALIZED VIEW LOG ON hr.employees",
        "DROP MATERIALIZED VIEW LOG ON t",
        "ALTER MATERIALIZED VIEW LOG ON t ADD ROWID",
        # Oracle 23.26 reads LOG as the log keyword even without ON (ORA-00969 missing ON keyword)
        "CREATE MATERIALIZED VIEW LOG AS SELECT 1 a FROM dual",
    ],
)
def test_a_materialized_view_log_is_not_a_view_named_log(sql):
    facts = _ora(sql)

    assert facts.objects == ()
    assert facts.opaque


def test_a_quoted_materialized_view_named_log_is_a_view():
    assert _objects('CREATE MATERIALIZED VIEW "LOG" AS SELECT 1 a FROM dual')[0] == (
        "LOG",
        T.MATERIALIZED_VIEW,
        "created",
        None,
    )


def test_a_materialized_view_is_dropped_as_one():
    assert _objects("DROP MATERIALIZED VIEW mv") == [("MV", T.MATERIALIZED_VIEW, "dropped", None)]


@pytest.mark.parametrize(
    "sql",
    [
        "BEGIN NULL; END;",
        "DECLARE x NUMBER; BEGIN DELETE FROM t; END;",
        "BEGIN EXECUTE IMMEDIATE 'DROP TABLE x'; END;",
    ],
)
def test_an_anonymous_block_is_opaque_and_names_no_table_from_its_body(sql):
    facts = _ora(sql)

    assert facts.objects == ()
    assert facts.target is None
    assert facts.opaque


def test_a_unit_names_itself_and_nothing_from_its_body():
    sql = (
        "CREATE OR REPLACE PROCEDURE p AS BEGIN EXECUTE IMMEDIATE 'DROP TABLE x'; "
        "UPDATE t SET a = 1; END;"
    )

    assert _objects(sql) == [("P", T.PROCEDURE, "created", None)]


@pytest.mark.parametrize(
    "sql,table",
    [
        ("INSERT INTO t (a) VALUES (q'{a'b}')", "T"),
        ("INSERT INTO t (a) VALUES (q'[x; DROP TABLE y]')", "T"),
        ("UPDATE t SET a = q'!it's ; WHERE!' WHERE id = 1", "T"),
        ("DELETE FROM t WHERE a = Q'<x>' ", "T"),
    ],
)
def test_q_quoted_strings_do_not_hide_or_invent_names(sql, table):
    facts = _ora(sql)

    assert [o.name for o in facts.objects] == [table]
    assert not facts.opaque


def test_a_table_created_with_a_tablespace_clause_is_read_by_the_grammar():
    facts = _ora("CREATE TABLE hr.emp (id NUMBER PRIMARY KEY) TABLESPACE users")

    assert facts == StatementFacts(
        "CREATE",
        "DDL",
        (NamedObject("EMP", T.TABLE, "created", "HR"),),
        declared_columns=("id",),
        declared_constraints=facts.declared_constraints,
    )


@pytest.mark.parametrize("dialect", ["postgres", "mysql", "sqlite", "duckdb"])
def test_other_dialects_keep_the_spelling_the_statement_uses(dialect):
    facts = read_statement_facts("CREATE TABLE MixedCase (a INT)", dialect=dialect)

    assert [o.name for o in facts.objects] == ["MixedCase"]


@pytest.mark.parametrize(
    "sql,expected,table",
    [
        (
            "CREATE BITMAP INDEX bx ON orders (status)",
            [("BX", T.INDEX, "created", None), ("ORDERS", T.TABLE, "referenced", None)],
            "ORDERS",
        ),
        (
            "CREATE INDEX hr.ix#1 ON hr.t (a) TABLESPACE users",
            [("IX#1", T.INDEX, "created", "HR"), ("T", T.TABLE, "referenced", "HR")],
            "T",
        ),
        (
            'CREATE UNIQUE INDEX "Ix" ON "t" (a) TABLESPACE users',
            [("Ix", T.INDEX, "created", None), ("t", T.TABLE, "referenced", None)],
            "t",
        ),
    ],
)
def test_an_index_read_from_its_head_names_the_table_it_is_built_on(sql, expected, table):
    facts = _ora(sql)

    assert _objects(sql) == expected
    assert facts.indexed_table == table
    assert facts.opaque


@pytest.mark.parametrize(
    "sql", ["CREATE BITMAP INDEX ix ON CLUSTER c", "CREATE BITMAP INDEX ix ON t", "DROP INDEX ix"]
)
def test_an_index_whose_table_the_head_does_not_prove_names_none(sql):
    facts = _ora(sql)

    assert facts.indexed_table is None
    assert [o.type for o in facts.objects] == [T.INDEX]


def test_merge_is_a_named_gap_that_names_nothing():
    facts = _ora("MERGE INTO t USING s ON (t.id = s.id) WHEN MATCHED THEN UPDATE SET t.a = s.a")

    assert facts.objects == ()
    assert facts.target is None and facts.events is None
    assert facts.opaque


@pytest.mark.parametrize(
    "sql,expected",
    [
        ("/* CREATE MATERIALIZED VIEW LOG ON x */ SELECT 1 FROM dual", "SELECT"),
        ("-- CREATE MATERIALIZED VIEW LOG ON x\nCREATE TABLE t (a NUMBER)", "CREATE"),
        ("/* DROP MATERIALIZED VIEW LOG ON t */ DROP TABLE t2", "DROP"),
    ],
)
def test_a_keyword_that_sits_only_in_a_comment_does_not_change_the_reading(sql, expected):
    facts = _ora(sql)

    assert facts.operation == expected
    assert facts.objects and not facts.opaque


def test_an_oracle_comment_ends_at_the_first_closer():
    facts = _ora("/* a /* b */ CREATE MATERIALIZED VIEW LOG ON x")

    assert facts.objects == () and facts.opaque


@pytest.mark.parametrize(
    "sql,table",
    [
        ("comment on table hr.t is 'x'", "T"),
        ("Comment On Column t.c Is 'x'", "T"),
        ("comment on materialized view mv is 'x'", "MV"),
    ],
)
def test_comment_on_is_read_whatever_the_case_of_its_keywords(sql, table):
    assert [o.name for o in _ora(sql).objects] == [table]


@pytest.mark.parametrize(
    "sql",
    [
        "TRUNCATE t",  # ORA-03290
        "TRUNCATE TABLE x PARTITION (p)",
        "TRUNCATE TABLE a.b.c",
        "TRUNCATE TABLE t@lnk",
    ],
)
def test_truncate_forms_oracle_rejects_name_nothing(sql):
    facts = _ora(sql)

    assert facts.objects == ()


@pytest.mark.parametrize(
    "sql",
    [
        "DELETE FROM emp@lnk WHERE a = 1",
        "SELECT * FROM hr.t@lnk",
        "INSERT INTO t@lnk VALUES (1)",
    ],
)
def test_an_object_reached_through_a_database_link_is_not_named_locally(sql):
    facts = _ora(sql)

    assert facts.objects == () and facts.target is None
    assert facts.opaque


@pytest.mark.parametrize(
    "sql",
    [
        "create materialized view log$x as select 1 a from dual",
        "create materialized view log#1 as select 1 a from dual",
    ],
)
def test_a_view_whose_name_starts_with_log_is_a_view(sql):
    assert _objects(sql)[0][1] == T.MATERIALIZED_VIEW


def test_a_bitmap_join_index_does_not_claim_one_table():
    facts = _ora(
        "CREATE BITMAP INDEX ix ON sales (c.name) FROM sales s, customers c WHERE s.id = c.id"
    )

    assert facts.indexed_table is None
    assert [o.type for o in facts.objects] == [T.INDEX]


# Oracle AI Database 26ai Free 23.26.3 accepted each of these as a call over a database link
# (ORA-12154 raised at the connection, after the parse), 2026-10-21.
@pytest.mark.parametrize(
    "sql",
    [
        "delete from emp @ lnk where a = 1",
        "update emp @ lnk set a = 1",
        "insert into emp @ lnk values (1)",
        "select * from emp\n@lnk",
        "select * from emp/*c*/@lnk",
        "select * from emp -- c\n@lnk",
        "insert into t select * from emp @ lnk",
        "create table t2 as select * from emp @ lnk",
        "select * from emp@ lnk",
        'select * from emp @ "lnk"',
        "select * from t where id in (select id from emp @ lnk)",
    ],
)
def test_a_database_link_written_with_blanks_or_comments_is_not_a_local_object(sql):
    facts = _ora(sql)

    assert facts.objects == () and facts.target is None
    assert facts.opaque


@pytest.mark.parametrize(
    "sql,names",
    [
        ("select '@lnk' from dual", ["DUAL"]),
        ("insert into t values ('a@b')", ["T"]),
        ("insert into t values (q'[x @ y]')", ["T"]),
        ('create table "a@b" (a number)', ["a@b"]),
        ("select 1 from dual -- @lnk", ["DUAL"]),
        ("select /* @lnk */ 1 from dual", ["DUAL"]),
    ],
)
def test_an_at_sign_in_a_string_comment_or_quoted_name_is_not_a_link(sql, names):
    facts = _ora(sql)

    assert [o.name for o in facts.objects] == names
    assert not facts.opaque


# Oracle 23.26.3 stores unquoted names with the one-character upper-case mapping of each letter:
# ı is I, µ is the Greek capital MU, ÿ is Ÿ, σ and ς are Σ; ß, ﬁ and ŉ stay as they are, which the
# multi-character mapping of Python's str.upper would not give (SS, FI, ʼN).
@pytest.mark.parametrize(
    "letter,stored",
    [("ı", "I"), ("µ", "Μ"), ("ÿ", "Ÿ"), ("σ", "Σ"), ("ς", "Σ"), ("ø", "Ø"), ("д", "Д")],
)
def test_unquoted_names_fold_letter_by_letter_as_oracle_stores_them(letter, stored):
    assert _ora(f"create table {letter}tab (a number)").objects[0].name == f"{stored}TAB"
    assert _ora(f"create table {letter}tab (a number) tablespace users").objects[0].name == (
        f"{stored}TAB"
    )


@pytest.mark.parametrize("letter", ["ß", "ﬁ", "ŉ"])
@pytest.mark.parametrize(
    "template",
    [
        "create table {l}tab (a number)",
        "create table s.t{l} (a number)",
        "create index {l}ix on t (a)",
        "create or replace procedure {l}p as begin null; end;",
        "create index {l}ix on t (a) tablespace users",
        "delete from {l}t where a = 1",
    ],
)
def test_a_name_whose_upper_case_form_is_not_one_character_per_letter_is_not_named(
    letter, template
):
    facts = _ora(template.format(l=letter))

    assert facts.objects == () and facts.target is None
    assert facts.opaque


def test_quoted_names_with_such_letters_stay_exact():
    assert _ora('create table "ßtab" (a number)').objects[0].name == "ßtab"
