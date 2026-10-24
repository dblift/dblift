"""MySQL statement facts for forms the engine accepts and the reader left unread or misread.

Every expectation here was checked against MySQL 8.0.46, 8.4.11 and MariaDB 11.8.8: the
statements run, and the object they act on is the one asserted. The other-dialect fixture
pins what every other sqlglot dialect returned for the same inputs before these MySQL arms
existed, so a MySQL arm cannot leak into another grammar.
"""

import json
from pathlib import Path

import pytest

from dblift.core.sql_model.base import SqlObjectType
from dblift.core.sql_parser import sqlglot_statement_facts
from dblift.core.sql_parser.sqlglot_statement_facts import read_statement_facts
from dblift.db import dml_analysis

OTHER = json.loads(
    (Path(__file__).with_name("mysql_facts_gaps_other_dialects.json")).read_text(encoding="utf-8")
)
EMOJI = "\U0001f600"  # outside the Basic Multilingual Plane: MySQL stores ``?``, MariaDB rejects


def mysql(sql):
    return read_statement_facts(sql, dialect="mysql")


def objects(facts):
    return [(obj.name, obj.type, obj.role, obj.schema) for obj in facts.objects]


def test_named_foreign_key_alter_is_read_without_a_grammar_gap():
    facts = mysql("ALTER TABLE t ADD FOREIGN KEY fk_user(user_id) REFERENCES users(id)")

    assert facts.diagnostic is None
    assert objects(facts) == [("t", SqlObjectType.TABLE, "altered", None)]


# --- TRUNCATE -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("sql", "name", "schema"),
    [
        ("TRUNCATE t", "t", None),
        ("TRUNCATE TABLE t", "t", None),
        ("TRUNCATE TABLE db.t", "t", "db"),
        ("TRUNCATE `Cap Probe`", "Cap Probe", None),
    ],
)
def test_truncate_names_its_one_table(sql, name, schema):
    facts = mysql(sql)

    assert (facts.operation, facts.kind) == ("TRUNCATE", "DDL")
    assert not facts.opaque
    assert objects(facts) == [(name, SqlObjectType.TABLE, "altered", schema)]


def test_truncate_of_a_table_list_stays_opaque():
    # MySQL rejects ``TRUNCATE t1, t2`` (error 1064): nothing to name.
    facts = mysql("TRUNCATE t1, t2")

    assert facts.operation == "TRUNCATE"
    assert facts.opaque
    assert facts.objects == ()


# --- CREATE / DROP SCHEMA (a database, in MySQL's vocabulary) -----------------------------


@pytest.mark.parametrize(
    ("sql", "role"),
    [
        ("CREATE SCHEMA s", "created"),
        ("CREATE SCHEMA IF NOT EXISTS s", "created"),
        ("DROP SCHEMA s", "dropped"),
        ("DROP SCHEMA IF EXISTS s", "dropped"),
    ],
)
def test_schema_statements_name_the_schema(sql, role):
    facts = mysql(sql)

    assert facts.kind == "DDL"
    assert not facts.opaque
    assert objects(facts) == [("s", SqlObjectType.SCHEMA, role, None)]


# --- RENAME TABLE -------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("sql", "expected"),
    [
        ("RENAME TABLE a TO b", [("a", SqlObjectType.TABLE, "altered", None)]),
        (
            "RENAME TABLE a TO b, c TO d",
            [
                ("a", SqlObjectType.TABLE, "altered", None),
                ("c", SqlObjectType.TABLE, "altered", None),
            ],
        ),
        ("RENAME TABLE db.a TO db.b", [("a", SqlObjectType.TABLE, "altered", "db")]),
        ("RENAME TABLE `we``ird` TO plain", [("we`ird", SqlObjectType.TABLE, "altered", None)]),
    ],
)
def test_rename_table_names_each_source_as_altered(sql, expected):
    facts = mysql(sql)

    assert (facts.operation, facts.kind) == ("RENAME", "DDL")
    assert not facts.opaque
    assert objects(facts) == expected


@pytest.mark.parametrize("sql", ["RENAME TABLE t1", "RENAME TABLE a TO b, c", "RENAME TABLE a TO"])
def test_an_incomplete_rename_names_nothing(sql):
    facts = mysql(sql)

    assert facts.operation == "RENAME"
    assert facts.opaque
    assert facts.objects == ()


