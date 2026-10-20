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


@pytest.mark.parametrize(
    ("dialect", "sql"), [(d, s) for d in sorted(OTHER) for s in sorted(OTHER[d])]
)
def test_other_dialects_read_the_same_inputs_as_before(dialect, sql):
    assert _plain(read_statement_facts(sql, dialect=dialect)) == OTHER[dialect][sql]


def test_the_fixture_covers_every_other_sqlglot_dialect_with_a_plugin():
    assert set(OTHER) == {"duckdb", "oracle", "postgres", "redshift", "sqlite", "snowflake", "tsql"}
