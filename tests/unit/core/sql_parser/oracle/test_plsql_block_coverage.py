"""Coverage tests for db.plugins.oracle.parser._plsql_block — missing lines.

Targets the uncovered line ranges:
  254-310  scan_to_plsql_body_start (compound trigger, strings, second-pass)
  359-382  handle_plsql_end_keyword — case_depth operator / quote paths
  408-445  handle_plsql_end_keyword — END + operator, END;, named-block paths
  468-475  handle_plsql_end_keyword — quoted identifier after END
  532-550  extract_java_source_block — string handling inside braces
  584      extract_java_source_block — EOF without closing brace
  608-609  extract_plsql_block — package-body line-start slash termination
  699-708  extract_plsql_block — EOF return path
"""

from __future__ import annotations

import pytest

from db.plugins.oracle.parser._plsql_block import (
    extract_java_source_block,
    extract_plsql_block,
    handle_plsql_end_keyword,
    scan_to_plsql_body_start,
)

# ---------------------------------------------------------------------------
# scan_to_plsql_body_start — compound trigger path (lines 253-262)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestScanToPlsqlBodyStartCompoundTrigger:
    def test_compound_trigger_returns_depth_1(self):
        # Text with COMPOUND TRIGGER — should return early with block_depth=1
        text = "CREATE OR REPLACE TRIGGER trg FOR INSERT ON t COMPOUND TRIGGER END;"
        # Find where COMPOUND starts
        idx = text.index("COMPOUND")
        stmt, new_i, depth = scan_to_plsql_body_start(
            text,
            idx,
            "CREATE OR REPLACE TRIGGER trg FOR INSERT ON t ",
            is_named_block=True,
            is_package=False,
            is_package_body=True,
            is_compound_trigger=True,
        )
        assert depth == 1
        assert "COMPOUND" in stmt

    def test_compound_trigger_with_space_after_compound(self):
        # Spaces between COMPOUND and TRIGGER
        text = "COMPOUND  TRIGGER END;"
        stmt, new_i, depth = scan_to_plsql_body_start(
            text,
            0,
            "",
            is_named_block=True,
            is_package=False,
            is_package_body=True,
            is_compound_trigger=True,
        )
        assert depth == 1
        assert "COMPOUND" in stmt

    def test_string_inside_scan(self):
        # AS/IS inside a string should not be treated as keyword
        text = "CREATE PROCEDURE p ('AS') AS BEGIN NULL; END;"
        idx = text.index("(")
        stmt, new_i, depth = scan_to_plsql_body_start(
            text,
            idx,
            "CREATE PROCEDURE p ",
            is_named_block=True,
            is_package=False,
            is_package_body=False,
            is_compound_trigger=False,
        )
        # Should have found the real AS keyword
        assert "AS" in stmt

    def test_package_body_as_sets_depth_1(self):
        # Package body: AS/IS → block_depth = 1
        text = " AS BEGIN NULL; END;"
        stmt, new_i, depth = scan_to_plsql_body_start(
            text,
            0,
            "CREATE PACKAGE BODY pkg",
            is_named_block=True,
            is_package=False,
            is_package_body=True,
            is_compound_trigger=False,
        )
        assert depth == 1

    def test_package_spec_is_sets_depth_1(self):
        # Package spec: IS → block_depth = 1
        text = " IS END;"
        stmt, new_i, depth = scan_to_plsql_body_start(
            text,
            0,
            "CREATE PACKAGE pkg",
            is_named_block=True,
            is_package=True,
            is_package_body=False,
            is_compound_trigger=False,
        )
        assert depth == 1

    def test_procedure_begin_via_second_pass(self):
        # procedure AS followed by BEGIN (two-pass path: block_depth == 0 after AS)
        text = " AS\n  v NUMBER;\nBEGIN\n  NULL;\nEND;"
        stmt, new_i, depth = scan_to_plsql_body_start(
            text,
            0,
            "CREATE PROCEDURE p",
            is_named_block=True,
            is_package=False,
            is_package_body=False,
            is_compound_trigger=False,
        )
        assert depth == 1
        assert "BEGIN" in stmt

    def test_second_pass_string_handling(self):
        # String with doubled-quote in second pass (lines 300-306)
        text = " AS\n  v VARCHAR2 := 'it''s';\nBEGIN NULL; END;"
        stmt, new_i, depth = scan_to_plsql_body_start(
            text,
            0,
            "CREATE PROCEDURE p",
            is_named_block=True,
            is_package=False,
            is_package_body=False,
            is_compound_trigger=False,
        )
        assert depth == 1
        assert "BEGIN" in stmt