# --- CREATE FULLTEXT / SPATIAL INDEX -------------------------------------------------------


@pytest.mark.parametrize(
    ("sql", "index", "table", "schema"),
    [
        ("CREATE FULLTEXT INDEX fx ON ft (txt)", "fx", "ft", None),
        ("CREATE SPATIAL INDEX sx ON ft (g)", "sx", "ft", None),
        ("CREATE FULLTEXT INDEX fx ON db.ft (txt) WITH PARSER ngram", "fx", "ft", "db"),
        ("CREATE FULLTEXT INDEX `f x` ON `ft` (`txt`, body)", "f x", "ft", None),
    ],
)
def test_fulltext_and_spatial_index_name_the_index_and_its_table(sql, index, table, schema):
    facts = mysql(sql)

    assert (facts.operation, facts.kind) == ("CREATE", "DDL")
    assert objects(facts) == [
        (index, SqlObjectType.INDEX, "created", None),
        (table, SqlObjectType.TABLE, "referenced", schema),
    ]
    assert facts.indexed_table == (f"{schema}.{table}" if schema else table)


def test_a_fulltext_index_without_a_name_names_nothing():
    # SQL Server syntax; MySQL rejects it (error 1064). ``ON`` is not an index name.
    facts = mysql("CREATE FULLTEXT INDEX ON t (c)")

    assert facts.operation == "CREATE"
    assert facts.objects == ()


# --- DML modifiers between the verb and the target ----------------------------------------


@pytest.mark.parametrize(
    ("sql", "operation", "target", "target_sql"),
    [
        ("UPDATE LOW_PRIORITY t SET a = 1", "UPDATE", "t", "t"),
        ("UPDATE /* c */ LOW_PRIORITY t SET a = 1", "UPDATE", "t", "t"),
        ("UPDATE -- c\n LOW_PRIORITY t SET a = 1", "UPDATE", "t", "t"),
        ("UPDATE # c\n LOW_PRIORITY t SET a = 1", "UPDATE", "t", "t"),
        ("UPDATE LOW_PRIORITY -- c\n IGNORE t SET a = 1", "UPDATE", "t", "t"),
        ("DELETE -- c\n QUICK FROM t", "DELETE", "t", "t"),
        ("UPDATE IGNORE `Cap Probe` SET b = 1", "UPDATE", "Cap Probe", "`Cap Probe`"),
        ("UPDATE LOW_PRIORITY IGNORE `s`.`t` SET b = 1", "UPDATE", "s.t", "`s`.`t`"),
        (
            "DELETE LOW_PRIORITY QUICK IGNORE FROM `Cap Probe` WHERE id = 1",
            "DELETE",
            "Cap Probe",
            "`Cap Probe`",
        ),
        ("DELETE QUICK FROM t", "DELETE", "t", "t"),
        ("DELETE IGNORE FROM t", "DELETE", "t", "t"),
        (
            "INSERT DELAYED IGNORE INTO `Cap Probe` (a) VALUES (1)",
            "INSERT",
            "Cap Probe",
            "`Cap Probe`",
        ),
        (
            "INSERT LOW_PRIORITY INTO `Cap Probe` (a) VALUES (1)",
            "INSERT",
            "Cap Probe",
            "`Cap Probe`",
        ),
        ("INSERT HIGH_PRIORITY INTO t (a) VALUES (1)", "INSERT", "t", "t"),
        ("REPLACE LOW_PRIORITY INTO t VALUES (1)", "REPLACE", "t", "t"),
        ("REPLACE DELAYED INTO t VALUES (1)", "REPLACE", "t", "t"),
    ],
)
def test_modifiers_are_not_the_target(sql, operation, target, target_sql):
    facts = mysql(sql)

    assert (facts.operation, facts.kind) == (operation, "DML")
    assert facts.target == target
    assert facts.target_sql == target_sql
    assert objects(facts)[0][:3] == (target.rpartition(".")[2], SqlObjectType.TABLE, "altered")
    assert facts.diagnostic is None or facts.operation == "REPLACE"


