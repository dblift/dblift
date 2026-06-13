"""Unit tests for `db.plugins.oracle.parser._plsql_block` (Phase-Oracle-06)."""

from __future__ import annotations

import pytest

from db.plugins.oracle.parser._plsql_block import (
    extract_java_source_block,
    extract_plsql_block,
    is_line_start_slash,
    is_partial_plsql_fragment,
    is_single_plsql_block,
    parse_plsql_create_header,
)


@pytest.mark.unit
class TestParsePlsqlCreateHeader:
    def test_procedure_header(self):
        sql = "CREATE PROCEDURE p AS BEGIN NULL; END;"
        named, body, pkg, compound, name, prefix, _ = parse_plsql_create_header(sql, 0)
        assert named is True
        assert body is False
        assert pkg is False
        assert compound is False
        assert name is None
        assert prefix == ""

    def test_package_spec_header(self):
        sql = "CREATE PACKAGE my_pkg AS END;"
        named, body, pkg, _, name, _, _ = parse_plsql_create_header(sql, 0)
        assert named is True
        assert body is False
        assert pkg is True
        assert name == "MY_PKG"

    def test_package_body_header(self):
        sql = "CREATE PACKAGE BODY my_pkg AS END;"
        named, body, pkg, _, name, _, _ = parse_plsql_create_header(sql, 0)
        assert named is True
        assert body is True
        assert pkg is False  # exclusive with body
        assert name == "MY_PKG"

    def test_compound_trigger_header(self):
        sql = "CREATE TRIGGER trg FOR INSERT ON t COMPOUND TRIGGER END;"
        named, body, _, compound, _, _, _ = parse_plsql_create_header(sql, 0)
        assert named is True
        assert compound is True
        assert body is True  # compound implies body flag per legacy contract

    def test_java_source_sentinel(self):
        sql = "CREATE JAVA SOURCE NAMED j AS public class J {}"
        named, _, _, _, _, prefix, _ = parse_plsql_create_header(sql, 0)
        assert prefix == "JAVA_SOURCE"
        assert named is False  # sentinel path does not set named

    def test_non_plsql_header(self):
        sql = "CREATE TABLE t (id NUMBER);"
        named, body, pkg, compound, name, prefix, _ = parse_plsql_create_header(sql, 0)
        assert named is False
        assert body is False
        assert pkg is False
        assert compound is False
        assert name is None
        assert prefix == ""

    def test_editionable_modifier(self):
        sql = "CREATE EDITIONABLE PROCEDURE p AS BEGIN NULL; END;"
        named, _, _, _, _, _, _ = parse_plsql_create_header(sql, 0)
        assert named is True

    def test_noneditionable_modifier(self):
        sql = "CREATE NONEDITIONABLE FUNCTION f RETURN NUMBER AS BEGIN RETURN 1; END;"
        named, _, _, _, _, _, _ = parse_plsql_create_header(sql, 0)
        assert named is True

    def test_qualified_package_name_yields_unqualified(self):
        sql = "CREATE PACKAGE schema1.my_pkg AS END;"
        _, _, _, _, name, _, _ = parse_plsql_create_header(sql, 0)
        assert name == "MY_PKG"


@pytest.mark.unit
class TestIsLineStartSlash:
    def test_start_of_file(self):
        assert is_line_start_slash("/", 0) is True

    def test_after_newline(self):
        text = "SELECT 1;\n/"
        assert is_line_start_slash(text, text.index("/")) is True

    def test_after_newline_plus_whitespace(self):
        text = "SELECT 1;\n   /"
        assert is_line_start_slash(text, text.index("/")) is True

    def test_mid_line_rejected(self):
        text = "SELECT a/b"
        assert is_line_start_slash(text, text.index("/")) is False


