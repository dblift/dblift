"""The Db2 script scanner: the rules of docs/sql-parsing/db2.md sections 3 to 6, one test per claim."""

from __future__ import annotations

import pytest

from dblift.core.exceptions import UnsafeStatementSplitError, UnsupportedMetaCommandError
from dblift.db.plugins.db2.parser._script import Unit, scan_script
from dblift.db.plugins.db2.parser.db2_regex_parser import DB2RegexParser


def texts(script: str) -> list[str]:
    return [u.text for u in scan_script(script) if u.kind == "sql"]


def test_a_statement_ends_at_a_line_whose_last_non_blank_characters_are_the_terminator() -> None:
    assert texts("SELECT 1 FROM t;\nSELECT 2 FROM t ;  \t\nSELECT 3 FROM t\n;") == [
        "SELECT 1 FROM t",
        "SELECT 2 FROM t",
        "SELECT 3 FROM t",
    ]


def test_a_cr_is_a_line_end_only_before_a_lf_and_a_lone_cr_is_text() -> None:
    assert texts("SELECT 1;\r\nSELECT 2;\r\n") == ["SELECT 1", "SELECT 2"]
    with pytest.raises(UnsafeStatementSplitError):  # one line: a ';' in the middle, then code
        scan_script("SELECT 1;\rSELECT 2;\r")
    assert texts("SELECT 1;\r") == ["SELECT 1;"]  # the last line ends in CR, not in the terminator


@pytest.mark.parametrize("blank", [" ", "\x0c"])
def test_a_no_break_space_or_a_form_feed_after_the_terminator_is_not_blank(blank: str) -> None:
    """The statement has not ended: it runs on to the next line and has a ';' in the middle."""
    with pytest.raises(UnsafeStatementSplitError):
        scan_script(f"SELECT 1;{blank}\nSELECT 2;")


def test_a_statement_keeps_the_line_ends_it_was_written_with() -> None:
    assert texts("CREATE TABLE t (\r\n  id INT\r\n);\r\n") == ["CREATE TABLE t (\r\n  id INT\r\n)"]


def test_a_leading_byte_order_mark_is_dropped() -> None:
    assert texts("\ufeffSELECT 1;") == ["SELECT 1"]


def test_leading_blank_and_comment_lines_are_not_part_of_the_statement() -> None:
    assert texts("\n  \n-- a;\n-- b\nSELECT 1;") == ["SELECT 1"]


def test_a_comment_line_inside_a_statement_is_kept_and_ends_nothing() -> None:
    assert texts("CREATE TABLE t (\n-- c;\n  id INT);") == ["CREATE TABLE t (\n-- c;\n  id INT)"]


def test_a_comment_that_follows_code_is_part_of_the_line() -> None:
    assert texts("SELECT 1 -- c;\nSELECT 2 -- d ;") == ["SELECT 1 -- c", "SELECT 2 -- d"]


def test_a_comment_after_a_semicolon_is_trivia_and_the_statement_ends_at_the_semicolon() -> None:
    assert texts("SELECT 1; -- c\nSELECT 2;") == ["SELECT 1", "SELECT 2"]
    assert texts("SELECT 1; /* c */\nSELECT 2;") == ["SELECT 1", "SELECT 2"]
    assert texts("CREATE TABLE t (\n  id INT\n); -- done") == ["CREATE TABLE t (\n  id INT\n)"]
    assert [u.line for u in scan_script("SELECT 1; -- c\nSELECT 2;") if u.kind == "sql"] == [1, 2]
    # the custom terminator keeps the old rule: a ';' with code after it, on any line, is refused
    with pytest.raises(UnsafeStatementSplitError):
        scan_script("--#SET TERMINATOR @\nSELECT 1; -- c\nSELECT 2@")


@pytest.mark.parametrize(
    "script",
    ["INSERT INTO t VALUES ('a;\nb');", 'CREATE TABLE "a;\nb" (id INT);', "SELECT 'x\n;\n';"],
)
def test_a_terminator_at_a_line_end_inside_a_string_or_a_quoted_identifier_is_refused(
    script: str,
) -> None:
    with pytest.raises(UnsafeStatementSplitError, match="inside a string"):
        scan_script(script)


