"""The statement facts reader reports what it cannot read; it never raises."""

from __future__ import annotations

import pytest

from dblift.core.sql_parser.sqlglot_statement_facts import read_statement_facts

DIALECTS = ("sqlite", "duckdb", "postgres", "mysql", "oracle", "tsql", "redshift", "snowflake")


@pytest.mark.parametrize("dialect", DIALECTS)
def test_index_without_columns_is_read_as_opaque(dialect):
    facts = read_statement_facts("CREATE INDEX ix ON t USING", dialect=dialect)

    assert facts.operation == "CREATE"
    assert facts.indexed_columns is None
    assert facts.opaque


def test_alter_session_is_read_as_opaque_on_snowflake():
    facts = read_statement_facts("ALTER SESSION SET LOCK_TIMEOUT = 0", dialect="snowflake")

    assert facts.operation == "ALTER"
    assert facts.objects == ()
    assert facts.opaque


@pytest.mark.parametrize("dialect", DIALECTS)
def test_alter_session_does_not_raise_on_any_dialect(dialect):
    assert read_statement_facts("ALTER SESSION SET LOCK_TIMEOUT = 0", dialect=dialect).operation


BLANKS = [c for c in map(chr, range(0x80, 0x10000)) if c.isspace()]
BLANK_IDS = [f"U+{ord(c):04X}" for c in BLANKS]


@pytest.mark.parametrize("char", BLANKS, ids=BLANK_IDS)
@pytest.mark.parametrize("tail", ["", " /* note"], ids=["tokenizes", "token-error"])
@pytest.mark.parametrize("dialect", ("sqlite", "postgres", "mysql"))
def test_a_unicode_blank_inside_a_two_word_object_type_never_raises(dialect, tail, char):
    from dblift.core.migration.sql.script_analysis import analyse_script

    sql = f"CREATE VIRTUAL{char}TABLE t USING fts5(a){tail}"

    assert read_statement_facts(sql, dialect=dialect).operation == "CREATE"
    analysis = analyse_script(sql + ";", dialect)
    assert analysis.statements or analysis.errors


FUZZ_STATEMENTS = (
    "CREATE TABLE t (id INT, name TEXT)",
    "CREATE VIRTUAL TABLE t USING fts5(a)",
    "CREATE UNIQUE INDEX IF NOT EXISTS ix ON s.t (a, b)",
    "CREATE VIEW v AS SELECT a FROM t WHERE b = 1",
    "CREATE TRIGGER tr AFTER INSERT ON t BEGIN UPDATE u SET a = 1; END",
    "ALTER TABLE t ADD COLUMN c INT",
    "DROP TABLE IF EXISTS s.t",
    "DROP MATERIALIZED VIEW m",
    "INSERT INTO t (a) VALUES ('x y')",
    "UPDATE t SET a = 1 WHERE b = 2 -- note",
    "DELETE FROM s.t WHERE a = 1 /* c */",
    "WITH x AS (SELECT 1) DELETE FROM u WHERE a = 1",
    "ALTER SESSION SET LOCK_TIMEOUT = 0",
    "DELETE FROM t WHERE a = 'x",
)


def test_random_unicode_blanks_never_raise_in_the_reader_or_the_analysis():
    import random

    from dblift.core.migration.sql.script_analysis import analyse_script

    unread = sorted(set(BLANKS) | {"\u200b", "\u2060", "\ufeff"})
    rng = random.Random(20261017)
    for _ in range(100):
        base = rng.choice(FUZZ_STATEMENTS)
        sql = base
        for _ in range(rng.randint(1, 3)):
            at = rng.randrange(len(sql) + 1)
            sql = sql[:at] + rng.choice(unread) + sql[at:]
        for dialect in DIALECTS:
            read_statement_facts(sql, dialect=dialect)
            analyse_script(sql + ";", dialect)