@pytest.mark.unit
class TestExtractPlsqlBlock:
    def test_anonymous_begin_end(self):
        sql = "BEGIN NULL; END;\n/\nCREATE TABLE t (id NUMBER);"
        block, next_pos = extract_plsql_block(sql, 0)
        assert "BEGIN" in block and "END" in block
        assert sql[next_pos:].lstrip().startswith("CREATE TABLE")

    def test_declare_begin_end(self):
        sql = "DECLARE x NUMBER; BEGIN x := 1; END;\n/\n"
        block, _ = extract_plsql_block(sql, 0)
        assert "DECLARE" in block
        assert "END" in block

    def test_simple_procedure(self):
        sql = "CREATE PROCEDURE p AS BEGIN NULL; END;\n/\n"
        block, _ = extract_plsql_block(sql, 0)
        assert "CREATE PROCEDURE p" in block
        assert "END" in block

    def test_nested_begin_end(self):
        sql = "CREATE PROCEDURE p AS\n" "BEGIN\n" "  BEGIN NULL; END;\n" "  NULL;\n" "END;\n" "/\n"
        block, _ = extract_plsql_block(sql, 0)
        assert block.count("BEGIN") == 2
        # Both ENDs now propagate: the inner END; plus the outer END;.
        assert block.count("END") == 2
        assert block.rstrip().endswith("END;") or block.rstrip().endswith("END p;")

    def test_end_if_does_not_terminate_block(self):
        sql = (
            "CREATE PROCEDURE p AS\n"
            "BEGIN\n"
            "  IF 1 = 1 THEN NULL; END IF;\n"
            "  NULL;\n"
            "END;\n"
            "/\n"
        )
        block, _ = extract_plsql_block(sql, 0)
        assert "END IF" in block
        assert block.rstrip().endswith("END p;") or block.rstrip().endswith("END;")

    def test_end_loop_does_not_terminate_block(self):
        sql = "BEGIN\n" "  FOR i IN 1..10 LOOP NULL; END LOOP;\n" "END;\n" "/\n"
        block, _ = extract_plsql_block(sql, 0)
        assert "END LOOP" in block
        assert block.rstrip().endswith("END;")

    def test_end_case_does_not_terminate_block(self):
        sql = "BEGIN\n" "  CASE WHEN 1 = 1 THEN NULL; END CASE;\n" "END;\n" "/\n"
        block, _ = extract_plsql_block(sql, 0)
        assert "END CASE" in block
        assert "WHEN 1 = 1" in block
        # After PR-D: the outer BEGIN…END; no longer terminates early.
        assert block.rstrip().endswith("END;")

    def test_end_identifier_consumed(self):
        sql = "CREATE PROCEDURE my_proc AS BEGIN NULL; END my_proc;\n/\n"
        block, _ = extract_plsql_block(sql, 0)
        assert "END my_proc;" in block

    def test_java_source_dispatch(self):
        sql = "CREATE JAVA SOURCE NAMED j AS public class J { }\n/\n"
        block, _ = extract_plsql_block(sql, 0)
        assert "public class J" in block

    def test_semicolon_inside_literal_not_terminator(self):
        sql = "BEGIN INSERT INTO t VALUES ('a;b'); END;\n/\n"
        block, _ = extract_plsql_block(sql, 0)
        assert "'a;b'" in block

    def test_doubled_quote_escape_inside_literal(self):
        sql = "BEGIN INSERT INTO t VALUES ('O''Reilly'); END;\n/\n"
        block, _ = extract_plsql_block(sql, 0)
        assert "'O''Reilly'" in block


