"""Statement facts never name an object the engine may read under a different name.

sqlglot reads 19 non-ASCII characters as blanks that SQLite, PostgreSQL and MySQL read as part
of a name, and DuckDB reads three zero-width characters as blanks that sqlglot keeps in a name.
A fact naming ``t`` for a statement that touches ``t`` followed by a no-break space makes a
generated undo drop the user's own ``t``. Such statements are reported without names instead.
"""

from __future__ import annotations

import sys
import unicodedata

import pytest
from sqlglot.dialects import Dialect

from dblift.core.sql_parser.sqlglot_statement_facts import read_statement_facts
from dblift.db.dml_analysis import analyze_dml
from dblift.db.plugins.duckdb.parser.duckdb_facts_parser import DuckDBFactsParser
from dblift.db.plugins.sqlite.parser.sqlite_facts_parser import SQLiteFactsParser
from dblift.db.provider_registry import ProviderRegistry

DIALECTS = ("sqlite", "duckdb", "postgres", "mysql", "oracle", "tsql", "redshift", "snowflake")

# sqlglot's non-ASCII blanks, plus the zero-width characters DuckDB reads as blanks.
BLANKS = [c for c in map(chr, range(0x80, sys.maxunicode + 1)) if c.isspace()]
ZERO_WIDTH = [chr(0x200B), chr(0x2060), chr(0xFEFF)]
UNREAD = BLANKS + ZERO_WIDTH
IDS = [f"U+{ord(c):04X}" for c in UNREAD]


def _quote(dialect: str, name: str) -> str:
    return f"`{name}`" if dialect == "mysql" else f'"{name}"'


# (operation, kind, template): ``{c}`` is the unread character.
TEMPLATES = {
    "name-after": ("CREATE", "DDL", "CREATE TABLE t{c}(id INT)"),
    "name-before": ("CREATE", "DDL", "CREATE TABLE {c}t(id INT)"),
    "name-inside": ("CREATE", "DDL", "CREATE TABLE a{c}b(id INT)"),
    "qualified-schema": ("CREATE", "DDL", "CREATE TABLE s{c}.t(id INT)"),
    "qualified-name": ("CREATE", "DDL", "CREATE TABLE s.t{c}(id INT)"),
    "column": ("CREATE", "DDL", "CREATE TABLE t (a{c} INT, b INT)"),
    "foreign-key": (
        "CREATE",
        "DDL",
        "CREATE TABLE t (a INT, FOREIGN KEY (a) REFERENCES p{c}(id))",
    ),
    "index-table": ("CREATE", "DDL", "CREATE INDEX ix ON t{c}(a)"),
    "index-column": ("CREATE", "DDL", "CREATE INDEX ix ON t(a{c}b)"),
    "drop": ("DROP", "DDL", "DROP TABLE t{c}"),
    "insert": ("INSERT", "DML", "INSERT INTO t{c} VALUES (1)"),
    "update-target": ("UPDATE", "DML", "UPDATE t{c} SET a = 1 WHERE b = 2"),
    "update-set-column": ("UPDATE", "DML", "UPDATE t SET a{c}b = 1 WHERE id = 2"),
    "delete-predicate": ("DELETE", "DML", "DELETE FROM t WHERE a{c}b = 1"),
    "trigger-name": (
        "CREATE",
        "DDL",
        "CREATE TRIGGER tr{c} AFTER INSERT ON t BEGIN SELECT 1; END",
    ),
    "trigger-body": (
        "CREATE",
        "DDL",
        "CREATE TRIGGER tr AFTER INSERT ON t BEGIN UPDATE u{c} SET a = 1; END",
    ),
    "cte-delete": ("DELETE", "DML", "WITH x AS (SELECT 1) DELETE FROM u{c} WHERE a = 1"),
    "rename": ("ALTER", "DDL", "ALTER TABLE t RENAME TO u{c}"),
}


def _assert_names_nothing(facts, operation: str, kind: str) -> None:
    assert facts.objects == ()
    assert facts.target is None and facts.target_sql is None and facts.predicate is None
    assert facts.declared_columns == () and facts.affected_columns == ()
    assert facts.indexed_table is None and facts.indexed_columns is None
    assert facts.events is None and facts.declared_constraints == ()
    assert facts.diagnostic and "U+" in facts.diagnostic
    assert facts.opaque
    assert facts.operation == operation
    assert facts.kind == kind


@pytest.mark.parametrize("char", UNREAD, ids=IDS)
@pytest.mark.parametrize("shape", sorted(TEMPLATES))
@pytest.mark.parametrize("dialect", DIALECTS)
def test_unread_name_characters_name_nothing(dialect, shape, char):
    operation, kind, template = TEMPLATES[shape]
    facts = read_statement_facts(template.format(c=char), dialect=dialect)
    _assert_names_nothing(facts, operation, kind)


@pytest.mark.parametrize("char", UNREAD, ids=IDS)
@pytest.mark.parametrize("dialect", ("sqlite", "duckdb"))
def test_active_plugin_readers_name_nothing(dialect, char):
    quirks = ProviderRegistry.get_quirks(dialect)
    for shape in ("name-after", "drop", "update-target", "trigger-name"):
        operation, kind, template = TEMPLATES[shape]
        _assert_names_nothing(quirks.statement_facts(template.format(c=char)), operation, kind)


@pytest.mark.parametrize("char", UNREAD, ids=IDS)
@pytest.mark.parametrize("parser", (SQLiteFactsParser, DuckDBFactsParser), ids=("sqlite", "duckdb"))
def test_parser_projection_names_nothing(parser, char):
    sql = f"CREATE TABLE t{char}(id INT); DROP TABLE u{char}; UPDATE v{char} SET a = 1"
    assert parser().extract_objects(sql) == []


