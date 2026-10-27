"""Client directive lines are recorded or refused, never dropped (docs/sql-parsing/oracle.md section 6)."""

import logging

import pytest

from dblift.core.exceptions import UnsafeStatementSplitError, UnsupportedMetaCommandError
from dblift.core.sql_parser.client_directives import classify_directive
from dblift.core.sql_parser.lexical_engine import LexicalEngine
from dblift.core.sql_parser.lexical_spec import DirectiveAction
from dblift.core.sql_parser.lexical_tokenizer import LexicalTokenizer
from dblift.core.sql_parser.statement import Statement
from dblift.core.sql_parser.tokens import TokenType
from dblift.db.plugins.oracle.parser._sqlplus import SQLPLUS_DIRECTIVES
from dblift.db.plugins.oracle.parser.lexical_spec import ORACLE_SPEC

RULES = ORACLE_SPEC.client_script
assert RULES is not None
ENGINE_LOGGER = "dblift.core.sql_parser.lexical_engine"
INVALID_PREFIX_COMMANDS = [
    "EXIT",
    "QUIT",
    "PROMPT PREFIX_OK",
    "REM PREFIX_OK",
    "SET FEEDBACK OFF",
    "WHENEVER SQLERROR EXIT",
    "@missing.sql",
    "EXEC dbms_output.put_line('PREFIX_OK')",
]


def records(script):
    return [
        (r.text, r.line, r.terminator, r.kind) for r in LexicalEngine(ORACLE_SPEC).split(script)
    ]


def strings(script):
    return LexicalEngine(ORACLE_SPEC).split_statements(script)


def kinds(script):
    return [r.kind for r in LexicalEngine(ORACLE_SPEC).split(script)]


def directive(text, line):
    return (text, line, None, "directive")


def test_row_14_directives_are_records_between_the_statements():
    script = (
        "PROMPT Creating customer's table\nCREATE TABLE a (x NUMBER);\n"
        "REM don't run twice\nCREATE TABLE b (y NUMBER);"
    )
    assert records(script) == [
        directive("PROMPT Creating customer's table", 1),
        ("CREATE TABLE a (x NUMBER)", 2, ";", "sql"),
        directive("REM don't run twice", 3),
        ("CREATE TABLE b (y NUMBER)", 4, ";", "sql"),
    ]
    assert strings(script) == ["CREATE TABLE a (x NUMBER);", "CREATE TABLE b (y NUMBER);"]


def test_row_17_exit_stops_the_script_and_warns_naming_the_first_ignored_line(caplog):
    script = "SELECT 1 FROM dual;\nEXIT\nSELECT 2 FROM dual;"
    with caplog.at_level(logging.WARNING, logger=ENGINE_LOGGER):
        found = records(script)
    assert found == [("SELECT 1 FROM dual", 1, ";", "sql"), directive("EXIT", 2)]
    assert [(r.name, r.getMessage()) for r in caplog.records] == [
        (
            ENGINE_LOGGER,
            "Content after EXIT on line 2 ignored, as SQL*Plus does not run it "
            "(first ignored line: 3)",
        )
    ]
    assert strings(script) == ["SELECT 1 FROM dual;"]


@pytest.mark.parametrize(
    "script",
    [
        "SELECT 1 FROM dual;\nQUIT\n-- done\n",
        "SELECT 1 FROM dual;\nEXIT\nPROMPT bye\n",
        "SELECT 1 FROM dual;\nEXIT",
    ],
)
def test_exit_with_nothing_to_ignore_does_not_warn(script, caplog):
    with caplog.at_level(logging.WARNING, logger=ENGINE_LOGGER):
        LexicalEngine(ORACLE_SPEC).split(script)
    assert not caplog.records


def test_row_17a_exit_ignores_a_malformed_tail():
    assert strings("SELECT 1 FROM dual;\nEXIT\nSELECT 'unterminated") == ["SELECT 1 FROM dual;"]
    assert strings("SELECT 1 FROM dual;\nEXIT\n@@never.sql\n") == ["SELECT 1 FROM dual;"]