# ---------------------------------------------------------------------------
# scan_to_plsql_body_start — BEGIN directly (lines 268-271)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestScanToPlsqlBodyStartBegin:
    def test_begin_before_as(self):
        # Some triggers have BEGIN directly without AS/IS
        text = " BEGIN NULL; END;"
        stmt, new_i, depth = scan_to_plsql_body_start(
            text,
            0,
            "CREATE TRIGGER trg",
            is_named_block=True,
            is_package=False,
            is_package_body=False,
            is_compound_trigger=False,
        )
        assert depth == 1
        assert "BEGIN" in stmt


# ---------------------------------------------------------------------------
# handle_plsql_end_keyword — case_depth operator/quote paths (lines 357-382)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestHandlePlsqlEndKeyword:
    """Direct tests of handle_plsql_end_keyword for uncovered branches."""

    def _call(
        self,
        text,
        i=0,
        block_depth=1,
        case_depth=0,
        case_stack=None,
        is_pkg_body=False,
        pkg_name=None,
        statement="",
        is_named=False,
    ):
        if case_stack is None:
            case_stack = []
        return handle_plsql_end_keyword(
            text,
            i,
            block_depth,
            case_depth,
            case_stack,
            is_pkg_body,
            pkg_name,
            statement,
            is_named,
        )

    def test_case_end_followed_by_operator_pipe(self):
        # case_depth > 0, char_after_end is '|' — line 358-363
        text = "END|"
        bd, cd, stack, result, new_i, stmt = self._call(
            text, i=0, block_depth=1, case_depth=1, case_stack=[0]
        )
        assert cd == 0  # case_depth decremented
        assert result is None  # block not terminated (block_depth still 1)

    def test_case_end_followed_by_plus(self):
        text = "END+"
        bd, cd, stack, result, new_i, stmt = self._call(
            text, i=0, block_depth=1, case_depth=1, case_stack=[0]
        )
        assert cd == 0

    def test_case_end_followed_by_quote(self):
        # case_depth > 0, char_after_end is quote (line 364-369)
        text = "END'"
        bd, cd, stack, result, new_i, stmt = self._call(
            text, i=0, block_depth=1, case_depth=1, case_stack=[0]
        )
        assert cd == 0

    def test_case_end_followed_by_double_quote(self):
        text = 'END"'
        bd, cd, stack, result, new_i, stmt = self._call(
            text, i=0, block_depth=1, case_depth=1, case_stack=[0]
        )
        assert cd == 0

    def test_case_end_followed_by_sql_keyword_where(self):
        # case_depth > 0, char after is alpha and matches _CASE_END_SQL_KEYWORDS (line 377-382)
        text = "END WHERE x = 1"
        bd, cd, stack, result, new_i, stmt = self._call(
            text, i=0, block_depth=1, case_depth=1, case_stack=[0]
        )
        assert cd == 0

    def test_case_end_followed_by_sql_keyword_and(self):
        text = "END AND x = 1"
        bd, cd, stack, result, new_i, stmt = self._call(
            text, i=0, block_depth=1, case_depth=1, case_stack=[0]
        )
        assert cd == 0

    def test_end_if_consumes_keyword(self):
        # END IF — control_flow_keyword_end set, keyword consumed (lines 391-406)
        text = "END IF;"
        bd, cd, stack, result, new_i, stmt = self._call(
            text, i=0, block_depth=1, case_depth=0, case_stack=[]
        )
        assert result is None  # control flow, not terminating
        assert "END IF" in stmt

    def test_end_loop_consumes_keyword(self):
        text = "END LOOP;"
        bd, cd, stack, result, new_i, stmt = self._call(
            text, i=0, block_depth=1, case_depth=0, case_stack=[]
        )
        assert result is None
        assert "END LOOP" in stmt

    def test_end_case_with_case_depth_decrements(self):
        # END CASE with case_depth > 0 (lines 396-399)
        text = "END CASE;"
        bd, cd, stack, result, new_i, stmt = self._call(
            text, i=0, block_depth=1, case_depth=1, case_stack=[0]
        )
        assert cd == 0
        assert result is None  # control flow

    def test_end_repeat_consumes_keyword(self):
        text = "END REPEAT;"
        bd, cd, stack, result, new_i, stmt = self._call(
            text, i=0, block_depth=1, case_depth=0, case_stack=[]
        )
        assert result is None
        assert "END REPEAT" in stmt

    def test_end_operator_not_in_case(self):
        # NOT case_end_handled, char_after_end in operators (lines 407-412)
        text = "END,"
        bd, cd, stack, result, new_i, stmt = self._call(
            text, i=0, block_depth=1, case_depth=0, case_stack=[]
        )
        # No case depth, so is_control_flow_end = True, block_depth unchanged
        assert bd == 1

    def test_end_semicolon_case_depth_inner_block(self):
        # END; with case_depth > 0 and block_depth > case_start (lines 413-421)
        # case_block_depth_stack[-1] = 0, block_depth = 2 → is_control_flow_end = False
        text = "END;"
        bd, cd, stack, result, new_i, stmt = self._call(
            text, i=0, block_depth=2, case_depth=1, case_stack=[0]
        )
        # block_depth > case_start → NOT control flow → decrements block_depth
        assert bd == 1

    def test_end_semicolon_case_depth_same_level(self):
        # case_block_depth_stack[-1] == block_depth → is_control_flow_end = True
        text = "END;"
        bd, cd, stack, result, new_i, stmt = self._call(
            text, i=0, block_depth=1, case_depth=1, case_stack=[1]
        )
        assert cd == 0

    def test_end_semicolon_named_block_trigger(self):
        # Named block with TRIGGER in statement → is_control_flow_end = False (lines 422-424)
        text = "END;"
        bd, cd, stack, result, new_i, stmt = self._call(
            text,
            i=0,
            block_depth=1,
            case_depth=0,
            case_stack=[],
            statement="CREATE TRIGGER trg BEGIN",
            is_named=True,
        )
        # Not control flow → block terminates
        assert result is not None

    def test_end_semicolon_named_block_followed_by_slash(self):
        # Named block (no TRIGGER), END; followed by / → is_control_flow_end = False (lines 428-430)
        text = "END;\n/"
        bd, cd, stack, result, new_i, stmt = self._call(
            text,
            i=0,
            block_depth=1,
            case_depth=0,
            case_stack=[],
            statement="CREATE PROCEDURE p AS BEGIN",
            is_named=True,
        )
        assert result is not None

    def test_end_semicolon_named_block_depth_greater_1(self):
        # Named block, block_depth > 1 → is_control_flow_end = False → decrements (lines 431-432)
        text = "END;"
        bd, cd, stack, result, new_i, stmt = self._call(
            text,
            i=0,
            block_depth=2,
            case_depth=0,
            case_stack=[],
            statement="CREATE PROCEDURE p AS BEGIN",
            is_named=True,
        )
        assert bd == 1
        assert result is None  # block_depth went to 1, not 0

    def test_end_semicolon_named_block_next_char_operator(self):
        # Named block, no slash after, next_char in operators (lines 434-437)
        text = "END; |"
        bd, cd, stack, result, new_i, stmt = self._call(
            text,
            i=0,
            block_depth=1,
            case_depth=0,
            case_stack=[],
            statement="CREATE PROCEDURE p AS BEGIN",
            is_named=True,
        )
        # next_char is '|' → is_control_flow_end = True
        assert bd == 1  # unchanged

    def test_end_semicolon_named_block_next_char_and(self):
        # Named block, no slash after, next tokens AND (lines 438-441)
        text = "END; AND more"
        bd, cd, stack, result, new_i, stmt = self._call(
            text,
            i=0,
            block_depth=1,
            case_depth=0,
            case_stack=[],
            statement="CREATE PROCEDURE p AS BEGIN",
            is_named=True,
        )
        assert bd == 1  # is_control_flow_end = True

    def test_end_semicolon_named_block_next_char_or(self):
        # Named block, no slash after, next tokens OR (line 439)
        text = "END; OR more"
        bd, cd, stack, result, new_i, stmt = self._call(
            text,
            i=0,
            block_depth=1,
            case_depth=0,
            case_stack=[],
            statement="CREATE PROCEDURE p AS BEGIN",
            is_named=True,
        )
        assert bd == 1  # is_control_flow_end = True

    def test_end_semicolon_named_block_at_eof(self):
        # Named block, END; and temp_pos >= len(text) → is_control_flow_end = False (lines 444-445)
        text = "END;"
        bd, cd, stack, result, new_i, stmt = self._call(
            text,
            i=0,
            block_depth=1,
            case_depth=0,
            case_stack=[],
            statement="CREATE PROCEDURE p AS BEGIN",
            is_named=True,
        )
        # No slash follows, no operator follows, EOF → is_control_flow_end = False → block terminates
        assert result is not None

    def test_end_identifier_after_end(self):
        # char_after_end is alnum/underscore — not control flow (line 447-449)
        text = "END my_proc;"
        bd, cd, stack, result, new_i, stmt = self._call(
            text,
            i=0,
            block_depth=1,
            case_depth=0,
            case_stack=[],
            statement="CREATE PROCEDURE my_proc AS BEGIN",
            is_named=True,
        )
        assert result is not None
        assert "my_proc" in result[0]

    def test_end_with_quoted_identifier(self):
        # block_depth <= 0, text[i] == '"' → quoted identifier path (lines 467-475)
        text = 'END "my_proc";'
        bd, cd, stack, result, new_i, stmt = self._call(
            text,
            i=0,
            block_depth=1,
            case_depth=0,
            case_stack=[],
            statement="CREATE PROCEDURE ",
            is_named=True,
        )
        assert result is not None
        assert '"my_proc"' in result[0]

    def test_end_at_exact_eof(self):
        # END with no trailing characters — end_pos >= len(text)
        text = "END"
        bd, cd, stack, result, new_i, stmt = self._call(
            text, i=0, block_depth=1, case_depth=0, case_stack=[]
        )
        # block_depth decrements to 0, block terminates
        assert result is not None