def test_a_terminator_at_a_line_end_inside_a_block_comment_does_not_cut() -> None:
    assert texts("SELECT 1 /* x;\n y */;") == ["SELECT 1 /* x;\n y */"]
    assert texts("/*\nDROP TABLE old;\n*/\nCREATE TABLE n (id INT);") == [
        "/*\nDROP TABLE old;\n*/\nCREATE TABLE n (id INT)"
    ]
    assert texts("--#SET TERMINATOR @\n/* a@\n b */ SELECT 1@") == ["/* a@\n b */ SELECT 1"]


@pytest.mark.parametrize(
    "script",
    [
        "INSERT INTO t VALUES ('a;b');",
        'CREATE TABLE "a;b" (id INT);',
        "SELECT 1 /* ; */;",
        "SELECT 1 /* a /* b */ ; */ FROM t;",
        "SELECT 1 -- a; b\nFROM t;",
        "SELECT 1;;",
        "SELECT 1; -- done",
        "SELECT 1; /* done */",
    ],
)
def test_a_semicolon_that_cannot_cut_is_not_refused(script: str) -> None:
    assert len(texts(script)) == 1


@pytest.mark.parametrize(
    "script",
    [
        "SELECT 1; SELECT 2;",
        "SELECT 1;SELECT 2",
        "CREATE PROCEDURE p() BEGIN END; SELECT 1;",
        "SELECT 1; ('x')",
    ],
)
def test_code_after_a_semicolon_in_the_middle_of_a_statement_is_refused(script: str) -> None:
    with pytest.raises(UnsafeStatementSplitError, match="code after a ';'"):
        scan_script(script)


def test_the_semicolon_check_follows_a_custom_terminator_too() -> None:
    with pytest.raises(UnsafeStatementSplitError):
        scan_script("--#SET TERMINATOR @\nSELECT 1; SELECT 2@")
    assert texts("--#SET TERMINATOR @\nSELECT 1;@") == ["SELECT 1;"]


# ---- the terminator directive ----


def test_the_directive_changes_the_terminator_until_the_next_one() -> None:
    units = scan_script("--#SET TERMINATOR @\nSELECT 1@\n--#SET TERMINATOR ;\nSELECT 2;")
    assert [(u.kind, u.text, u.terminator) for u in units] == [
        ("directive", "--#SET TERMINATOR @", None),
        ("sql", "SELECT 1", "@"),
        ("directive", "--#SET TERMINATOR ;", None),
        ("sql", "SELECT 2", ";"),
    ]


@pytest.mark.parametrize(
    "value", ["@", "%%", "'", '"', "/", "\\", "-", "*", "$", "|", "0", "e", ";;", "@;"]
)
def test_any_one_or_two_characters_are_a_terminator(value: str) -> None:
    assert texts(f"--#SET TERMINATOR {value}\nSELECT 1{value}\nSELECT 2{value}") == [
        "SELECT 1",
        "SELECT 2",
    ]


@pytest.mark.parametrize(
    "line", ["--#SET  TERMINATOR  @", "  --#SET TERMINATOR @", "\t--#SET TERMINATOR @ \t"]
)
def test_blanks_around_the_words_are_fine(line: str) -> None:
    assert texts(f"{line}\nSELECT 1@") == ["SELECT 1"]


@pytest.mark.parametrize(
    "line",
    [
        "--#set terminator @",
        "--#SET terminator @",
        "--#set TERMINATOR @",
        "--#SET\tTERMINATOR @",
        "-- #SET TERMINATOR @",
    ],
)
def test_what_is_not_the_directive_is_a_comment(line: str) -> None:
    assert texts(f"{line}\nSELECT 1;") == ["SELECT 1"]


@pytest.mark.parametrize(
    "line",
    [
        "--#SET TERMINATOR abc",
        "--#SET TERMINATOR @ @",
        "--#SET TERMINATOR @ -- c",
        "--#SET TERMINATOR",
        "--#SET TERMINATOR ",
        "--#SET TERMINATOR@",
        "--#SET TERMINATOR\t@",
    ],
)
def test_a_malformed_directive_is_refused_with_its_line(line: str) -> None:
    with pytest.raises(UnsafeStatementSplitError, match="line 2"):
        scan_script(f"SELECT 0;\n{line}\nSELECT 1;")


def test_the_directive_is_read_in_the_middle_of_a_statement() -> None:
    assert texts("CREATE TABLE t (\n--#SET TERMINATOR @\nid INT)@") == ["CREATE TABLE t (\nid INT)"]