@pytest.mark.parametrize("prefix", ["\u00a0", "\x1c"])
@pytest.mark.parametrize("command", INVALID_PREFIX_COMMANDS)
def test_invalid_client_blank_prefix_is_refused_not_dropped(prefix, command):
    script = f"{prefix}{command}\nSELECT 'FOLLOWUP_OK' AS MARKER FROM dual;\n"

    with pytest.raises(UnsafeStatementSplitError) as raised:
        strings(script)
    assert f"U+{ord(prefix):04X} at line 1, column 1" in str(raised.value)


@pytest.mark.parametrize("prefix", ["\u00a0", "\x1c"])
@pytest.mark.parametrize("command", INVALID_PREFIX_COMMANDS)
def test_invalid_client_blank_prefix_is_not_a_directive_token(prefix, command):
    script = f"{prefix}{command}\nSELECT 'FOLLOWUP_OK' AS MARKER FROM dual;\n"

    first_line_tokens = [
        token for token in LexicalTokenizer(script, spec=ORACLE_SPEC).tokenize() if token.line == 1
    ]
    assert first_line_tokens
    assert all(token.type is not TokenType.DIRECTIVE for token in first_line_tokens)


@pytest.mark.parametrize("prefix", ["\u00a0", "\x1c"])
@pytest.mark.parametrize("before", ["", "SELECT 'FIRST_OK' AS MARKER FROM dual;\n"])
def test_invalid_client_blank_prefix_does_not_make_slash_a_terminator(prefix, before):
    script = f"{before}{prefix}/\nSELECT 'FOLLOWUP_OK' AS MARKER FROM dual;"
    line = 2 if before else 1
    with pytest.raises(UnsafeStatementSplitError) as raised:
        strings(script)
    assert f"U+{ord(prefix):04X} at line {line}, column 1" in str(raised.value)


@pytest.mark.parametrize("prefix", ["\u00a0", "\x1c"])
def test_invalid_client_blank_prefix_slash_is_not_a_delimiter_token(prefix):
    tokens = LexicalTokenizer(f"{prefix}/\n", spec=ORACLE_SPEC).tokenize()
    slash = next(token for token in tokens if token.text == "/")
    assert slash.type is TokenType.SYMBOL


@pytest.mark.parametrize("prefix", ["\u00a0", "\x1c"])
def test_invalid_client_blank_prefix_slash_does_not_end_a_plsql_unit(prefix):
    script = (
        "BEGIN dbms_output.put_line('BLOCK_OK'); END;\n"
        f"{prefix}/\nSELECT 'FOLLOWUP_OK' AS MARKER FROM dual;"
    )
    with pytest.raises(UnsafeStatementSplitError, match="PL/SQL unit"):
        strings(script)


@pytest.mark.parametrize("suffix", ["\u00a0", "\x1c"])
@pytest.mark.parametrize("before", ["", "SELECT 'FIRST_OK' AS MARKER FROM dual;\n"])
def test_invalid_client_blank_after_slash_is_a_command_with_a_clear_buffer(suffix, before):
    script = f"{before}/{suffix}\nSELECT 'FOLLOWUP_OK' AS MARKER FROM dual;"
    with pytest.raises(UnsafeStatementSplitError) as raised:
        strings(script)
    assert ("re-execute the previous statement" if before else "run an empty buffer") in str(
        raised.value
    )


@pytest.mark.parametrize("suffix", ["\u00a0", "\x1c"])
def test_invalid_client_blank_after_slash_does_not_end_an_open_plsql_unit(suffix):
    script = (
        "BEGIN dbms_output.put_line('BLOCK_OK'); END;\n"
        f"/{suffix}\nSELECT 'FOLLOWUP_OK' AS MARKER FROM dual;"
    )
    with pytest.raises(UnsafeStatementSplitError, match="PL/SQL unit"):
        strings(script)


@pytest.mark.parametrize("prefix", [" ", "\t", "\u3000"])
def test_measured_client_blanks_still_make_slash_a_terminator(prefix):
    script = f"BEGIN dbms_output.put_line('BLOCK_OK'); END;\n{prefix}/\n"
    assert strings(script) == ["BEGIN dbms_output.put_line('BLOCK_OK'); END;"]


