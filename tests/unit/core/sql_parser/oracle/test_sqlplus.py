"""Unit tests for `db.plugins.oracle.parser._sqlplus` (Phase-Oracle-03)."""

from __future__ import annotations

import pytest

from db.plugins.oracle.parser._sqlplus import is_sqlplus_command, parse_whenever_sqlerror


@pytest.mark.unit
class TestIsSqlplusCommand:
    """Directive recognition — parametrised for readability."""

    @pytest.mark.parametrize(
        "stmt",
        [
            "SHOW ERRORS",
            "SHOW ERROR",
            "SHOW ALL",
            "SHOW USER",
            "SHOW LINESIZE",
            "SET SERVEROUTPUT ON",
            "SET LINESIZE 200",
            "set feedback off",  # case-insensitive
            "SPOOL output.log",
            "SPOOL",
            "WHENEVER OSERROR EXIT",
            "PROMPT hello",
            "PROMPT",
            "ACCEPT name PROMPT 'Name?'",
            "DEFINE x = 1",
            "UNDEFINE x",
            "COLUMN name FORMAT A20",
            "COL id FORMAT 999",
            "TIMING START",
            "CONNECT user/pwd@db",
            "CONN user/pwd",
            "EXIT",
            "QUIT",
            "DESC employees",
            "DESCRIBE employees",
            "HOST ls",
            "!ls",
            "@script.sql",
            "@@script.sql",
            "EXEC proc()",
            "EXECUTE proc()",
            "CLEAR SCREEN",
            "BREAK ON dept",
            "COMPUTE SUM OF sal",
            "TTITLE CENTER 'Report'",
            "BTITLE CENTER 'Page'",
            "REPHEADER PAGE CENTER 'R'",
            "REPFOOTER CENTER 'F'",
            # Added in PR-E (ADR-0012 §Follow-ups): items the tokenizer
            # corpus carried that the regex corpus lacked.
            "DISCONNECT",
            "VARIABLE result NUMBER",
            "PRINT result",
            "PAUSE",
            "PAUSE Press Enter to continue",
            # Directives with a trailing semicolon — common in scripts
            # authored in SQL*Plus-flavoured SQL files. PR-E strips
            # trailing ``;`` before matching.
            "SPOOL output.log;",
            "SET SERVEROUTPUT ON;",
            "EXIT;",
            # Additional SET subcommands and REMARK directives
            "SET DEFINE OFF",
            "SET DEFINE ON",
            "set define off",
            "SET DEFINE &",
            "SET NULL (null)",
            "SET TERMOUT OFF",
            "SET SCAN OFF",
            "REMARK this is a comment",
            "REM short form",
        ],
    )
    def test_recognises_directive(self, stmt: str) -> None:
        assert is_sqlplus_command(stmt), f"{stmt!r} should be a SQL*Plus directive"

    @pytest.mark.parametrize(
        "stmt",
        [
            "CREATE TABLE t (id NUMBER)",
            "INSERT INTO t VALUES (1)",
            "SELECT * FROM t",
            "DROP TABLE t",
            "ALTER TABLE t ADD col NUMBER",
            "BEGIN NULL; END;",
            "DECLARE x NUMBER; BEGIN NULL; END;",
            "",
            "   ",
            # SHOW without a recognised sub-command — not a directive today.
            "SHOW TABLES",
            # SET with an unrecognised option — not a directive today.
            "SET ROLE admin",
            # WHENEVER SQLERROR passes through for positional policy tracking in executor.
            "WHENEVER SQLERROR EXIT",
            "WHENEVER SQLERROR CONTINUE",
        ],
    )
    def test_does_not_match_executable_sql(self, stmt: str) -> None:
        assert not is_sqlplus_command(stmt), f"{stmt!r} must not be flagged"

    def test_handles_leading_whitespace(self) -> None:
        assert is_sqlplus_command("   SPOOL output.log")

    def test_handles_mixed_case(self) -> None:
        assert is_sqlplus_command("SpOoL out.log")


@pytest.mark.unit
class TestParseWheneverSqlerror:
    def test_exit_returns_exit(self) -> None:
        assert parse_whenever_sqlerror("WHENEVER SQLERROR EXIT") == "exit"

    def test_continue_returns_continue(self) -> None:
        assert parse_whenever_sqlerror("WHENEVER SQLERROR CONTINUE") == "continue"

    def test_case_insensitive(self) -> None:
        assert parse_whenever_sqlerror("whenever sqlerror exit") == "exit"
        assert parse_whenever_sqlerror("WHENEVER SQLERROR continue") == "continue"

    def test_leading_whitespace(self) -> None:
        assert parse_whenever_sqlerror("  WHENEVER SQLERROR EXIT") == "exit"

    def test_non_whenever_returns_none(self) -> None:
        assert parse_whenever_sqlerror("SELECT 1 FROM DUAL") is None
        assert parse_whenever_sqlerror("WHENEVER OSERROR EXIT") is None
        assert parse_whenever_sqlerror("") is None