@pytest.mark.parametrize(
    "script",
    [
        "INSERT INTO t VALUES ('x\n--#SET TERMINATOR @\ny')@",
        'CREATE TABLE "a\n--#SET TERMINATOR @\nb" (id INT);',
        "/*\n--#SET TERMINATOR @\n*/ SELECT 1@",
    ],
)
def test_a_directive_inside_a_string_a_quoted_identifier_or_a_comment_is_refused(
    script: str,
) -> None:
    with pytest.raises(UnsafeStatementSplitError, match="line 2 stands inside"):
        scan_script(script)


def test_a_directive_after_code_on_its_line_is_not_a_directive() -> None:
    assert texts("SELECT 1 --#SET TERMINATOR @\nFROM t;") == [
        "SELECT 1 --#SET TERMINATOR @\nFROM t"
    ]


def test_other_set_lines_are_comments() -> None:
    assert texts("--#SET DELIMITER @\n--#SET MAXERRORS 1\n--#COMMENT hi\nSELECT 1;") == ["SELECT 1"]


# ---- the last statement, empty and comment-only statements ----


def test_a_last_statement_without_a_terminator_is_returned_with_no_terminator() -> None:
    units = scan_script("SELECT 1;\nSELECT 2")
    assert [(u.text, u.terminator) for u in units] == [("SELECT 1", ";"), ("SELECT 2", None)]


def test_a_comment_after_the_last_terminator_is_not_a_statement() -> None:
    assert texts("SELECT 1;\n/* bye */\n") == ["SELECT 1"]


@pytest.mark.parametrize(
    "script",
    [
        "SELECT 1;\n/* bye\n",
        "SELECT 1;\n/* oops\nCREATE TABLE t (id INT);\n",
        "SELECT 1 /* a\nSELECT 2;",
        "--#SET TERMINATOR @\n/* oops\nCREATE TABLE t (id INT)@",
    ],
)
def test_a_block_comment_that_is_never_closed_is_refused_with_the_line_it_opened_on(
    script: str,
) -> None:
    with pytest.raises(UnsafeStatementSplitError, match="not closed"):
        scan_script(script)


def test_the_message_names_the_line_the_comment_opened_on() -> None:
    with pytest.raises(UnsafeStatementSplitError, match="line 2"):
        scan_script("SELECT 1;\n/* oops\nCREATE TABLE t (id INT);")


@pytest.mark.parametrize("terminator", ["/", "*/"])
@pytest.mark.parametrize("body", ["/* header */", "CREATE TABLE t (id INT) /* x */"])
def test_a_terminator_that_completes_a_comment_close_is_refused_not_read_as_a_comment(
    terminator: str, body: str
) -> None:
    script = f"--#SET TERMINATOR {terminator}\n{body}\nCREATE TABLE u (id INT)\n{terminator}\n"
    with pytest.raises(UnsafeStatementSplitError, match="line 2"):
        scan_script(script)


def test_a_terminator_that_shares_a_character_with_a_comment_but_closes_nothing_is_fine() -> None:
    assert texts("--#SET TERMINATOR /\nSELECT 1 /* a */ FROM t\n/\nSELECT 2\n/") == [
        "SELECT 1 /* a */ FROM t",
        "SELECT 2",
    ]


@pytest.mark.parametrize(
    "script, expected",
    [
        ("SELECT 1 /* a\n b */", "SELECT 1 /* a\n b */"),
        ("SELECT 'a\nb'", "SELECT 'a\nb'"),
        ('SELECT "a\nb"', 'SELECT "a\nb"'),
        ("SELECT 1\n\n  \n", "SELECT 1"),
        ("SELECT 1\n-- why\n", "SELECT 1"),
        ("SELECT 1\n-- a\n  -- b\n", "SELECT 1"),
        ("SELECT 1\n-- a\nFROM t\n-- b", "SELECT 1\n-- a\nFROM t"),
        ("SELECT 'a\n-- b", "SELECT 'a\n-- b"),
    ],
)
def test_the_last_statement_is_returned_whole(script: str, expected: str) -> None:
    assert texts(script) == [expected]


def test_a_terminator_at_a_line_end_inside_a_string_in_a_body_is_refused_too() -> None:
    script = "CREATE PROCEDURE p()\nBEGIN\n  INSERT INTO t VALUES ('a;\nb');\nEND;"
    with pytest.raises(UnsafeStatementSplitError, match="inside a string"):
        scan_script(script)