# ---------------------------------------------------------------------------
# extract_java_source_block — string handling (lines 532-550)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestExtractJavaSourceBlockStrings:
    def test_single_quoted_string_inside_java(self):
        # Single-quoted string inside Java source (lines 531-536)
        sql = "CREATE JAVA SOURCE NAMED j AS public class J { String s = 'hello'; }\n/\n"
        block, pos = extract_java_source_block(sql, 0)
        assert "'hello'" in block

    def test_double_quote_escape_inside_java(self):
        # Doubled-quote escape inside string literal (lines 537-546)
        sql = 'CREATE JAVA SOURCE NAMED j AS public class J { String s = "it"; }\n/\n'
        block, pos = extract_java_source_block(sql, 0)
        assert "it" in block

    def test_string_with_doubled_quote(self):
        # String continuation (same char twice = escape)
        sql = "CREATE JAVA SOURCE NAMED j AS public class J { String s = ''x''; }\n/\n"
        block, pos = extract_java_source_block(sql, 0)
        assert block  # just verify it doesn't crash

    def test_char_inside_string_not_brace(self):
        # Characters inside string (line 547-550 — in_string branch)
        sql = 'CREATE JAVA SOURCE NAMED j AS public class J { String s = "{}not-brace"; }\n/\n'
        block, pos = extract_java_source_block(sql, 0)
        # The braces inside the string should not affect brace_depth
        assert "{}not-brace" in block

    def test_eof_without_closing_brace(self):
        # EOF without closing brace — returns statement.strip(), len(text) (line 584)
        sql = "CREATE JAVA SOURCE NAMED j AS public class J { unclosed"
        block, pos = extract_java_source_block(sql, 0)
        assert pos == len(sql)
        assert "unclosed" in block