UNTERMINATED = {
    "delete": ("DELETE", "DELETE FROM {c}u WHERE a = 1 /* note"),
    "update": ("UPDATE", "UPDATE {c}u SET a = 1 WHERE b = 2 /* note"),
    "insert": ("INSERT", "INSERT INTO {c}u VALUES (1) /* note"),
    "create": ("CREATE", "CREATE TABLE {c}u (a INT) /* note"),
    "drop": ("DROP", "DROP TABLE {c}u /* note"),
    "quote": ("DELETE", "DELETE FROM u{c} WHERE a = 'x"),
}


@pytest.mark.parametrize("char", UNREAD, ids=IDS)
@pytest.mark.parametrize("shape", sorted(UNTERMINATED))
@pytest.mark.parametrize("dialect", ("sqlite", "postgres", "mysql", "oracle", "tsql", "snowflake"))
def test_token_error_names_nothing_with_an_unread_character(dialect, shape, char):
    operation, template = UNTERMINATED[shape]
    sql = template.format(c=char)
    facts = read_statement_facts(sql, dialect=dialect)
    assert facts.error, "the statement stays reported as not tokenizable"
    assert facts.operation == operation
    assert facts.objects == ()
    assert facts.target is None and facts.predicate is None and facts.target_sql is None
    assert analyze_dml(sql, sqlglot_dialect=dialect).table == ""


@pytest.mark.parametrize("char", UNREAD, ids=IDS)
def test_token_error_on_duckdb_names_nothing(char):
    facts = ProviderRegistry.get_quirks("duckdb").statement_facts(
        f"DELETE FROM {char}u WHERE a = 1 /* note"
    )
    assert facts.objects == () and facts.target is None and facts.predicate is None


def test_token_error_still_names_the_target_without_an_unread_character():
    facts = read_statement_facts("DELETE FROM u WHERE a = 1 /* note", dialect="sqlite")
    assert facts.error and facts.target == "u"


NAMED = {
    "accented-letters": ("CREATE TABLE tété (id INT)", "tété"),
    "decomposed-letters": ("CREATE TABLE café (id INT)", None),
    "cjk": ("CREATE TABLE 中文 (id INT)", "中文"),
    "string": ("CREATE TABLE t (a TEXT DEFAULT 'x{c}y')", "t"),
    "string-insert": ("INSERT INTO t VALUES ('x{c}y')", "t"),
    "quoted-identifier": ("CREATE TABLE {q}a{c}b{q} (id INT)", "a{c}b"),
    "line-comment": ("-- note{c}x\nCREATE TABLE t (id INT)", "t"),
    "block-comment": ("/* x{c}y */ CREATE TABLE t (id INT)", "t"),
    "trailing-block-comment": ("CREATE TABLE t (id INT) /* x{c}y */", "t"),
}


@pytest.mark.parametrize("char", UNREAD, ids=IDS)
@pytest.mark.parametrize("shape", sorted(k for k in NAMED if NAMED[k][0].count("{c}")))
@pytest.mark.parametrize("dialect", ("sqlite", "postgres", "mysql", "oracle", "tsql", "snowflake"))
def test_unread_character_inside_text_stays_named(dialect, shape, char):
    template, expected = NAMED[shape]
    quote = "`" if dialect == "mysql" else '"'
    sql = template.format(c=char, q=quote)
    facts = read_statement_facts(sql, dialect=dialect)
    assert facts.diagnostic is None and facts.error is None, sql
    assert [o.name for o in facts.objects] == [expected.format(c=char)] or (
        facts.operation == "INSERT" and facts.target == "t"
    )


@pytest.mark.parametrize("dialect", DIALECTS)
@pytest.mark.parametrize("shape", ("accented-letters", "cjk"))
def test_letters_stay_named(dialect, shape):
    template, expected = NAMED[shape]
    facts = read_statement_facts(template, dialect=dialect)
    assert [o.name for o in facts.objects] == [expected]
    assert facts.diagnostic is None


@pytest.mark.parametrize("dialect", ("sqlite", "duckdb"))
def test_letters_stay_named_through_the_active_readers(dialect):
    quirks = ProviderRegistry.get_quirks(dialect)
    for sql, expected in (
        ("CREATE TABLE tété (id INT)", "tété"),
        ("CREATE TABLE 中文 (id INT)", "中文"),
        ("UPDATE tété SET a = 1 WHERE b = 2", "tété"),
    ):
        facts = quirks.statement_facts(sql)
        assert facts.diagnostic is None
        assert (facts.target or facts.objects[0].name) == expected


def test_the_unread_set_is_computed_not_listed():
    assert len(UNREAD) == 22
    assert all(unicodedata.category(c) in {"Zs", "Zl", "Zp", "Cc", "Cf"} for c in UNREAD)


@pytest.mark.parametrize("dialect", DIALECTS)
def test_sqlglot_blank_set_is_str_isspace(dialect):
    """The set of unread characters is derived from ``str.isspace``; this pins that sqlglot
    still reads exactly those characters as blanks, so a change upstream turns this red."""
    tokenizer = Dialect.get_or_raise(dialect)
    candidates = [
        chr(i)
        for i in range(1, sys.maxunicode + 1)
        if chr(i).isspace() or unicodedata.category(chr(i)) in {"Zs", "Zl", "Zp", "Cc", "Cf"}
    ]
    blank = set()
    for c in candidates:
        try:
            tokens = tokenizer.tokenize("t" + c + "u")
        except Exception:
            continue
        if len(tokens) == 2:
            blank.add(c)
    assert blank == {c for c in candidates if c.isspace()}