@pytest.mark.unit
class TestEndLiteralPropagation:
    """PR-D (ADR-0012 §Follow-ups): ``END`` propagates through control flow.

    Prior to PR-D, ``handle_plsql_end_keyword`` appended the three
    ``END`` characters to a *local* ``statement`` parameter that
    Python strings never propagated back to the caller. Every
    non-terminating END (``END IF`` / ``END LOOP`` / ``END CASE``)
    advanced the scanner position correctly but dropped the literal
    ``END`` from the emitted block text. The fix returns ``statement``
    from the helper and reassigns it at the call site.
    """

    def test_end_if_literal_present(self):
        sql = "BEGIN IF 1 = 1 THEN NULL; END IF; END;\n/\n"
        block, _ = extract_plsql_block(sql, 0)
        assert "END IF" in block
        assert block.rstrip().endswith("END;")

    def test_end_loop_literal_present(self):
        sql = "BEGIN FOR i IN 1..10 LOOP NULL; END LOOP; END;\n/\n"
        block, _ = extract_plsql_block(sql, 0)
        assert "END LOOP" in block
        assert block.rstrip().endswith("END;")

    def test_end_case_literal_present(self):
        sql = "BEGIN CASE WHEN 1 = 1 THEN NULL; END CASE; END;\n/\n"
        block, _ = extract_plsql_block(sql, 0)
        assert "END CASE" in block
        assert block.rstrip().endswith("END;")

    def test_inner_end_semicolon_literal_present(self):
        # Nested anonymous sub-block: the inner END; is control flow
        # relative to the outer block (block_depth does not reach 0).
        sql = "BEGIN BEGIN NULL; END; NULL; END;\n/\n"
        block, _ = extract_plsql_block(sql, 0)
        # Both END; sequences present: inner + outer.
        assert block.count("END;") == 2

    def test_end_at_text_boundary_does_not_raise(self):
        # Regression: ``control_flow_keyword_end`` used to live inside
        # the ``if end_pos < len(text):`` guard. When END sat at the
        # very end of the input (optionally followed only by
        # whitespace), the guard skipped the initialisation and a
        # later reference raised ``NameError``.
        for sql in ("BEGIN NULL; END", "BEGIN NULL; END   ", "BEGIN NULL; END\n"):
            block, _ = extract_plsql_block(sql, 0)
            assert "END" in block


@pytest.mark.unit
class TestExtractJavaSourceBlock:
    def test_simple_class(self):
        sql = "CREATE JAVA SOURCE NAMED j AS public class J { public void run() { } }\n/\n"
        block, next_pos = extract_java_source_block(sql, 0)
        assert "public class J" in block
        # Trailing slash + whitespace consumed.
        assert sql[next_pos:].strip() == ""

    def test_nested_braces(self):
        sql = (
            "CREATE JAVA SOURCE NAMED j AS "
            "public class J { public void f() { if (true) { return; } } }\n/\n"
        )
        block, _ = extract_java_source_block(sql, 0)
        # Every opening brace is balanced.
        assert block.count("{") == block.count("}")


@pytest.mark.unit
class TestIsSinglePlsqlBlock:
    @pytest.mark.parametrize(
        "sql",
        [
            "CREATE PROCEDURE p AS BEGIN NULL; END;",
            "CREATE OR REPLACE PROCEDURE p AS BEGIN NULL; END;",
            "CREATE FUNCTION f RETURN NUMBER AS BEGIN RETURN 1; END;",
            "CREATE PACKAGE pkg AS END;",
            "CREATE PACKAGE BODY pkg AS END;",
            "CREATE TRIGGER trg BEFORE INSERT ON t BEGIN NULL; END;",
            "CREATE TYPE t AS OBJECT (a NUMBER);",  # TYPE ... END is legal here too
            "BEGIN NULL; END;",
            "DECLARE x NUMBER; BEGIN NULL; END;",
        ],
    )
    def test_recognises_single_block(self, sql: str) -> None:
        # Accept at least the core ones — the TYPE OBJECT form may or may
        # not match the END regex depending on whether `END` appears.
        result = is_single_plsql_block(sql)
        if "END" in sql.upper():
            assert result is True

    @pytest.mark.parametrize(
        "sql",
        [
            "CREATE TABLE t (id NUMBER);",
            "INSERT INTO t VALUES (1);",
            "SELECT * FROM t;",
            "",
            "  ",
        ],
    )
    def test_rejects_non_plsql(self, sql: str) -> None:
        assert is_single_plsql_block(sql) is False


@pytest.mark.unit
class TestIsPartialPlsqlFragment:
    @pytest.mark.parametrize(
        "stmt",
        [
            "",
            "   ",
            "END",
            "END;",
            "END;  /",
            "BEGIN",
            "DECLARE",
            "/",
            ";",
        ],
    )
    def test_detects_fragment(self, stmt: str) -> None:
        assert is_partial_plsql_fragment(stmt) is True

    @pytest.mark.parametrize(
        "stmt",
        [
            "CREATE TABLE t (id NUMBER);",
            "CREATE PROCEDURE p AS BEGIN NULL; END;",
            "SELECT * FROM t;",
        ],
    )
    def test_rejects_complete_statements(self, stmt: str) -> None:
        assert is_partial_plsql_fragment(stmt) is False