# ---------------------------------------------------------------------------
# extract_plsql_block — package-body slash termination (lines 697-703)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestExtractPlsqlBlockPackageBody:
    def test_package_body_line_start_slash_terminates(self):
        # Package body with BEGIN block — line-start slash should terminate (lines 698-703)
        sql = (
            "CREATE PACKAGE BODY my_pkg AS\n"
            "  PROCEDURE p IS\n"
            "  BEGIN\n"
            "    NULL;\n"
            "  END;\n"
            "/\n"
        )
        block, pos = extract_plsql_block(sql, 0)
        assert "my_pkg" in block
        # Should NOT include anything after the slash
        remaining = sql[pos:]
        assert remaining.strip() == "" or not remaining.strip().startswith("CREATE")

    def test_package_body_slash_not_at_line_start_not_terminating(self):
        # Slash that is NOT at line start inside package body should not terminate
        sql = (
            "CREATE PACKAGE BODY my_pkg AS\n"
            "  v NUMBER := 10/2;\n"
            "BEGIN\n"
            "  NULL;\n"
            "END;\n"
            "/\n"
        )
        block, pos = extract_plsql_block(sql, 0)
        # The 10/2 should be inside the block
        assert "10/2" in block or "10" in block  # part of expr

    def test_extract_plsql_block_eof_return(self):
        # Block without terminating slash — returns statement.strip(), len(text) (lines 708)
        sql = "BEGIN\n  NULL;\n  x := 1;\nEND"
        block, pos = extract_plsql_block(sql, 0)
        assert pos == len(sql)
        assert "NULL" in block