@pytest.mark.parametrize(
    "sql",
    [
        "UPDATE --x\n LOW_PRIORITY t SET a = 1",
        "UPDATE --x LOW_PRIORITY t SET a = 1",
        "UPDATE LOW_PRIORITY LOW_PRIORITY t SET a = 1",
    ],
)
def test_a_modifier_word_is_never_the_target(sql):
    # ``--x`` without a following blank is not a comment in MySQL and the engine rejects all
    # three (error 1064); whatever the reader makes of them, the modifier word is not a table.
    facts = mysql(sql)

    assert facts.target != "LOW_PRIORITY"
    assert all(obj.name.upper() != "LOW_PRIORITY" for obj in facts.objects)


def test_modifier_elision_keeps_the_predicate_and_the_assignments():
    facts = mysql("UPDATE LOW_PRIORITY IGNORE t SET b = 1, c = 2 WHERE id = 1")

    assert facts.predicate == "id = 1"
    assert facts.affected_columns == ("b", "c")
    assert facts.events == frozenset({"UPDATE"})

    facts = mysql("DELETE LOW_PRIORITY QUICK IGNORE FROM t WHERE id = 1")
    assert facts.predicate == "id = 1"
    assert facts.events == frozenset({"DELETE"})


@pytest.mark.parametrize(
    ("sql", "target"),
    [
        # Each of these runs on MySQL 8.4.11 and MariaDB 11.8.8 (``quick`` is not reserved; a
        # quoted or ``$``-suffixed reserved word is a name). ``UPDATE ignore SET``, ``UPDATE
        # delayed t SET`` and ``INSERT INTO delayed`` are rejected by both engines (error 1064).
        ("UPDATE quick SET a = 1", "quick"),
        ("UPDATE `ignore` SET a = 1", "ignore"),
        ("UPDATE `low_priority` SET a = 1", "low_priority"),
        ("DELETE quick FROM quick", "quick"),
        ("DELETE FROM quick", "quick"),
        ("DELETE FROM `ignore` WHERE a = 1", "ignore"),
        ("INSERT INTO ignore$x (a) VALUES (1)", "ignore$x"),
        ("INSERT INTO `delayed` (a) VALUES (1)", "delayed"),
        ("UPDATE low_priority_x SET a = 1", "low_priority_x"),
        ("UPDATE ignore$x SET a = 1", "ignore$x"),
        ("UPDATE quick t SET a = 1", "quick"),
        ("UPDATE quick, u SET quick.a = u.a", "quick"),
        ("INSERT INTO quick (a) VALUES (1)", "quick"),
    ],
)
def test_a_table_named_like_a_modifier_is_the_target(sql, target):
    facts = mysql(sql)

    assert facts.target == target
    assert not facts.opaque


def test_a_schema_named_like_a_keyword_is_proven_from_the_head():
    # ``UPDATE ignore.t SET a = 1`` runs on both engines, but sqlglot's MySQL grammar rejects the
    # reserved word as a schema name; the single target is proven from the statement head.
    facts = mysql("UPDATE ignore.t SET a = 1 WHERE id = 1")

    assert facts.target == "ignore.t"
    assert facts.predicate == "id = 1"
    assert [(o.name, o.schema, o.role) for o in facts.objects] == [("t", "ignore", "altered")]


def test_modifier_words_elsewhere_in_the_statement_are_untouched():
    facts = mysql("UPDATE t SET quick = 2, `ignore` = 1 WHERE quick = 3")
    assert facts.target == "t"
    assert facts.affected_columns == ("quick", "ignore")
    assert facts.predicate == "quick = 3"

    facts = mysql("DELETE FROM t WHERE quick = 1")
    assert facts.target == "t"
    assert facts.predicate == "quick = 1"

    facts = mysql("INSERT INTO t (a) VALUES ('LOW_PRIORITY IGNORE')")
    assert facts.target == "t"
    assert not facts.opaque


def test_the_modifier_table_has_one_definition():
    assert dml_analysis._DML_MODIFIER_WORDS is sqlglot_statement_facts.MYSQL_DML_MODIFIER_WORDS
    assert sqlglot_statement_facts.MYSQL_DML_MODIFIER_WORDS == {
        "UPDATE": "LOW_PRIORITY|IGNORE",
        "DELETE": "LOW_PRIORITY|QUICK|IGNORE",
        "INSERT": "LOW_PRIORITY|HIGH_PRIORITY|DELAYED|IGNORE",
        "REPLACE": "LOW_PRIORITY|DELAYED",
    }


