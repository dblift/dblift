"""SQL*Plus directives are recorded or refused, never dropped (docs/sql-parsing/oracle.md section 6)."""

import logging

import pytest

from dblift.core.exceptions import UnsupportedMetaCommandError
from dblift.core.migration.sql.sql_analyzer import SqlAnalyzer
from dblift.core.sql_parser.parser_context import ParserContext
from dblift.core.sql_parser.statement import Statement
from dblift.core.sql_parser.tokens import TokenType
from dblift.db.plugins.oracle.parser._directives import DirectiveAction, classify_directive
from dblift.db.plugins.oracle.parser.oracle_statement_parser import OracleStatementParser
from dblift.db.plugins.oracle.parser.oracle_tokenizer import OracleTokenizer
from dblift.db.plugins.oracle.quirks import OracleQuirks


def _records(script):
    tokens = OracleTokenizer(script).tokenize()
    return OracleStatementParser(tokens, ParserContext(), source=script).split()


def _strings(script):
    return SqlAnalyzer("oracle").split_statements(script)


def _directive(text, line):
    return Statement(text=text, line=line, terminator=None, kind="directive")


def test_row_14_directives_are_records_between_the_statements():
    script = (
        "PROMPT Creating customer's table\nCREATE TABLE a (x NUMBER);\n"
        "REM don't run twice\nCREATE TABLE b (y NUMBER);"
    )

    assert _records(script) == [
        _directive("PROMPT Creating customer's table", 1),
        Statement(text="CREATE TABLE a (x NUMBER)", line=2, terminator=";"),
        _directive("REM don't run twice", 3),
        Statement(text="CREATE TABLE b (y NUMBER)", line=4, terminator=";"),
    ]
    assert _strings(script) == ["CREATE TABLE a (x NUMBER);", "CREATE TABLE b (y NUMBER);"]


def test_row_17_exit_stops_the_script_and_warns_naming_the_first_ignored_line(caplog):
    script = "SELECT 1 FROM dual;\nEXIT\nSELECT 2 FROM dual;"

    with caplog.at_level(logging.WARNING):
        records = _records(script)

    assert records == [
        Statement(text="SELECT 1 FROM dual", line=1, terminator=";"),
        _directive("EXIT", 2),
    ]
    assert any(
        "1 statement(s) after EXIT" in r.getMessage() and "first ignored line: 3" in r.getMessage()
        for r in caplog.records
    )
    assert _strings(script) == ["SELECT 1 FROM dual;"]


def test_exit_with_nothing_after_it_does_not_warn(caplog):
    with caplog.at_level(logging.WARNING):
        _records("SELECT 1 FROM dual;\nQUIT\n-- done\n")

    assert not caplog.records


def test_statements_after_exit_are_not_read_so_their_errors_do_not_surface():
    assert _strings("SELECT 1 FROM dual;\nEXIT\n@@never.sql\n") == ["SELECT 1 FROM dual;"]


def test_row_18_include_is_refused_naming_the_directive_and_line():
    with pytest.raises(UnsupportedMetaCommandError, match=r"'@@'.*line 1"):
        _strings("@@setup.sql\nSELECT 1 FROM dual;")


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
    ],
)
def test_interactive_and_lexer_changing_directives_are_refused(line, name):
    with pytest.raises(UnsupportedMetaCommandError, match=rf"{name!r}.*line 2"):
        _strings(f"SELECT 1 FROM dual;\n{line}\nSELECT 2 FROM dual;")


def test_row_19_directive_after_a_semicolon_on_the_same_line_is_refused():
    with pytest.raises(UnsupportedMetaCommandError, match=r"'PROMPT'.*line 1"):
        _strings("SELECT 1 FROM dual; PROMPT x\nSELECT 2 FROM dual;")


def test_row_23_whenever_sqlerror_is_recorded_and_still_reaches_execution():
    script = "WHENEVER SQLERROR EXIT FAILURE\nCREATE TABLE t (id NUMBER);"

    assert _records(script) == [
        _directive("WHENEVER SQLERROR EXIT FAILURE", 1),
        Statement(text="CREATE TABLE t (id NUMBER)", line=2, terminator=";"),
    ]
    strings = _strings(script)
    assert strings == ["WHENEVER SQLERROR EXIT FAILURE;", "CREATE TABLE t (id NUMBER);"]
    assert OracleQuirks().parse_error_policy_directive(strings[0]) == "exit"


def test_whenever_sqlerror_already_terminated_is_not_terminated_twice():
    assert _strings("WHENEVER SQLERROR CONTINUE;\nSELECT 1 FROM dual;")[0] == (
        "WHENEVER SQLERROR CONTINUE;"
    )