def test_the_semicolon_refusal_names_the_line_holding_the_semicolon() -> None:
    with pytest.raises(UnsafeStatementSplitError, match="line 3"):
        scan_script("CREATE TABLE t (\n  id INT\n); SELECT 1;\nSELECT 2;")


@pytest.mark.parametrize("line", ["--#SET TERMINATORX @", "--#SET TERMINATORS @"])
def test_a_comment_that_merely_starts_like_the_directive_is_text(line: str) -> None:
    assert texts(f"{line}\nSELECT 1;") == ["SELECT 1"]


def test_a_statement_line_is_the_first_line_with_something_on_it() -> None:
    assert [u.line for u in scan_script("\x0c\nSELECT 1;")] == [2]


def test_a_comment_alone_before_a_terminator_is_not_a_statement() -> None:
    assert texts("SELECT 1;\n/* c */;\nSELECT 2;") == ["SELECT 1", "SELECT 2"]


def test_empty_statements_are_not_statements() -> None:
    assert texts(";\n;;\n  ;\nSELECT 1;;\n;") == ["SELECT 1;"]


# ---- CLP commands ----


@pytest.mark.parametrize(
    "line",
    [
        "CONNECT TO sample",
        "connect to sample",
        "CONNECT",
        "QUIT",
        "ECHO hello",
        "!ls",
        "? CONNECT",
        "UPDATE COMMAND OPTIONS USING S ON",
        "UPDATE DB CFG FOR sample USING LOGFILSIZ 10",
        "UPDATE DATABASE MANAGER CONFIGURATION USING DIAGLEVEL 3",
        "CHANGE ISOLATION TO UR",
        "REORG TABLE t",
        "RUNSTATS ON TABLE t",
        "EXPORT TO f.del OF DEL SELECT * FROM t",
        "IMPORT FROM f.del OF DEL INSERT INTO t",
        "LOAD FROM f.del OF DEL INSERT INTO t",
        "LIST TABLES",
        "DESCRIBE TABLE t",
        "GET DB CFG",
        "ATTACH TO inst",
        "BIND f.bnd",
        "BACKUP DATABASE sample",
        "RESTORE DATABASE sample",
        "FORCE APPLICATION (1)",
        "SET CLIENT CONNECT_NODE 0",
        "START DATABASE MANAGER",
        "STOP DATABASE MANAGER",
        "REGISTER XMLSCHEMA a AS b",
        "RESET DB CFG FOR sample",
    ],
)
def test_a_clp_command_is_refused_by_name_and_line(line: str) -> None:
    with pytest.raises(UnsupportedMetaCommandError, match="line 2"):
        scan_script(f"SELECT 0;\n{line};\nSELECT 1;")


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE t SET a = 1",
        "UPDATE history SET a = 1",
        "SET CURRENT SCHEMA s",
        "SET SCHEMA s",
        "SET v = 1",
        "CREATE TABLE connect (id INT)",
        "DROP TABLE t",
        "REFRESH TABLE t",
        "COMMIT WORK",
        "ROLLBACK",
        "CREATE DATABASE LINK dl CONNECT TO u USING 'db'",
        "CREATE DATABASE sample",
        "CALL p(?)",
        "VALUES 1",
        "WITH x(a) AS (VALUES 1) SELECT a FROM x",
        "XQUERY 1",
        "/* c */ ECHO hello",
        "/* c */ CONNECT RESET",
        "EXIT",
        "GO",
        "GET DIAGNOSTICS rc = ROW_COUNT",
    ],
)
def test_sql_and_other_text_is_not_a_clp_command(statement: str) -> None:
    assert texts(f"{statement};") == [statement]


def test_a_command_word_in_the_middle_of_a_statement_is_text() -> None:
    assert texts("CREATE TABLE t (\nconnect INT,\necho INT,\nquit INT);") == [
        "CREATE TABLE t (\nconnect INT,\necho INT,\nquit INT)"
    ]


def test_connect_reset_and_terminate_at_the_end_are_dropped_and_recorded() -> None:
    units = scan_script("SELECT 1;\nCOMMIT;\nCONNECT RESET;\nTERMINATE;\n")
    assert [(u.kind, u.text) for u in units] == [
        ("sql", "SELECT 1"),
        ("sql", "COMMIT"),
        ("directive", "CONNECT RESET"),
        ("directive", "TERMINATE"),
    ]
    assert [u.kind for u in scan_script("SELECT 1;\nterminate;")] == ["sql", "directive"]