# --- Characters outside the Basic Multilingual Plane --------------------------------------


@pytest.mark.parametrize(
    "sql",
    [
        f"CREATE TABLE t{EMOJI} (id INT)",
        f"CREATE TABLE `t{EMOJI}` (id INT)",
        f"DROP TABLE t{EMOJI}",
        f"DROP TABLE `t{EMOJI}`",
        f"UPDATE t{EMOJI} SET a = 1",
        f"DELETE FROM `t{EMOJI}` WHERE id = 1",
        f"CREATE TABLE e (c{EMOJI} INT)",
        f"ALTER TABLE e ADD COLUMN `d{EMOJI}` INT",
        f"CREATE INDEX ix ON t (c{EMOJI})",
        f"RENAME TABLE `t{EMOJI}` TO b",
        f"RENAME TABLE t{EMOJI} TO b",
        f"RENAME TABLE a TO `b{EMOJI}`",
        f"CREATE FULLTEXT INDEX `f{EMOJI}` ON ft (txt)",
        f"TRUNCATE `t{EMOJI}`",
    ],
)
def test_a_name_holding_a_supplementary_character_is_not_reported(sql):
    facts = mysql(sql)

    assert facts.opaque
    assert facts.objects == ()
    assert facts.target is None
    assert facts.error is None
    assert "U+1F600" in (facts.diagnostic or "")
    assert "part of a name" not in facts.diagnostic


@pytest.mark.parametrize(
    ("sql", "target"),
    [
        (f"INSERT INTO t VALUES ('{EMOJI}')", "t"),
        (f"UPDATE t SET a = '{EMOJI}' WHERE b = '{EMOJI}'", "t"),
        (f"-- {EMOJI}\nUPDATE t SET a = 1", "t"),
        (f"UPDATE t /* {EMOJI} */ SET a = 1", "t"),
    ],
)
def test_a_supplementary_character_in_a_string_or_comment_changes_nothing(sql, target):
    facts = mysql(sql)

    assert not facts.opaque
    assert facts.target == target


def test_the_diagnostic_names_the_first_offending_code_point():
    facts = mysql("CREATE TABLE t\U0001f600\U0001f601 (id INT)")
    assert "U+1F600" in facts.diagnostic


# --- TABLESPACE and SEQUENCE heads (issue #664) ----------------------------------------------


@pytest.mark.parametrize(
    ("sql", "operation", "name", "role"),
    [
        ("DROP TABLESPACE ts", "DROP", "ts", "dropped"),
        ("DROP TABLESPACE ts ENGINE = InnoDB", "DROP", "ts", "dropped"),
        ("DROP TABLESPACE `we``ird ts`", "DROP", "we`ird ts", "dropped"),
        ("CREATE TABLESPACE ts ADD DATAFILE 'x.ibd'", "CREATE", "ts", "created"),
        ("CREATE TABLESPACE ts", "CREATE", "ts", "created"),
        ("ALTER TABLESPACE ts ADD DATAFILE 'y.ibd'", "ALTER", "ts", "altered"),
        ("ALTER TABLESPACE ts RENAME TO ts2", "ALTER", "ts", "altered"),
    ],
)
def test_a_tablespace_statement_names_the_tablespace(sql, operation, name, role):
    """Measured 2026-10-24 on MySQL 8.0.46, 8.4.11 and MariaDB 11.8.8, root, database ``db``.

    MySQL 8.0 and 8.4 run ``CREATE TABLESPACE f664ts ADD DATAFILE 'f664ts.ibd'``, ``CREATE
    TABLESPACE f664ts``, ``ALTER TABLESPACE f664ts RENAME TO f664ts2`` and ``DROP TABLESPACE
    f664ts2`` (they succeed), and answer ``DROP TABLESPACE f664ts ENGINE=InnoDB``, ``ALTER
    TABLESPACE f664ts ADD DATAFILE 'f664b.ibd'`` and ``DROP TABLESPACE `f664 ts` `` with error 3510
    (the tablespace is missing, a failure after parsing). MariaDB 11.8.8 rejects every one of
    them with error 1064. A tablespace is not schema-qualified. The rename also creates a second
    name, which the reader leaves unread, so that statement stays opaque.
    """
    facts = mysql(sql)

    assert (facts.operation, facts.kind) == (operation, "DDL")
    assert objects(facts) == [(name, SqlObjectType.TABLESPACE, role, None)]
    assert facts.affected_objects == facts.objects


