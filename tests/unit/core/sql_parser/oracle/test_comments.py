"""Unit tests for `dblift.db.plugins.oracle.parser._comments` (Phase-Oracle-02)."""

from __future__ import annotations

import pytest

from dblift.db.plugins.oracle.parser._comments import strip_comments, strip_sql_comments


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


# Comment markers inside plain and q-quoted literals are data, not comments.
LITERAL_MARKERS = [
    "'--'",
    "'a -- b'",
    "q'[--]'",
    "q'{/* x */}'",
    "'it''s -- ok'",
    "'/*'",
]


@pytest.mark.unit
@pytest.mark.parametrize("literal", LITERAL_MARKERS)
@pytest.mark.parametrize("strip", [strip_comments, strip_sql_comments])
def test_comment_markers_inside_literals_are_kept(strip, literal):
    sql = f"INSERT INTO t VALUES ({literal}); -- gone\nCREATE TABLE u (id NUMBER); /* gone */"
    result = strip(sql)
    assert literal in result
    assert "gone" not in result
    assert "CREATE TABLE u (id NUMBER);" in result


@pytest.mark.unit
def test_line_comment_marker_inside_block_comment():
    assert strip_comments("SELECT /* a -- b */ 1 FROM dual;") == "SELECT  1 FROM dual;"


@pytest.mark.unit
@pytest.mark.parametrize("strip", [strip_comments, strip_sql_comments])
@pytest.mark.parametrize(
    "directive",
    ["PROMPT Creating customer's table", "REM don't run twice", "REMARK it's fine"],
)
def test_apostrophe_in_sqlplus_directive_does_not_open_a_literal(strip, directive):
    sql = (
        f"{directive}\n"
        "CREATE TABLE t (id NUMBER); -- gone\n"
        "CREATE TABLE u (v VARCHAR2(9) DEFAULT '--'); /* gone */\n"
    )
    result = strip(sql)
    assert directive in result
    assert "gone" not in result
    assert "DEFAULT '--');" in result


@pytest.mark.unit
def test_directive_keyword_inside_plsql_block_is_sql_not_a_directive():
    """``EXECUTE IMMEDIATE '...`` inside a block opens a real literal."""
    sql = (
        "PROMPT it's a block\n"
        "BEGIN\n"
        "  NULL;\n"
        "  EXECUTE IMMEDIATE 'CREATE TABLE x (\n"
        "    v VARCHAR2(9) DEFAULT ''--'')';\n"
        "END;\n"
        "/\n"
        "REM don't\n"
        "CREATE TABLE y (id NUMBER); -- gone\n"
    )
    result = strip_comments(sql)
    assert "DEFAULT ''--'')';\nEND;" in result
    assert "REM don't" in result
    assert "gone" not in result