@pytest.mark.parametrize("script", ["CONNECT RESET;\nSELECT 1;", "TERMINATE;\nSELECT 1;"])
def test_connect_reset_and_terminate_before_a_statement_are_refused(script: str) -> None:
    with pytest.raises(UnsupportedMetaCommandError, match="line 1"):
        scan_script(script)


def test_a_clp_comment_block_is_refused_where_it_opens() -> None:
    for line in ("(=", "   (= c =)"):
        with pytest.raises(UnsupportedMetaCommandError, match="line 2"):
            scan_script(f"SELECT 1;\n{line}\nSELECT 2;")
    assert texts("SELECT 1 (= c =);") == ["SELECT 1 (= c =)"]  # in the middle of a line it is text


# ---- routine bodies ----


BODY = "CREATE PROCEDURE p()\nBEGIN\n  DECLARE x INT;\n  SET x = 1;\nEND"


def test_a_routine_body_is_kept_whole_under_the_semicolon_terminator() -> None:
    assert texts(f"{BODY};\nCALL p();") == [BODY, "CALL p()"]


def test_a_routine_body_on_one_line_needs_nothing() -> None:
    one = "CREATE PROCEDURE p() BEGIN DECLARE x INT; SET x = 1; END"
    assert texts(f"{one};\nCALL p();") == [one, "CALL p()"]


def test_a_routine_body_under_a_custom_terminator() -> None:
    assert texts(f"--#SET TERMINATOR @\n{BODY}@\nCALL p()@") == [BODY, "CALL p()"]


@pytest.mark.parametrize(
    "head",
    [
        "CREATE PROCEDURE p()",
        "CREATE OR REPLACE PROCEDURE p()",
        "create function f() returns int",
        "CREATE TRIGGER tr AFTER INSERT ON t FOR EACH ROW",
        "CREATE TRIGGER tr AFTER INSERT ON t REFERENCING NEW AS n FOR EACH ROW WHEN (n.a > (1 + 1))",
        "ALTER MODULE m ADD PROCEDURE p()",
        "CREATE METHOD m() FOR t",
    ],
)
def test_every_routine_head_keeps_its_body(head: str) -> None:
    script = f"{head}\nBEGIN ATOMIC\n  SET x = 1;\n  SET y = 2;\nEND;\nSELECT 1;"
    assert len(texts(script)) == 2


def test_a_compound_statement_is_a_body() -> None:
    script = "BEGIN ATOMIC\n  DECLARE v INT;\n  SET v = 1;\nEND;\nSELECT 1;"
    assert len(texts(script)) == 2
    assert len(texts("BEGIN\n  DECLARE v INT;\nEND;\nSELECT 1;")) == 2
    assert len(texts("BEGIN NOT ATOMIC\n  DECLARE v INT;\nEND;\nSELECT 1;")) == 2


def test_nested_controls_pair_their_ends() -> None:
    body = (
        "CREATE PROCEDURE p()\nBEGIN\n  DECLARE i INT DEFAULT 0;\n  WHILE i < 3 DO\n    SET i = i + 1;\n  END WHILE;\n"
        "  IF i = 3 THEN\n    SET i = 0;\n  END IF;\n  FOR r AS SELECT 1 AS c FROM sysibm.sysdummy1 DO\n    SET i = r.c;\n  END FOR;\n"
        "  REPEAT\n    SET i = i + 1;\n  UNTIL i > 2 END REPEAT;\n  L1: LOOP\n    LEAVE L1;\n  END LOOP L1;\n"
        "  CASE i WHEN 1 THEN SET i = 2; ELSE SET i = 3; END CASE;\n  SET i = CASE WHEN i = 1 THEN 1 ELSE 2 END;\n"
        "  BEGIN\n    DECLARE j INT;\n    SET j = 1;\n  END;\nEND"
    )
    assert texts(f"{body};\nSELECT 1;") == [body, "SELECT 1"]


def test_a_comment_between_end_and_its_keyword_changes_nothing() -> None:
    body = "CREATE PROCEDURE p()\nBEGIN\n  IF 1 = 1 THEN\n    SET x = 1;\n  END /* c */ IF;\n  END -- c\n  IF;\nEND"
    assert texts(f"{body};") == [body]


