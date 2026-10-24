"""Tests for SqlplusContext extraction (SET SERVEROUTPUT, PROMPT)."""

import pytest

from dblift.core.exceptions import UnsafeStatementSplitError
from dblift.db.plugins.oracle.parser.sqlplus_context import extract_sqlplus_context


class TestExtractSqlplusContext:
    def test_defaults_when_empty(self):
        ctx = extract_sqlplus_context("")
        assert ctx.serveroutput is False
        assert ctx.prompts == []

    def test_set_serveroutput_on(self):
        ctx = extract_sqlplus_context("SET SERVEROUTPUT ON\nSELECT 1 FROM DUAL;")
        assert ctx.serveroutput is True

    def test_set_serveroutput_off_overrides_on(self):
        ctx = extract_sqlplus_context("SET SERVEROUTPUT ON\nSET SERVEROUTPUT OFF")
        assert ctx.serveroutput is False

    def test_prompt_captured(self):
        ctx = extract_sqlplus_context("PROMPT Starting migration...")
        assert ctx.prompts == ["Starting migration..."]

    def test_remark_silent(self):
        # OBS-01: REM/REMARK are SQL*Plus comment directives (equivalent to --).
        # They must not appear in ctx.prompts (which would echo them as [PROMPT]).
        ctx = extract_sqlplus_context("REMARK this is a comment")
        assert ctx.prompts == []

    def test_rem_short_form_silent(self):
        ctx = extract_sqlplus_context("REM short remark")
        assert ctx.prompts == []

    def test_prompt_and_remark_only_prompt_kept(self):
        ctx = extract_sqlplus_context(
            "REMARK suppressed comment\nPROMPT visible message\nREM another comment"
        )
        assert ctx.prompts == ["visible message"]

    def test_ignores_sql_comment_lines(self):
        ctx = extract_sqlplus_context("-- SET SERVEROUTPUT ON\nSELECT 1 FROM DUAL;")
        assert ctx.serveroutput is False

    def test_case_insensitive_directives(self):
        ctx = extract_sqlplus_context("set serveroutput on\nprompt hello")
        assert ctx.serveroutput is True
        assert "hello" in ctx.prompts

    def test_prompt_with_only_whitespace_not_captured(self):
        ctx = extract_sqlplus_context("PROMPT   ")
        assert ctx.prompts == []

    def test_block_comment_directive_ignored(self):
        ctx = extract_sqlplus_context("/* SET SERVEROUTPUT ON */\nSELECT 1 FROM DUAL;")
        assert ctx.serveroutput is False

    def test_block_comment_spanning_multiple_lines_ignored(self):
        script = "/*\nSET SERVEROUTPUT ON\n*/\nSELECT 1 FROM DUAL;"
        ctx = extract_sqlplus_context(script)
        assert ctx.serveroutput is False

    def test_block_comment_inline_partial_line(self):
        # Code before /* is effective; code inside is ignored; code after */ resumes.
        ctx = extract_sqlplus_context("SET SERVEROUTPUT ON /* ignored SET SERVEROUTPUT OFF */ x")
        assert ctx.serveroutput is True

    def test_block_comment_open_close_same_line_then_directive(self):
        ctx = extract_sqlplus_context("/* comment */ SET SERVEROUTPUT ON")
        assert ctx.serveroutput is True

    def test_unclosed_block_comment_content_visible(self):
        # an unterminated block comment is refused, not swallowed
        with pytest.raises(UnsafeStatementSplitError):
            extract_sqlplus_context("/* start\nSET SERVEROUTPUT ON")

    def test_consecutive_block_comments_same_line(self):
        ctx = extract_sqlplus_context("/* a */ /* b */ SET SERVEROUTPUT ON")
        assert ctx.serveroutput is True
