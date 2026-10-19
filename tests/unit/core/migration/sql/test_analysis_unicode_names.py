"""Unicode object names and unreadable text in script analysis."""

from __future__ import annotations

import logging
import warnings

import pytest

from dblift.core.migration.sql.script_analysis import analyse_script
from dblift.db.plugins.oracle.parser.lexical_spec import ORACLE_SPEC

LEGACY = (
    "postgresql",
    "mysql",
    "mariadb",
    "sqlserver",
    "oracle",
    "db2",
    "snowflake",
    "redshift",
    "cockroachdb",
)
BLANKS = [" ", " ", "　", "\u0085", " ", " "]
ZERO_WIDTH = ["​", "⁠", "﻿"]
READ_WHOLE = ("sqlserver", "snowflake")
NAME_PARTS = ["‍", "­", "́"]
RULE = BLANKS + ZERO_WIDTH
IDS = {c: f"U+{ord(c):04X}" for c in RULE + NAME_PARTS}
ALL_BLANKS = [c for c in map(chr, range(0x80, 0x10000)) if c.isspace()]
TAIL_DIALECTS = ("postgresql", "mysql", "mariadb", "oracle", "db2", "redshift", "cockroachdb")
BYPASS_DIALECTS = ("postgresql", "mysql", "oracle")
BYPASS_CHARS = (" ", " ")


@pytest.fixture(autouse=True)
def _quiet():
    logging.disable(logging.CRITICAL)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        yield
    logging.disable(logging.NOTSET)


def refused(dialect: str, char: str) -> bool:
    return dialect == "oracle" and char.isspace() and char not in ORACLE_SPEC.text_blanks


def read_as_blank(dialect: str, char: str) -> bool:
    return dialect == "oracle" and char in ORACLE_SPEC.text_blanks


@pytest.mark.parametrize("dialect", LEGACY)
@pytest.mark.parametrize("char", RULE + NAME_PARTS, ids=IDS.get)
@pytest.mark.parametrize("template", ["DROP TABLE t{c} CASCADE;", "DELETE FROM t{c}WHERE a = 1;"])
def test_analysis_names_no_object_whose_name_holds_the_character(dialect, char, template):
    analysis = analyse_script(template.format(c=char), dialect)
    if dialect in READ_WHOLE and char in NAME_PARTS:
        return
    names = {obj.name.lower() for stmt in analysis.statements for obj in stmt.objects}
    assert "t" not in names
    assert not any(" t " in f" {c.reason} ".lower() for c in analysis.cautions)


def test_there_are_19_trailing_blanks():
    assert len(ALL_BLANKS) == 19


@pytest.mark.parametrize("dialect", TAIL_DIALECTS)
@pytest.mark.parametrize("char", ALL_BLANKS, ids=lambda c: f"U+{ord(c):04X}")
@pytest.mark.parametrize(
    "sql",
    ["CREATE SEQUENCE q{c};", "CREATE SEQUENCE q{c}", "CREATE TABLE t{c}", "CREATE TABLE t{c};\n"],
)
def test_create_name_with_trailing_blank_is_not_silently_changed(dialect, char, sql):
    analysis = analyse_script(sql.format(c=char), dialect)
    if refused(dialect, char):
        assert not analysis.statements and analysis.errors
        return
    assert [statement.operation for statement in analysis.statements] == ["CREATE"]
    assert not analysis.errors
    name = "q" if "SEQUENCE" in sql else "t"
    names = {obj.name.lower() for statement in analysis.statements for obj in statement.objects}
    if read_as_blank(dialect, char):
        assert names <= {name}
    else:
        assert name not in names


@pytest.mark.parametrize("dialect", TAIL_DIALECTS)
@pytest.mark.parametrize("char", ALL_BLANKS, ids=lambda c: f"U+{ord(c):04X}")
@pytest.mark.parametrize(
    "sql", ["DROP TABLE t{c};", "TRUNCATE TABLE t{c};", "DELETE FROM t{c};", "DROP TABLE t{c}"]
)
def test_analysis_of_a_name_that_ends_its_statement_names_what_the_engine_reads(dialect, char, sql):
    if refused(dialect, char):  # the script is not parsed: nothing is named
        assert not analyse_script(sql.format(c=char), dialect).statements
        return
    analysis = analyse_script(sql.format(c=char), dialect)
    names = {obj.name.lower() for stmt in analysis.statements for obj in stmt.objects}
    if read_as_blank(dialect, char):  # the engine reads the name before the blank
        assert "t" in names
        return
    assert "t" not in names
    assert not any(" t " in f" {c.reason} ".lower() for c in analysis.cautions)
    assert analysis.cautions, "the statement still deserves its caution"


@pytest.mark.parametrize("dialect", ("postgresql", "mysql", "redshift"))
def test_analysis_respects_the_flag_the_parser_set_for_a_cut_name(dialect):
    analysis = analyse_script("DROP TABLE tété;", dialect)
    assert not [obj for stmt in analysis.statements for obj in stmt.objects]
    assert analysis.cautions and not any("tété" in c.reason for c in analysis.cautions)


@pytest.mark.parametrize("dialect", LEGACY)
def test_unreadable_delete_is_cautioned_as_an_unreadable_one(dialect):
    (caution,) = analyse_script(f"DELETE FROM t{chr(0xA0)} CASCADE;", dialect).cautions
    assert "could not be read" in caution.reason and " of t" not in caution.reason


@pytest.mark.parametrize("dialect", BYPASS_DIALECTS)
@pytest.mark.parametrize("char", BYPASS_CHARS, ids=lambda c: f"U+{ord(c):04X}")
def test_analysis_of_a_statement_whose_text_also_stands_in_a_comment(dialect, char):
    if refused(dialect, char):  # the script is not parsed: nothing is named
        assert not analyse_script(f"-- DROP TABLE t\nDROP TABLE t{char};", dialect).statements
        return
    analysis = analyse_script(f"-- DROP TABLE t\nDROP TABLE t{char};", dialect)
    assert not [obj for stmt in analysis.statements for obj in stmt.objects]
    assert analysis.cautions and not any(" t " in f" {c.reason} " for c in analysis.cautions)