def test_whenever_sqlerror_with_an_unknown_action_is_refused():
    with pytest.raises(UnsupportedMetaCommandError, match="WHENEVER SQLERROR.*line 1"):
        _strings("WHENEVER SQLERROR PANIC\nSELECT 1 FROM dual;")


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
        "EXEC null",
        "EXECUTE null",
    ],
)
def test_recognised_directives_are_recorded_not_sent_to_the_server(line):
    records = _records(f"{line}\nSELECT 1 FROM dual;")

    assert [r.kind for r in records] == ["directive", "sql"]
    assert records[0].text == line
    assert "SELECT 1 FROM dual;" in _strings(f"{line}\nSELECT 1 FROM dual;")


def test_set_serveroutput_is_a_record_only():
    assert _strings("SET SERVEROUTPUT ON\nSELECT 1 FROM dual;") == ["SELECT 1 FROM dual;"]


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
    records = _records(sql)

    assert [r.kind for r in records] == ["sql"]


def test_create_database_link_connect_to_is_sql():
    sql = "CREATE DATABASE LINK l CONNECT TO u IDENTIFIED BY p USING 'x';"

    assert _strings(sql) == [sql]
    assert _strings("CREATE DATABASE LINK l\nCONNECT TO u IDENTIFIED BY p\nUSING 'x';") == [
        "CREATE DATABASE LINK l\nCONNECT TO u IDENTIFIED BY p\nUSING 'x';"
    ]


def test_rem_with_an_apostrophe_opens_no_literal():
    assert _strings("REM don't\nCREATE TABLE a (x NUMBER);\nREM it's\nSELECT 1 FROM dual;") == [
        "CREATE TABLE a (x NUMBER);",
        "SELECT 1 FROM dual;",
    ]


def test_trailing_hyphen_continues_a_directive_onto_the_next_line():
    script = "SET LINESIZE -\n  200\nCREATE TABLE a (x NUMBER);"

    records = _records(script)

    assert records[0] == _directive("SET LINESIZE 200", 1)
    assert records[1] == Statement(text="CREATE TABLE a (x NUMBER)", line=3, terminator=";")


def test_continued_whenever_line_is_one_directive():
    assert _strings("WHENEVER SQLERROR -\nCONTINUE\nSELECT 1 FROM dual;") == [
        "WHENEVER SQLERROR CONTINUE;",
        "SELECT 1 FROM dual;",
    ]


def test_directive_only_where_a_statement_can_begin():
    # Inside a block and inside a statement the words are SQL.
    block = "BEGIN\n  EXECUTE IMMEDIATE 'x';\nPROMPT_LIKE := 1;\nEND;"
    assert _strings(f"{block}\n/") == [block]
    assert _strings("SELECT 1\nFROM dual\nPRINT\n;") == ["SELECT 1\nFROM dual\nPRINT\n;"]


def test_directive_after_a_unit_slash_is_a_directive():
    records = _records("BEGIN NULL; END;\n/\nPROMPT done\nSELECT 1 FROM dual;")

    assert [r.kind for r in records] == ["sql", "directive", "sql"]


def test_indented_directive_is_recognised():
    assert [r.kind for r in _records("SELECT 1 FROM dual;\n   set linesize 100\n")] == [
        "sql",
        "directive",
    ]


def test_directive_token_text_is_not_lexed():
    tokens = OracleTokenizer("REM don't").tokenize()

    assert [(t.type, t.text) for t in tokens] == [(TokenType.DIRECTIVE, "REM don't")]


def test_trailing_comment_ends_the_directive_and_is_a_comment():
    records = _records("SET LINESIZE 100 -- wide\nSELECT 1 FROM dual;")

    assert records[0] == _directive("SET LINESIZE 100", 1)


def test_directive_ends_a_statement_with_no_terminator_before_it():
    # A statement without ';' or '/' is ended where a directive begins only if
    # a statement can begin there; here the SELECT is still open, so PROMPT is text.
    assert [r.kind for r in _records("SELECT 1 FROM dual\nPROMPT x\n/")] == ["sql"]


@pytest.mark.parametrize(
    "line, action, name",
    [
        ("SET SERVEROUT ON", DirectiveAction.RECORD_POLICY, "SET SERVEROUTPUT"),
        ("SET SERVEROUTPUT ON", DirectiveAction.RECORD_POLICY, "SET SERVEROUTPUT"),
        ("SET SERVEROU ON", DirectiveAction.DROP_RECORD, "SET"),  # below the minimum
        ("SET DEF OFF", DirectiveAction.DEFINE, "SET DEFINE"),
        ("set feed off", DirectiveAction.DROP_RECORD, "SET"),
        ("EXEC p;", DirectiveAction.EXEC, "EXECUTE"),
        ("EXIT 1", DirectiveAction.EXIT, "EXIT"),
        ("QUIT", DirectiveAction.EXIT, "QUIT"),
        ("@@x.sql", DirectiveAction.REJECT, "@@"),
        ("SELECT 1 FROM dual", None, None),
        ("SET", None, None),
        ("WHENEVER NOT FOUND EXIT", None, None),
        ("PROMPTS x", None, None),
    ],
)
def test_classify_directive(line, action, name):
    directive = classify_directive(line)

    if action is None:
        assert directive is None
    else:
        assert (directive.action, directive.name) == (action, name)