@pytest.mark.parametrize("prefix", [" ", "\t", "\u3000"])
def test_measured_client_blanks_still_allow_exit(prefix):
    assert strings(f"{prefix}EXIT\nSELECT 'FOLLOWUP_OK' AS MARKER FROM dual;") == []


def test_nonbreaking_space_in_quoted_or_commented_text_does_not_act_as_exit():
    assert strings("SELECT '\u00a0EXIT' AS marker FROM dual;") == [
        "SELECT '\u00a0EXIT' AS marker FROM dual;"
    ]
    assert strings("/* \u00a0EXIT */\nSELECT 'FOLLOWUP_OK' AS MARKER FROM dual;") == [
        "SELECT 'FOLLOWUP_OK' AS MARKER FROM dual;"
    ]


@pytest.mark.parametrize("prefix", ["\u00a0", "\x1c"])
def test_invalid_client_blank_prefix_after_block_comment_is_refused(prefix):
    with pytest.raises(UnsafeStatementSplitError) as raised:
        strings(f"/* note */{prefix}EXIT\nSELECT 'FOLLOWUP_OK' FROM dual;")
    assert f"U+{ord(prefix):04X} at line 1, column 11" in str(raised.value)


def test_row_18_include_is_refused_naming_the_directive_and_line():
    with pytest.raises(UnsupportedMetaCommandError) as raised:
        strings("@@setup.sql\nSELECT 1 FROM dual;")
    assert (
        str(raised.value) == "Unsupported SQL*Plus directive '@@' at line 1; dblift does not run it"
    )


@pytest.mark.parametrize(
    "line, name",
    [
        ("@setup.sql", "@"),
        ("START setup.sql", "START"),
        ("STA setup.sql", "START"),
        ("HOST ls", "HOST"),
        ("! ls", "!"),
        ("ACCEPT x", "ACCEPT"),
        ("PAUSE", "PAUSE"),
        ("CONNECT scott/tiger", "CONNECT"),
        ("CONN scott/tiger", "CONNECT"),
        ("DISCONNECT", "DISCONNECT"),
        ("PASSWORD", "PASSWORD"),
        ("SET SQLTERMINATOR OFF", "SET SQLTERMINATOR"),
        ("SET SQLT '!'", "SET SQLTERMINATOR"),
        ("SET BLOCKTERMINATOR '!'", "SET BLOCKTERMINATOR"),
        ("SET SQLBLANKLINES ON", "SET SQLBLANKLINES"),
        ("SET SQLPREFIX '#'", "SET SQLPREFIX"),
        ("SET CMDSEP '+'", "SET CMDSEP"),
        ("SET ESCAPE ON", "SET ESCAPE"),
        ("SET ESC '\\'", "SET ESCAPE"),
        ("SET CONCAT OFF", "SET CONCAT"),
        ("SET CON '#'", "SET CONCAT"),
    ],
)
def test_interactive_and_lexer_changing_directives_are_refused(line, name):
    with pytest.raises(UnsupportedMetaCommandError, match=rf"{name!r}.*line 2"):
        strings(f"SELECT 1 FROM dual;\n{line}\nSELECT 2 FROM dual;")


def test_row_19_directive_after_a_semicolon_on_the_same_line_is_refused():
    with pytest.raises(UnsupportedMetaCommandError) as raised:
        strings("SELECT 1 FROM dual; PROMPT x\nSELECT 2 FROM dual;")
    assert str(raised.value) == (
        "SQL*Plus directive 'PROMPT' follows a ';' on line 1: SQL*Plus rejects the line "
        "(ORA-03405); put it on its own line"
    )


def test_a_non_directive_after_a_semicolon_is_still_the_text_after_terminator_refusal():
    with pytest.raises(UnsafeStatementSplitError, match="ORA-03405"):
        strings("SELECT 1 FROM dual; SELECT 2 FROM dual;")


