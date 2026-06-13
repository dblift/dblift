"""Unit tests for `db.plugins.oracle.parser._statement_splitter` (Phase-Oracle-05)."""

from __future__ import annotations

from typing import List, Tuple

import pytest

from db.plugins.oracle.parser._statement_splitter import (
    extract_next_complete_statement,
    extract_regular_statement,
    is_empty_or_comment,
    is_plsql_keyword_start,
    split_statements_regex,
    word_at_position,
)


def _fake_plsql_extractor(text: str, start_pos: int) -> Tuple[str, int]:
    """Fake PL/SQL extractor for tests that don't exercise the PL/SQL path.

    Scans to the first ``END;`` followed by optional ``/`` on its own line,
    which is just enough to honour the splitter's contract in tests that
    build synthetic PL/SQL blocks. Not production grade.
    """
    end_marker = text.upper().find("END;", start_pos)
    if end_marker == -1:
        return text[start_pos:].strip(), len(text)
    stop = end_marker + 4  # include the ``END;``
    # Swallow trailing whitespace + optional ``/``.
    while stop < len(text) and text[stop].isspace():
        stop += 1
    if stop < len(text) and text[stop] == "/":
        stop += 1
        while stop < len(text) and text[stop].isspace():
            stop += 1
    return text[start_pos:stop].strip(), stop


@pytest.mark.unit
class TestIsPlsqlKeywordStart:
    @pytest.mark.parametrize(
        "text",
        [
            "BEGIN",
            "DECLARE",
            "CREATE PROCEDURE p AS BEGIN NULL; END;",
            "CREATE OR REPLACE PROCEDURE p AS BEGIN NULL; END;",
            "CREATE FUNCTION f RETURN NUMBER AS BEGIN RETURN 1; END;",
            "CREATE OR REPLACE FUNCTION f RETURN NUMBER AS BEGIN RETURN 1; END;",
            "CREATE PACKAGE pkg AS END;",
            "CREATE PACKAGE BODY pkg AS END;",
            "CREATE TRIGGER trg BEFORE INSERT ON t BEGIN NULL; END;",
            "CREATE COMPOUND TRIGGER trg FOR INSERT ON t END;",
            "CREATE TYPE t AS OBJECT (a NUMBER);",
            "CREATE TYPE BODY t AS END;",
            "CREATE JAVA SOURCE NAMED j AS public class J {}",
            "CREATE AND RESOLVE JAVA SOURCE NAMED j AS public class J {}",
            "CREATE AND COMPILE JAVA SOURCE NAMED j AS public class J {}",
            "CREATE EDITIONABLE PROCEDURE p AS BEGIN NULL; END;",
            "CREATE NONEDITIONABLE FUNCTION f RETURN NUMBER AS BEGIN RETURN 1; END;",
            "   BEGIN NULL; END;",  # leading whitespace
            "begin null; end;",  # lowercase
        ],
    )
    def test_recognises_plsql_start(self, text: str) -> None:
        assert is_plsql_keyword_start(text) is True

    @pytest.mark.parametrize(
        "text",
        [
            "CREATE TABLE t (id NUMBER)",
            "CREATE VIEW v AS SELECT 1 FROM DUAL",
            "CREATE INDEX idx ON t(id)",
            "CREATE SEQUENCE s",
            "ALTER TABLE t ADD col NUMBER",
            "DROP TABLE t",
            "INSERT INTO t VALUES (1)",
            "SELECT * FROM t",
            "",
            "   ",
        ],
    )
    def test_rejects_non_plsql(self, text: str) -> None:
        assert is_plsql_keyword_start(text) is False


@pytest.mark.unit
class TestWordAtPosition:
    def test_matches_at_start(self):
        assert word_at_position("CREATE TABLE t", 0, "CREATE") is True

    def test_matches_mid_string(self):
        assert word_at_position("CREATE TABLE t", 7, "TABLE") is True

    def test_case_insensitive(self):
        assert word_at_position("create table t", 0, "CREATE") is True
        assert word_at_position("CREATE TABLE t", 0, "create") is True

    def test_partial_word_rejected(self):
        # "REATE" appears at offset 1 but is not a standalone word.
        assert word_at_position("CREATE", 1, "REATE") is False

    def test_out_of_range_rejected(self):
        assert word_at_position("SEL", 0, "SELECT") is False

    def test_boundary_identifier_char(self):
        # Word followed by identifier char — not a boundary.
        assert word_at_position("CREATETABLE t", 0, "CREATE") is False

    def test_oracle_identifier_chars_dollar_and_hash(self):
        # $ and # are identifier chars in Oracle.
        assert word_at_position("CREATE$MORE t", 0, "CREATE") is False
        assert word_at_position("FOO#BAR t", 0, "FOO") is False


