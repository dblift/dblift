"""Db2 statement facts: a name touching a character the engine may read differently is not named."""

import sys

import pytest

from dblift.db.plugins.db2.parser.statement_facts import UNREAD_NAME, Db2StatementFactsReader

READ = Db2StatementFactsReader(None).read

UNREAD = [c for c in map(chr, range(0x80, sys.maxunicode + 1)) if c.isspace()] + [
    "​",
    "⁠",
    "﻿",
    "é",
    "表",
]


@pytest.mark.parametrize("char", UNREAD, ids=lambda c: f"U+{ord(c):04X}")
@pytest.mark.parametrize(
    "template",
    [
        "CREATE TABLE t{c}(id INT)",
        "CREATE TABLE {c}t (id INT)",
        "CREATE TABLE a{c}b (id INT)",
        "CREATE TABLE s{c}.t (id INT)",
        "DROP TABLE t{c}",
        "INSERT INTO t{c} VALUES (1)",
        "UPDATE t{c} SET a = 1",
        "DELETE FROM app.t{c} WHERE 1 = 1",
        "CREATE INDEX ix ON t{c}(a)",
    ],
)
def test_a_name_touching_an_unread_character_is_not_named(template, char):
    facts = READ(template.format(c=char))
    assert facts.objects == () and facts.target is None
    assert facts.diagnostic == UNREAD_NAME.format(code=ord(char))


@pytest.mark.parametrize(
    ("sql", "names"),
    [
        ('CREATE TABLE "café" (id INT)', ["café"]),
        ('CREATE TABLE "x y" (id INT)', ["x y"]),
        ("CREATE TABLE t (cé INT)", ["T"]),
        ("INSERT INTO t VALUES ('café')", ["T"]),
        ("CREATE TABLE t (id INT) -- café", ["T"]),
        ("CREATE TABLE t /* café */ (id INT)", ["T"]),
    ],
)
def test_an_unread_character_away_from_the_name_keeps_the_name(sql, names):
    assert [o.name for o in READ(sql).objects] == names


def test_an_unread_character_after_the_name_inside_the_head_is_not_named():
    facts = READ("CREATE TABLE t é (a INT)")
    assert facts.objects == ()
    assert facts.diagnostic == UNREAD_NAME.format(code=ord("é"))