@pytest.mark.parametrize(
    "sql",
    [
        "DROP TABLESPACE a.b",
        "CREATE TABLESPACE a.b ADD DATAFILE 'x.ibd'",
        "DROP UNDO TABLESPACE u",
        "CREATE UNDO TABLESPACE u ADD DATAFILE 'u.ibu'",
        "ALTER UNDO TABLESPACE u SET INACTIVE",
        f"DROP TABLESPACE ts{EMOJI}",
        "DROP TABLESPACE ts x",
    ],
)
def test_a_tablespace_head_the_reader_cannot_bound_names_nothing(sql):
    """Measured 2026-10-24: ``DROP TABLESPACE a.b`` and ``CREATE TABLESPACE a.b ADD DATAFILE
    'x.ibd'`` get error 1064 on MySQL 8.0.46, 8.4.11 and MariaDB 11.8.8, so a tablespace name has
    no schema part. ``DROP UNDO TABLESPACE u`` is accepted by MySQL (error 3510 for a missing
    one) and rejected by MariaDB; the head does not model the UNDO form, and the unread-name
    characters apply to these heads as to every other."""
    facts = mysql(sql)

    assert facts.opaque
    assert facts.objects == ()


@pytest.mark.parametrize(
    ("sql", "operation", "name", "schema", "role"),
    [
        ("CREATE SEQUENCE s", "CREATE", "s", None, "created"),
        ("CREATE SEQUENCE db.s START WITH 1", "CREATE", "s", "db", "created"),
        ("DROP SEQUENCE s", "DROP", "s", None, "dropped"),
        ("DROP SEQUENCE IF EXISTS db.s", "DROP", "s", "db", "dropped"),
        ("ALTER SEQUENCE s RESTART WITH 100", "ALTER", "s", None, "altered"),
        ("ALTER SEQUENCE db.s RESTART WITH 100", "ALTER", "s", "db", "altered"),
        ("ALTER SEQUENCE `my s` RESTART WITH 100", "ALTER", "my s", None, "altered"),
        ("ALTER SEQUENCE IF EXISTS s RESTART", "ALTER", "s", None, "altered"),
    ],
)
def test_a_sequence_statement_names_the_sequence_the_same_way_for_each_verb(
    sql, operation, name, schema, role
):
    """Measured 2026-10-24 on MySQL 8.0.46, 8.4.11 and MariaDB 11.8.8, root, database ``db``.

    MariaDB runs ``CREATE SEQUENCE f664s``, ``CREATE SEQUENCE db.f664s``, ``ALTER SEQUENCE f664s
    RESTART WITH 100``, ``ALTER SEQUENCE db.f664s RESTART WITH 100``, ``ALTER SEQUENCE IF EXISTS
    f664s RESTART``, ``DROP SEQUENCE f664s`` and ``DROP SEQUENCE IF EXISTS db.f664s`` (they
    succeed), and answers ``ALTER SEQUENCE f664missing RESTART WITH 100``, ``ALTER SEQUENCE
    `f664 s` RESTART WITH 100`` and ``DROP SEQUENCE f664missing`` with error 4091 (the sequence
    is missing, a failure after parsing). MySQL 8.0 and 8.4 reject every one of them with error
    1064. A sequence is a table of its schema (``db``), so it can be qualified.
    """
    facts = mysql(sql)

    assert (facts.operation, facts.kind) == (operation, "DDL")
    assert objects(facts) == [(name, SqlObjectType.SEQUENCE, role, schema)]


def test_a_three_part_sequence_name_names_nothing():
    # MariaDB rejects ``ALTER SEQUENCE a.b.c RESTART`` with error 1064 (measured 2026-10-24 on
    # MariaDB 11.8.8, and on MySQL 8.0.46 and 8.4.11, which reject every SEQUENCE statement).
    facts = mysql("ALTER SEQUENCE a.b.c RESTART WITH 100")

    assert facts.opaque
    assert facts.objects == ()