def test_end_followed_by_a_label_closes_the_block() -> None:
    body = "CREATE PROCEDURE p()\nP1: BEGIN\n  SET x = 1;\nEND P1"
    assert texts(f"{body};\nSELECT 1;") == [body, "SELECT 1"]


def test_words_in_strings_identifiers_and_comments_count_for_nothing() -> None:
    body = (
        "CREATE PROCEDURE p()\nBEGIN\n  INSERT INTO t VALUES ('END;');\n  INSERT INTO \"BEGIN\" VALUES (1);\n"
        "  -- END;\n  /* END; /* nested END; */ BEGIN */\n  SET x = 1;\nEND"
    )
    assert texts(f"{body};") == [body]


def test_a_routine_without_a_body_ends_at_its_terminator() -> None:
    assert texts(
        "CREATE FUNCTION f() RETURNS INT\nRETURN CASE WHEN 1 = 1 THEN 1 END;\nSELECT 1;"
    ) == [
        "CREATE FUNCTION f() RETURNS INT\nRETURN CASE WHEN 1 = 1 THEN 1 END",
        "SELECT 1",
    ]
    assert texts("CREATE MODULE m;\nALTER MODULE m PUBLISH PROCEDURE q();") == [
        "CREATE MODULE m",
        "ALTER MODULE m PUBLISH PROCEDURE q()",
    ]


def test_a_directive_inside_a_body_is_consumed() -> None:
    units = scan_script(
        "--#SET TERMINATOR @\nCREATE PROCEDURE p()\nBEGIN\n--#SET TERMINATOR @\n  SET x = 1;\nEND@"
    )
    assert [u.kind for u in units] == ["directive", "directive", "sql"]
    assert units[-1].text == "CREATE PROCEDURE p()\nBEGIN\n  SET x = 1;\nEND"


@pytest.mark.parametrize(
    "script", ["CREATE PROCEDURE p()\nBEGIN\n  SET x = 1;\n", "BEGIN ATOMIC\n  SET x = 1;"]
)
def test_a_body_that_is_not_closed_is_refused(script: str) -> None:
    with pytest.raises(UnsafeStatementSplitError, match="not closed"):
        scan_script(script)


# ---- records ----


def test_units_carry_line_terminator_and_kind() -> None:
    units = scan_script("\n-- c\nSELECT 1;\n--#SET TERMINATOR @\n\nSELECT 2@\nSELECT 3")
    assert units == [
        Unit("SELECT 1", 3, ";", "sql"),
        Unit("--#SET TERMINATOR @", 4, None, "directive"),
        Unit("SELECT 2", 6, "@", "sql"),
        Unit("SELECT 3", 7, None, "sql"),
    ]


def test_the_parser_returns_statement_records_and_the_string_projection() -> None:
    parser = DB2RegexParser()
    script = "--#SET TERMINATOR @\nSELECT 1@\nSELECT 2"
    records = parser.split(script)
    assert [(r.kind, r.text, r.terminator, r.line) for r in records] == [
        ("directive", "--#SET TERMINATOR @", None, 1),
        ("sql", "SELECT 1", "@", 2),
        ("sql", "SELECT 2", None, 3),
    ]
    assert parser.split_statements(script) == ["SELECT 1", "SELECT 2"]
    assert parser.SPLITS_WITHOUT_FALLBACK is True


def test_the_epilogue_is_a_directive_record_and_not_in_the_string_projection() -> None:
    parser = DB2RegexParser()
    script = "SELECT 1;\nCONNECT RESET;\nTERMINATE;"
    assert [(r.kind, r.text) for r in parser.split(script)] == [
        ("sql", "SELECT 1"),
        ("directive", "CONNECT RESET"),
        ("directive", "TERMINATE"),
    ]
    assert parser.split_statements(script) == ["SELECT 1"]


def test_a_package_is_a_body_that_opens_at_as_and_closes_at_its_own_end() -> None:
    spec = "CREATE OR REPLACE PACKAGE pk1 AS\nPROCEDURE proc1(x INT);\nEND pk1"
    body = (
        "CREATE OR REPLACE PACKAGE BODY pk1 AS\nPROCEDURE proc1(x INT) IS\nBEGIN\n  SET x = 1;\nEND proc1;\n"
        "PROCEDURE proc2(y INT) IS\nBEGIN\n  SET y = 1;\nEND proc2;\nEND pk1"
    )
    assert texts(f"{spec};\n{body};\nSELECT 1;") == [spec, body, "SELECT 1"]
    assert texts(f"--#SET TERMINATOR @\n{spec}@\n{body}@") == [spec, body]
    assert texts(f"{body}") == [body]  # the last statement needs no terminator