def test_row_23_whenever_sqlerror_is_recorded_and_still_reaches_execution():
    script = "WHENEVER SQLERROR EXIT FAILURE\nCREATE TABLE t (id NUMBER);"
    assert records(script) == [
        directive("WHENEVER SQLERROR EXIT FAILURE", 1),
        ("CREATE TABLE t (id NUMBER)", 2, ";", "sql"),
    ]
    assert strings(script) == ["WHENEVER SQLERROR EXIT FAILURE;", "CREATE TABLE t (id NUMBER);"]


def test_whenever_sqlerror_already_terminated_is_not_terminated_twice():
    assert strings("WHENEVER SQLERROR CONTINUE;\nSELECT 1 FROM dual;")[0] == (
        "WHENEVER SQLERROR CONTINUE;"
    )


def test_whenever_sqlerror_with_an_unknown_action_is_refused():
    with pytest.raises(UnsupportedMetaCommandError) as raised:
        strings("WHENEVER SQLERROR PANIC\nSELECT 1 FROM dual;")
    assert str(raised.value) == (
        "Unsupported WHENEVER SQLERROR action at line 1: expected EXIT or CONTINUE"
    )


def test_whenever_sqlerror_with_a_slash_on_its_line_is_still_a_policy():
    assert strings("WHENEVER SQLERROR EXIT FAILURE /\nSELECT 1 FROM dual;")[0] == (
        "WHENEVER SQLERROR EXIT FAILURE /;"
    )


def test_continued_whenever_line_is_one_directive():
    assert strings("WHENEVER SQLERROR -\nCONTINUE\nSELECT 1 FROM dual;") == [
        "WHENEVER SQLERROR CONTINUE;",
        "SELECT 1 FROM dual;",
    ]


@pytest.mark.parametrize(
    "line",
    [
        "SET SERVEROUT ON",
        "SET SERVEROUTPUT OFF",
        "SET FEED OFF",
        "SET TERM OFF",
        "SET LINESIZE 200",
        "SET DEFINE OFF",
        "SET DEF '&'",
        "SHOW ERRORS",
        "SPOOL out.log",
        "PROMPT hello",
        "PRO hello",
        "REMARK it's a remark",
        "REM",
        "COL name FORMAT A30",
        "TTITLE 'x'",
        "COMPUTE SUM OF a ON b",
        "CLEAR SCREEN",
        "TIMING START t",
        "VARIABLE v NUMBER",
        "PRINT v",
        "DESC t",
        "WHENEVER OSERROR EXIT",
        "DEFINE x = 1",
        "UNDEFINE x",
    ],
)
def test_recognised_directives_are_recorded_not_sent_to_the_server(line):
    found = records(f"{line}\nSELECT 1 FROM dual;")
    assert [r[3] for r in found] == ["directive", "sql"]
    assert found[0][0] == line
    assert "SELECT 1 FROM dual;" in strings(f"{line}\nSELECT 1 FROM dual;")


def test_set_serveroutput_is_a_record_only():
    assert strings("SET SERVEROUTPUT ON\nSELECT 1 FROM dual;") == ["SELECT 1 FROM dual;"]


@pytest.mark.parametrize(
    "sql",
    [
        "SET ROLE ALL;",
        "SET TRANSACTION READ ONLY;",
        "SET CONSTRAINTS ALL DEFERRED;",
        "COMMENT ON TABLE t IS 'x';",
        "COMMIT;",
        "SELECT 1 FROM dual;",
        "DECLARE v NUMBER; BEGIN NULL; END;\n/",
    ],
)
def test_sql_that_starts_like_a_directive_stays_sql(sql):
    assert kinds(sql) == ["sql"]


def test_create_database_link_connect_to_is_sql():
    sql = "CREATE DATABASE LINK l CONNECT TO u IDENTIFIED BY p USING 'x';"
    assert strings(sql) == [sql]
    multi = "CREATE DATABASE LINK l\nCONNECT TO u IDENTIFIED BY p\nUSING 'x';"
    assert strings(multi) == [multi]


def test_rem_with_an_apostrophe_opens_no_literal():
    assert strings("REM don't\nCREATE TABLE a (x NUMBER);\nREM it's\nSELECT 1 FROM dual;") == [
        "CREATE TABLE a (x NUMBER);",
        "SELECT 1 FROM dual;",
    ]