# --- Forms left unread by design (issue #664) -----------------------------------------------


@pytest.mark.parametrize(
    ("sql", "operation", "kind"),
    [
        ("WHILE x < 3 DO SET x = x + 1; END WHILE", "WHILE", "UNKNOWN"),
        ("IF 1 = 1 THEN DROP TABLE t; END IF", "IF", "UNKNOWN"),
        ("EXECUTE IMMEDIATE 'DROP TABLE temp'", "EXECUTE", "UNKNOWN"),
        ("EXECUTE IMMEDIATE CONCAT('DROP TABLE ', 'temp')", "EXECUTE", "UNKNOWN"),
    ],
)
def test_a_compound_statement_or_dynamic_sql_names_no_object(sql, operation, kind):
    """Measured 2026-10-24 on MySQL 8.0.46, 8.4.11 and MariaDB 11.8.8 (``DELIMITER $$`` so that
    the client sends the whole text).

    ``WHILE 1 = 0 DO SELECT 1; END WHILE`` and ``IF 1 = 0 THEN SELECT 1; END IF`` run on MariaDB
    outside a stored program and are rejected by MySQL 8.0 and 8.4 with error 1064; ``EXECUTE
    IMMEDIATE 'DROP TABLE IF EXISTS f664temp'`` runs on MariaDB and is rejected by MySQL with
    error 1064. By design no object is named: the statements inside a compound statement are not
    split, and the object of dynamic SQL is the content of a string, known only when the server
    evaluates it (see docs/sql-parsing/mysql.md section 12).
    """
    facts = mysql(sql)

    assert (facts.operation, facts.kind) == (operation, kind)
    assert facts.opaque
    assert facts.objects == ()


def test_a_statement_inside_a_trigger_body_is_not_an_object_of_its_own():
    """Measured 2026-10-24 on MySQL 8.0.46, 8.4.11 and MariaDB 11.8.8: ``CREATE TRIGGER f664tg
    BEFORE INSERT ON f664u FOR EACH ROW BEGIN CREATE INDEX f664i ON f664u (c); END`` is parsed
    by all three and refused with error 1422 (a commit inside a trigger). Only the trigger and
    its table are named; the body is not read, so ``i`` is not an object."""
    facts = mysql(
        "CREATE TRIGGER tg BEFORE INSERT ON t FOR EACH ROW BEGIN CREATE INDEX i ON u (c); END"
    )

    assert objects(facts) == [
        ("tg", SqlObjectType.TRIGGER, "created", None),
        ("t", SqlObjectType.TABLE, "referenced", None),
    ]
    assert facts.opaque


# --- Other dialects are unchanged -----------------------------------------------------------


def _plain(facts):
    return {
        "operation": facts.operation,
        "kind": facts.kind,
        "opaque": facts.opaque,
        "objects": [[o.name, o.type.value, o.role, o.schema] for o in facts.objects],
        "target": facts.target,
        "target_sql": facts.target_sql,
        "predicate": facts.predicate,
        "events": sorted(facts.events) if facts.events else None,
        "affected_columns": list(facts.affected_columns),
        "indexed_table": facts.indexed_table,
        "diagnostic": facts.diagnostic,
        "error": facts.error,
    }


