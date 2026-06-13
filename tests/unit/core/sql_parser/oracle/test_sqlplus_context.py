"""Tests for SqlplusContext extraction and DEFINE substitution."""

import pytest

from db.plugins.oracle.parser.sqlplus_context import (
    SqlplusContext,
    apply_define_substitution,
    extract_sqlplus_context,
)


class TestExtractSqlplusContext:
    def test_defaults_when_empty(self):
        ctx = extract_sqlplus_context("")
        assert ctx.serveroutput is False
        assert ctx.define_on is True
        assert ctx.defines == {}
        assert ctx.prompts == []

    def test_set_serveroutput_on(self):
        ctx = extract_sqlplus_context("SET SERVEROUTPUT ON\nSELECT 1 FROM DUAL;")
        assert ctx.serveroutput is True

    def test_set_serveroutput_off_overrides_on(self):
        ctx = extract_sqlplus_context("SET SERVEROUTPUT ON\nSET SERVEROUTPUT OFF")
        assert ctx.serveroutput is False

    def test_set_define_off(self):
        ctx = extract_sqlplus_context("SET DEFINE OFF\nSELECT 1 FROM DUAL;")
        assert ctx.define_on is False

    def test_set_define_on_explicit(self):
        ctx = extract_sqlplus_context("SET DEFINE OFF\nSET DEFINE ON")
        assert ctx.define_on is True

    def test_define_captures_variable(self):
        ctx = extract_sqlplus_context("DEFINE schema_name = MY_SCHEMA\nSELECT 1 FROM DUAL;")
        assert ctx.defines["SCHEMA_NAME"] == "MY_SCHEMA"

    def test_define_strips_quotes(self):
        ctx = extract_sqlplus_context("DEFINE owner = 'APP_OWNER'")
        assert ctx.defines["OWNER"] == "APP_OWNER"

    def test_define_double_quotes(self):
        ctx = extract_sqlplus_context('DEFINE owner = "APP_OWNER"')
        assert ctx.defines["OWNER"] == "APP_OWNER"

    def test_define_key_uppercased(self):
        ctx = extract_sqlplus_context("define MyVar = somevalue")
        assert "MYVAR" in ctx.defines
        assert ctx.defines["MYVAR"] == "somevalue"

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
        ctx = extract_sqlplus_context("set serveroutput on\ndefine foo = bar\nprompt hello")
        assert ctx.serveroutput is True
        assert ctx.defines.get("FOO") == "bar"
        assert "hello" in ctx.prompts

    def test_multiple_defines(self):
        script = "DEFINE env = PROD\nDEFINE owner = APP\nDEFINE suffix = _V2"
        ctx = extract_sqlplus_context(script)
        assert ctx.defines["ENV"] == "PROD"
        assert ctx.defines["OWNER"] == "APP"
        assert ctx.defines["SUFFIX"] == "_V2"

    def test_prompt_with_only_whitespace_not_captured(self):
        ctx = extract_sqlplus_context("PROMPT   ")
        assert ctx.prompts == []

    def test_block_comment_directive_ignored(self):
        ctx = extract_sqlplus_context("/* SET DEFINE OFF */\nSELECT 1 FROM DUAL;")
        assert ctx.define_on is True

    def test_block_comment_spanning_multiple_lines_ignored(self):
        script = "/*\nSET DEFINE OFF\nSET SERVEROUTPUT ON\n*/\nSELECT 1 FROM DUAL;"
        ctx = extract_sqlplus_context(script)
        assert ctx.define_on is True
        assert ctx.serveroutput is False

    def test_block_comment_inline_partial_line(self):
        # Code before /* is effective; code inside is ignored; code after */ resumes.
        ctx = extract_sqlplus_context("SET SERVEROUTPUT ON /* ignored SET DEFINE OFF */ remaining")
        assert ctx.serveroutput is True
        assert ctx.define_on is True

    def test_block_comment_open_close_same_line_then_directive(self):
        ctx = extract_sqlplus_context("/* comment */ SET DEFINE OFF")
        assert ctx.define_on is False

    def test_unclosed_block_comment_content_visible(self):
        # strip_comments() uses regex requiring both /* and */ — unclosed comments
        # are not matched, so content after /* remains and directives are processed.
        # Unclosed block comments are malformed SQL and not a supported input.
        ctx = extract_sqlplus_context("/* start\nSET DEFINE OFF\nSET SERVEROUTPUT ON")
        assert ctx.define_on is False
        assert ctx.serveroutput is True

    def test_consecutive_block_comments_same_line(self):
        ctx = extract_sqlplus_context("/* a */ /* b */ SET SERVEROUTPUT ON")
        assert ctx.serveroutput is True


class TestApplyDefineSubstitution:
    def test_replaces_single_ampersand_dot_consumed(self):
        # SQL*Plus dot-terminator: the dot after &var is consumed, not kept.
        # &owner.users with OWNER=APP_SCHEMA → APP_SCHEMAusers (not APP_SCHEMA.users)
        ctx = SqlplusContext(defines={"OWNER": "APP_SCHEMA"})
        result = apply_define_substitution("SELECT * FROM &owner.users", ctx)
        assert result == "SELECT * FROM APP_SCHEMAusers"

    def test_double_dot_keeps_one_dot(self):
        # Use double-dot to keep a literal dot: &owner..users → APP_SCHEMA.users
        ctx = SqlplusContext(defines={"OWNER": "APP_SCHEMA"})
        result = apply_define_substitution("SELECT * FROM &owner..users", ctx)
        assert result == "SELECT * FROM APP_SCHEMA.users"

    def test_replaces_double_ampersand_dot_consumed(self):
        ctx = SqlplusContext(defines={"ENV": "PROD"})
        result = apply_define_substitution("CREATE TABLE &&env._log (id NUMBER)", ctx)
        assert result == "CREATE TABLE PROD_log (id NUMBER)"

    def test_unknown_var_left_unchanged(self):
        ctx = SqlplusContext(defines={"FOO": "bar"})
        result = apply_define_substitution("SELECT &unknown FROM DUAL", ctx)
        assert result == "SELECT &unknown FROM DUAL"

    def test_no_substitution_when_define_off(self):
        ctx = SqlplusContext(define_on=False, defines={"OWNER": "APP"})
        result = apply_define_substitution("SELECT * FROM &owner.t", ctx)
        assert result == "SELECT * FROM &owner.t"

    def test_no_substitution_when_no_defines(self):
        ctx = SqlplusContext(define_on=True, defines={})
        result = apply_define_substitution("SELECT * FROM &owner.t", ctx)
        assert result == "SELECT * FROM &owner.t"

    def test_case_insensitive_lookup_dot_consumed(self):
        ctx = SqlplusContext(defines={"SCHEMA": "MYSCHEMA"})
        result = apply_define_substitution("SELECT * FROM &schema.tab", ctx)
        assert result == "SELECT * FROM MYSCHEMAtab"

    def test_multiple_replacements(self):
        ctx = SqlplusContext(defines={"A": "X", "B": "Y"})
        result = apply_define_substitution("&a AND &b", ctx)
        assert result == "X AND Y"