def test_trailing_hyphen_continues_a_directive_onto_the_next_line():
    found = records("SET LINESIZE -\n  200\nCREATE TABLE a (x NUMBER);")
    assert found[0] == directive("SET LINESIZE 200", 1)
    assert found[1] == ("CREATE TABLE a (x NUMBER)", 3, ";", "sql")


def test_directive_only_where_a_statement_can_begin():
    block = "BEGIN\n  EXECUTE IMMEDIATE 'x';\nPROMPT_LIKE := 1;\nEND;"
    assert strings(f"{block}\n/") == [block]
    assert strings("SELECT 1\nFROM dual\nPRINT\n;") == ["SELECT 1\nFROM dual\nPRINT\n;"]
    assert kinds("SELECT 1 FROM dual\nPROMPT x\n/") == ["sql"]


def test_directive_after_a_unit_slash_and_indented_directives_are_recognised():
    assert kinds("BEGIN NULL; END;\n/\nPROMPT done\nSELECT 1 FROM dual;") == [
        "sql",
        "directive",
        "sql",
    ]
    assert kinds("SELECT 1 FROM dual;\n   set linesize 100\n") == ["sql", "directive"]


def test_directive_token_text_is_not_lexed():
    tokens = LexicalTokenizer("REM don't", spec=ORACLE_SPEC).tokenize()
    assert [(t.type, t.text) for t in tokens] == [(TokenType.DIRECTIVE, "REM don't")]


def test_trailing_comment_ends_the_directive_and_is_a_comment():
    assert records("SET LINESIZE 100 -- wide\nSELECT 1 FROM dual;")[0] == directive(
        "SET LINESIZE 100", 1
    )


@pytest.mark.parametrize(
    "script, expected",
    [
        ("EXEC dbms_output.put_line('-------')", "BEGIN dbms_output.put_line('-------'); END;"),
        ("EXEC dbms_output.put_line('a -- b');", "BEGIN dbms_output.put_line('a -- b'); END;"),
        ('EXEC p("x--y")', 'BEGIN p("x--y"); END;'),
        ("EXEC foo;\nSELECT 1 FROM dual;", "BEGIN foo; END;"),
    ],
)
def test_exec_is_rewritten_to_a_unit_and_quotes_hide_comment_markers(script, expected):
    assert strings(script)[0] == expected


def test_exec_without_a_statement_is_refused():
    with pytest.raises(UnsupportedMetaCommandError, match="EXECUTE on line 1 has no statement"):
        strings("EXEC ;")


def test_unclosed_quote_means_no_comment_and_no_continuation():
    found = records("DEFINE x = it's -\nSELECT 1 FROM dual;")
    assert found[0][0] == "DEFINE x = it's -"
    assert found[1][3] == "sql"


@pytest.mark.parametrize("word", ["PROMPT", "REM", "REMARK"])
def test_free_text_directives_keep_the_whole_line(word):
    line = f"{word} it's -- x"
    tokens = LexicalTokenizer(f"{line}\nSELECT 1 FROM dual;", spec=ORACLE_SPEC).tokenize()
    assert (tokens[0].type, tokens[0].text) == (TokenType.DIRECTIVE, line)


@pytest.mark.parametrize(
    "script, texts",
    [
        ("/* c */ PROMPT hi\nSELECT 1 FROM dual;", ["PROMPT hi", None]),
        ("/* a */ /* b */ SET LINESIZE 9\nSELECT 1 FROM dual;", ["SET LINESIZE 9", None]),
        ("/* c */ SELECT 1 FROM dual;", [None]),
    ],
)
def test_a_directive_may_follow_block_comments_on_its_line(script, texts):
    got = [
        r.text if r.kind == "directive" else None for r in LexicalEngine(ORACLE_SPEC).split(script)
    ]
    assert got == texts