def test_a_blank_or_comment_only_script_has_no_statements() -> None:
    assert texts("") == [] and texts("\n  \n") == [] and texts("-- c\n/* d */\n") == []


@pytest.mark.parametrize(
    "script",
    [
        "SELECT 1;\nQUIT",
        "SELECT 1;\nQUIT; -- bye",
        "SELECT 1;\nQUIT -- bye",
        "SELECT 1;\nCONNECT RESET;\nTERMINATE;\nQUIT;",
        "--#SET TERMINATOR @\nSELECT 1@\nQUIT@",
    ],
)
def test_every_form_of_the_epilogue_is_dropped_and_recorded(script: str) -> None:
    units = scan_script(script)
    assert [u.kind for u in units if u.kind == "sql"] == ["sql"]
    assert units[-1].kind == "directive"


@pytest.mark.parametrize(
    "script",
    ["QUIT;\nSELECT 1;", "SELECT 1;\nQUIT;\nSELECT 2;", "--#SET TERMINATOR @\nQUIT@\nSELECT 1@"],
)
def test_quit_before_a_statement_is_refused(script: str) -> None:
    with pytest.raises(UnsupportedMetaCommandError, match="QUIT"):
        scan_script(script)


@pytest.mark.parametrize("command", ["CONNECT RESET", "QUIT", "TERMINATE"])
@pytest.mark.parametrize("after", ["\nCREATE TABLE u (id INT);", " -- c\nCREATE TABLE u (id INT);"])
def test_an_epilogue_command_without_a_terminator_does_not_swallow_the_next_statement(
    command: str, after: str
) -> None:
    with pytest.raises(UnsafeStatementSplitError, match="line 2"):
        scan_script(f"SELECT 1;\n{command}{after}")


@pytest.mark.parametrize(
    "script",
    [
        "SELECT 1;\nCONNECT RESET",
        "SELECT 1;\nQUIT;",
        "SELECT 1;\nTERMINATE -- bye",
        "SELECT 1;\nTERMINATE; -- bye",
        "SELECT 1;\nQUIT /* bye */",
        "--#SET TERMINATOR @\nSELECT 1@\nCONNECT RESET@",
    ],
)
def test_the_accepted_epilogue_forms_are_recorded_and_dropped(script: str) -> None:
    parser = DB2RegexParser()
    assert [r.kind for r in parser.split(script)][-1] == "directive"
    assert parser.split_statements(script) == ["SELECT 1"]


@pytest.mark.parametrize("tail", ["QUIT;;", "TERMINATE;;", "QUIT foo;", "CONNECT RESET now;"])
def test_what_is_not_exactly_an_epilogue_command_is_refused(tail: str) -> None:
    with pytest.raises(UnsafeStatementSplitError, match="line 2"):
        scan_script(f"SELECT 1;\n{tail}")


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE\nCOMMAND OPTIONS USING S ON",
        "UPDATE DB\nCFG FOR sample USING LOGFILSIZ 10",
        "SET\nCLIENT CONNECT_NODE 0",
    ],
)
def test_a_command_phrase_split_over_lines_is_still_a_command(statement: str) -> None:
    with pytest.raises(UnsupportedMetaCommandError, match="line 2"):
        scan_script(f"SELECT 0;\n{statement};")


def test_a_statement_that_merely_starts_like_a_command_phrase_on_two_lines_is_sql() -> None:
    assert texts("UPDATE\nt SET x = 1;") == ["UPDATE\nt SET x = 1"]


@pytest.mark.parametrize(
    "script, expected",
    [
        ("SELECT 1\n/* c */", "SELECT 1"),
        ("SELECT 1\n/* a\n b */\n", "SELECT 1"),
        ("SELECT 1 /* a\n b */\n-- c", "SELECT 1 /* a\n b */"),
        ("SELECT 1\n/* c */\nFROM t\n/* d */", "SELECT 1\n/* c */\nFROM t"),
    ],
)
def test_comment_lines_of_both_forms_after_the_last_code_are_not_part_of_it(
    script: str, expected: str
) -> None:
    assert texts(script) == [expected]