@pytest.mark.unit
class TestExtractRegularStatement:
    def test_simple_statement(self):
        stmt, pos = extract_regular_statement("SELECT 1;", 0)
        assert stmt == "SELECT 1;"
        assert pos == len("SELECT 1;")

    def test_semicolon_inside_single_quote_is_part_of_literal(self):
        sql = "INSERT INTO t VALUES ('a;b'); SELECT 1;"
        stmt, pos = extract_regular_statement(sql, 0)
        assert stmt == "INSERT INTO t VALUES ('a;b');"
        assert sql[pos:].strip() == "SELECT 1;"

    def test_doubled_quote_escape_in_literal(self):
        # Oracle: '' inside a string literal is a single quote.
        sql = "INSERT INTO t VALUES ('O''Reilly');"
        stmt, _ = extract_regular_statement(sql, 0)
        assert stmt == sql

    def test_semicolon_inside_double_quoted_identifier(self):
        sql = 'CREATE TABLE "a;b" (id NUMBER);'
        stmt, _ = extract_regular_statement(sql, 0)
        assert stmt == sql

    def test_trailing_slash_is_consumed(self):
        sql = "SELECT 1;\n/\nSELECT 2;"
        _, pos = extract_regular_statement(sql, 0)
        # The position advances past the ``/`` and any trailing whitespace.
        assert sql[pos:].lstrip().startswith("SELECT 2")

    def test_unterminated_statement_returns_to_end(self):
        stmt, pos = extract_regular_statement("SELECT 1", 0)
        assert stmt == "SELECT 1"
        assert pos == len("SELECT 1")


@pytest.mark.unit
class TestIsEmptyOrComment:
    @pytest.mark.parametrize(
        "stmt",
        [
            "",
            "   ",
            "\n\t  \n",
            "-- only line comment",
            "/* only block */",
            "/* multi\n   line */",
            ";",
            "  ;  ",
            "SET SERVEROUTPUT ON",  # SQL*Plus
            "SPOOL output.log",
        ],
    )
    def test_detects_empty(self, stmt: str) -> None:
        assert is_empty_or_comment(stmt) is True

    @pytest.mark.parametrize(
        "stmt",
        [
            "CREATE TABLE t (id NUMBER);",
            "SELECT 1;",
            "-- comment\nCREATE TABLE t (id NUMBER);",
            "/* block */ CREATE TABLE t (id NUMBER);",
        ],
    )
    def test_retains_real_statements(self, stmt: str) -> None:
        assert is_empty_or_comment(stmt) is False


@pytest.mark.unit
class TestExtractNextCompleteStatement:
    def test_empty_input(self):
        stmt, pos = extract_next_complete_statement(
            "", 0, extract_plsql_block=_fake_plsql_extractor
        )
        assert stmt == ""
        assert pos == 0

    def test_start_past_end(self):
        stmt, pos = extract_next_complete_statement(
            "SELECT 1;", 20, extract_plsql_block=_fake_plsql_extractor
        )
        assert stmt == ""
        assert pos == 20

    def test_dispatches_regular_statement(self):
        stmt, _ = extract_next_complete_statement(
            "SELECT 1;", 0, extract_plsql_block=_fake_plsql_extractor
        )
        assert stmt == "SELECT 1;"

    def test_dispatches_plsql_block(self):
        calls: List[Tuple[str, int]] = []

        def extractor(text: str, start_pos: int) -> Tuple[str, int]:
            calls.append((text, start_pos))
            return _fake_plsql_extractor(text, start_pos)

        stmt, _ = extract_next_complete_statement(
            "BEGIN NULL; END;", 0, extract_plsql_block=extractor
        )
        assert calls, "PL/SQL extractor must be invoked for BEGIN…END blocks"
        assert "BEGIN NULL; END;" in stmt


@pytest.mark.unit
class TestSplitStatementsRegex:
    def test_empty_input(self):
        assert split_statements_regex("", extract_plsql_block=_fake_plsql_extractor) == []
        assert split_statements_regex("  \n ", extract_plsql_block=_fake_plsql_extractor) == []

    def test_two_regular_statements(self):
        sql = "CREATE TABLE a (id NUMBER); CREATE TABLE b (id NUMBER);"
        out = split_statements_regex(sql, extract_plsql_block=_fake_plsql_extractor)
        assert len(out) == 2
        assert "CREATE TABLE a" in out[0]
        assert "CREATE TABLE b" in out[1]

    def test_strips_sqlplus_directives(self):
        sql = "SET SERVEROUTPUT ON;\n" "SPOOL output.log;\n" "CREATE TABLE t (id NUMBER);\n"
        out = split_statements_regex(sql, extract_plsql_block=_fake_plsql_extractor)
        assert len(out) == 1
        assert "CREATE TABLE t" in out[0]

    def test_strips_leading_and_trailing_slash(self):
        sql = "/ CREATE TABLE t (id NUMBER); /"
        out = split_statements_regex(sql, extract_plsql_block=_fake_plsql_extractor)
        assert out == ["CREATE TABLE t (id NUMBER);"]

    def test_comments_are_stripped_before_split(self):
        sql = (
            "-- comment one\n"
            "CREATE TABLE t (id NUMBER); /* inline */\n"
            "/* block\n"
            "   comment */\n"
            "CREATE INDEX idx ON t(id);\n"
        )
        out = split_statements_regex(sql, extract_plsql_block=_fake_plsql_extractor)
        assert len(out) == 2
        assert "CREATE TABLE t" in out[0]
        assert "CREATE INDEX idx" in out[1]

    def test_semicolon_inside_string_literal_not_a_terminator(self):
        sql = "INSERT INTO t VALUES ('a;b'); INSERT INTO t VALUES ('c;d');"
        out = split_statements_regex(sql, extract_plsql_block=_fake_plsql_extractor)
        assert len(out) == 2
        assert "'a;b'" in out[0]
        assert "'c;d'" in out[1]