TSQL_CHANGES = {
    "CREATE SCHEMA IF NOT EXISTS s": {"objects": [["s", "SCHEMA", "created", None]]},
    "CREATE SCHEMA s": {"objects": [["s", "SCHEMA", "created", None]]},
    "DELETE IGNORE FROM t": {"objects": [["t", "TABLE", "altered", None]]},
    "DELETE QUICK FROM t": {"objects": [["t", "TABLE", "altered", None]]},
    "DELETE quick FROM quick": {"objects": [["quick", "TABLE", "altered", None]]},
    "DROP SCHEMA IF EXISTS s": {"objects": [["s", "SCHEMA", "dropped", None]]},
    "DROP SCHEMA s": {"objects": [["s", "SCHEMA", "dropped", None]]},
    "TRUNCATE TABLE db.t": {
        "kind": "DDL",
        "opaque": False,
        "objects": [["t", "TABLE", "altered", "db"]],
        "diagnostic": None,
    },
    "TRUNCATE TABLE t": {
        "kind": "DDL",
        "opaque": False,
        "objects": [["t", "TABLE", "altered", None]],
        "diagnostic": None,
    },
    "TRUNCATE t": {
        "kind": "DDL",
        "opaque": False,
        "objects": [["t", "TABLE", "altered", None]],
        "diagnostic": None,
    },
    "TRUNCATE t1, t2": {"kind": "DDL", "diagnostic": "tsql TRUNCATE scope is opaque"},
    "UPDATE -- c\n LOW_PRIORITY t SET a = 1": {"target_sql": "LOW_PRIORITY"},
    "UPDATE IGNORE t SET b = 1": {"target_sql": "IGNORE"},
    "UPDATE LOW_PRIORITY IGNORE `s`.`t` SET b = 1": {
        "objects": [],
        "target": None,
        "target_sql": None,
        "events": None,
    },
    "UPDATE LOW_PRIORITY t SET a = 1": {"target_sql": "LOW_PRIORITY"},
    "UPDATE `ignore` SET a = 1": {
        "objects": [],
        "target": None,
        "target_sql": None,
        "events": None,
    },
    "UPDATE delayed t SET a = 1": {"target_sql": "delayed"},
    "UPDATE quick t SET a = 1": {"target_sql": "quick"},
}

SNOWFLAKE_CHANGES = {
    "CREATE SCHEMA IF NOT EXISTS s": {"objects": [["S", "SCHEMA", "created", None]]},
    "CREATE SCHEMA s": {"objects": [["S", "SCHEMA", "created", None]]},
    "DROP SCHEMA IF EXISTS s": {"objects": [["S", "SCHEMA", "dropped", None]]},
    "DROP SCHEMA s": {"objects": [["S", "SCHEMA", "dropped", None]]},
    # The modifier word is read as the table and the table as its alias; the alias is dropped.
    "UPDATE -- c\n LOW_PRIORITY t SET a = 1": {"target_sql": "LOW_PRIORITY"},
    "UPDATE IGNORE t SET b = 1": {"target_sql": "IGNORE"},
    "UPDATE LOW_PRIORITY t SET a = 1": {"target_sql": "LOW_PRIORITY"},
    "UPDATE delayed t SET a = 1": {"target_sql": "delayed"},
    "UPDATE quick t SET a = 1": {"target_sql": "quick"},
    # A single plain table is read; a list of tables is not.
    "TRUNCATE TABLE db.t": {
        "kind": "DDL",
        "opaque": False,
        "objects": [["T", "TABLE", "altered", "DB"]],
        "diagnostic": None,
    },
    "TRUNCATE TABLE t": {
        "kind": "DDL",
        "opaque": False,
        "objects": [["T", "TABLE", "altered", None]],
        "diagnostic": None,
    },
    "TRUNCATE t": {
        "kind": "DDL",
        "opaque": False,
        "objects": [["T", "TABLE", "altered", None]],
        "diagnostic": None,
    },
    "TRUNCATE t1, t2": {"diagnostic": "snowflake TRUNCATE target is not read"},
}


@pytest.mark.parametrize(
    ("dialect", "sql"), [(d, s) for d in sorted(OTHER) for s in sorted(OTHER[d])]
)
def test_other_dialects_read_the_same_inputs_as_before(dialect, sql):
    expected = OTHER[dialect][sql]
    if dialect == "tsql":
        expected = {**expected, **TSQL_CHANGES.get(sql, {})}
    if dialect == "snowflake":
        expected = {**expected, **SNOWFLAKE_CHANGES.get(sql, {})}
    if (
        dialect in {"duckdb", "postgres", "redshift", "snowflake"}
        and sql == "UPDATE `ignore` SET a = 1"
    ):
        # Those tokenizers do not recognize backticks as identifier quotes. The opaque
        # head cannot prove that this spelling names a table in these dialects.
        expected = {**expected, "objects": [], "target": None, "target_sql": None, "events": None}
    assert _plain(read_statement_facts(sql, dialect=dialect)) == expected


def test_the_fixture_covers_every_other_sqlglot_dialect_with_a_plugin():
    assert set(OTHER) == {"duckdb", "oracle", "postgres", "redshift", "sqlite", "snowflake", "tsql"}
