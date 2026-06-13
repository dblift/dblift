"""Unit tests for `db.plugins.oracle.parser._comments` (Phase-Oracle-02)."""

from __future__ import annotations

import pytest

from db.plugins.oracle.parser._comments import strip_comments, strip_sql_comments


@pytest.mark.unit
class TestStripComments:
    """Line + block comment removal, whitespace preserved."""

    def test_strips_line_comment(self):
        assert strip_comments("SELECT 1; -- trailing\n") == "SELECT 1;"

    def test_strips_leading_line_comment(self):
        assert strip_comments("-- leading\nSELECT 1;") == "SELECT 1;"

    def test_strips_block_comment_inline(self):
        assert strip_comments("SELECT /* inline */ 1;") == "SELECT  1;"

    def test_strips_block_comment_multiline(self):
        sql = "SELECT 1;\n/* block\n   comment */\nSELECT 2;"
        assert strip_comments(sql) == "SELECT 1;\n\nSELECT 2;"

    def test_preserves_horizontal_whitespace(self):
        # strip_comments does NOT collapse runs of spaces — that's strip_sql_comments.
        sql = "SELECT    1;"
        assert strip_comments(sql) == "SELECT    1;"

    def test_returns_stripped(self):
        assert strip_comments("   -- only\n   ") == ""

    def test_empty_input(self):
        assert strip_comments("") == ""

    def test_no_comments_passthrough_modulo_outer_strip(self):
        sql = "CREATE TABLE t (id NUMBER);"
        assert strip_comments(sql) == sql


@pytest.mark.unit
class TestStripSqlComments:
    """Line + block comments + horizontal-whitespace collapse; newlines kept."""

    def test_collapses_runs_of_spaces(self):
        assert strip_sql_comments("SELECT    1;") == "SELECT 1;"

    def test_collapses_tabs(self):
        assert strip_sql_comments("SELECT\t\t1;") == "SELECT 1;"

    def test_preserves_newlines(self):
        sql = "SELECT 1;\nSELECT 2;"
        assert strip_sql_comments(sql) == "SELECT 1;\nSELECT 2;"

    def test_strips_line_comment(self):
        assert strip_sql_comments("SELECT 1; -- tail\n") == "SELECT 1; \n"

    def test_strips_block_comment(self):
        sql = "SELECT /*c*/ 1;"
        assert strip_sql_comments(sql) == "SELECT 1;"

    def test_multiline_with_leading_indent(self):
        # Column alignment collapses into single spaces. Line structure survives.
        sql = "CREATE TABLE t (\n    id NUMBER,\n    name VARCHAR2(50)\n);"
        expected = "CREATE TABLE t (\n id NUMBER,\n name VARCHAR2(50)\n);"
        assert strip_sql_comments(sql) == expected

    def test_does_not_outer_strip(self):
        # Contract differs from strip_comments: leading/trailing whitespace kept.
        sql = "\n   SELECT 1;\n"
        result = strip_sql_comments(sql)
        assert result.startswith("\n")
        assert result.endswith("\n")

    def test_empty_input(self):
        assert strip_sql_comments("") == ""