def test_every_directive_example_is_recorded_refused_or_ends_the_script():
    for d in SQLPLUS_DIRECTIVES:
        for example in d.examples:
            found = classify_directive(RULES, example)
            assert found is not None, example
            raw = f"{example}\nCREATE TABLE t_{d.name.lower()} (id NUMBER);\n"
            if found[1] is DirectiveAction.REJECT:
                with pytest.raises(UnsupportedMetaCommandError):
                    strings(raw)
                continue
            out = strings(raw)
            survives = any(f"t_{d.name.lower()}" in s for s in out)
            assert survives == (found[1] is not DirectiveAction.EXIT), (example, out)
            for s in out:
                if s.startswith("CREATE TABLE"):
                    continue
                if found[1] is DirectiveAction.EXEC:
                    assert s.startswith("BEGIN "), out
                else:
                    assert not d.filter_from_execution and "WHENEVER SQLERROR" in s, out


@pytest.mark.parametrize(
    "line, expected",
    [
        ("SET SERVEROUT ON", ("SET SERVEROUTPUT", DirectiveAction.DROP_RECORD)),
        ("SET SERVEROU ON", ("SET", DirectiveAction.DROP_RECORD)),
        ("SET DEF OFF", ("SET DEFINE", DirectiveAction.DEFINE)),
        ("set feed off", ("SET", DirectiveAction.DROP_RECORD)),
        ("EXEC p;", ("EXECUTE", DirectiveAction.EXEC)),
        ("EXIT 1", ("EXIT", DirectiveAction.EXIT)),
        ("QUIT", ("QUIT", DirectiveAction.EXIT)),
        ("@@x.sql", ("@@", DirectiveAction.REJECT)),
        ("SELECT 1 FROM dual", None),
        ("SET", None),
        ("WHENEVER NOT FOUND EXIT", None),
        ("WHENEVER SQLERROR EXIT", ("WHENEVER SQLERROR", DirectiveAction.DROP_RECORD)),
        ("WHENEVE SQLERROR EXIT", None),
        ("whenever oserror exit", ("WHENEVER OSERROR", DirectiveAction.DROP_RECORD)),
        ("PROMPTS x", None),
    ],
)
def test_classify_directive(line, expected):
    assert classify_directive(RULES, line) == expected


def test_every_rule_matches_at_its_minimum_abbreviation_and_not_below():
    for rule in RULES.directives:
        at_minimum = classify_directive(RULES, rule.word[: rule.min_abbrev] + " x")
        assert at_minimum is not None and at_minimum[0] == rule.word, rule.word
        below = classify_directive(RULES, rule.word[: rule.min_abbrev - 1] + " x")
        assert below is None or below[0] != rule.word, rule.word
    for rule in RULES.set_options:
        at_minimum = classify_directive(RULES, "SET " + rule.word[: rule.min_abbrev] + " x")
        assert at_minimum is not None and at_minimum[0] == f"SET {rule.word}", rule.word
        below = classify_directive(RULES, "SET " + rule.word[: rule.min_abbrev - 1] + " x")
        assert below is not None and below[0] != f"SET {rule.word}", rule.word


def test_a_directive_record_is_a_statement_of_kind_directive():
    (record,) = LexicalEngine(ORACLE_SPEC).split("SET LINESIZE 100\n")
    assert record == Statement(text="SET LINESIZE 100", line=1, terminator=None, kind="directive")
    assert (record.source_start, record.source_end) == (0, 17)


@pytest.mark.parametrize(
    "line",
    ["PROMPT hi -- x", "PRO hi -- x", "REMARK a -- b", "REM a -- b"],
)
def test_free_text_directives_do_not_read_a_comment(line):
    script = f"{line}\nSELECT 1 FROM dual;"
    assert records(script)[0] == directive(line, 1)
    tokens = LexicalTokenizer(script, spec=ORACLE_SPEC).tokenize()
    assert [t.type for t in tokens[:2]] == [TokenType.DIRECTIVE, TokenType.KEYWORD]


@pytest.mark.parametrize("action, policy", [("EXIT FAILURE", "exit"), ("CONTINUE", "continue")])
def test_the_projected_policy_line_is_read_by_the_policy_reader(action, policy):
    from dblift.db.plugins.oracle.quirks import OracleQuirks

    projected = strings(f"WHENEVER SQLERROR {action}\nCREATE TABLE t (id NUMBER);")[0]
    assert OracleQuirks().parse_error_policy_directive(projected) == policy