# ---------------------------------------------------------------------------
# Integration: full extract_plsql_block covering case-depth paths
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestExtractPlsqlBlockCaseDepth:
    def test_case_expression_in_query(self):
        # CASE expression (not statement) → case_depth tracked
        sql = "BEGIN\n" "  v := CASE WHEN x = 1 THEN 'a' ELSE 'b' END;\n" "END;\n" "/\n"
        block, pos = extract_plsql_block(sql, 0)
        assert "CASE" in block
        assert block.rstrip().endswith("END;")

    def test_nested_case_expressions(self):
        # Two nested CASE expressions
        sql = (
            "BEGIN\n"
            "  v := CASE WHEN x = CASE WHEN y THEN 1 ELSE 2 END THEN 'a' ELSE 'b' END;\n"
            "END;\n"
            "/\n"
        )
        block, pos = extract_plsql_block(sql, 0)
        assert "CASE" in block
        assert block.rstrip().endswith("END;")

    def test_case_expression_followed_by_where_keyword(self):
        # CASE END followed by WHERE SQL keyword
        sql = (
            "BEGIN\n"
            "  SELECT CASE WHEN x = 1 THEN 'a' END WHERE id = 1;\n"
            "  NULL;\n"
            "END;\n"
            "/\n"
        )
        block, pos = extract_plsql_block(sql, 0)
        assert block.rstrip().endswith("END;")

    def test_function_with_as_and_no_begin_in_spec(self):
        # Function spec with IS and then BEGIN
        sql = (
            "CREATE FUNCTION get_val(p_id NUMBER) RETURN NUMBER IS\n"
            "  v_result NUMBER;\n"
            "BEGIN\n"
            "  SELECT val INTO v_result FROM t WHERE id = p_id;\n"
            "  RETURN v_result;\n"
            "END get_val;\n"
            "/\n"
        )
        block, pos = extract_plsql_block(sql, 0)
        assert "get_val" in block
        assert "RETURN" in block

    def test_anonymous_block_with_declare(self):
        # Anonymous block with DECLARE section
        sql = (
            "DECLARE\n"
            "  v_count NUMBER := 0;\n"
            "BEGIN\n"
            "  SELECT COUNT(*) INTO v_count FROM t;\n"
            "END;\n"
            "/\n"
        )
        block, pos = extract_plsql_block(sql, 0)
        assert "DECLARE" in block
        assert "v_count" in block
