"""The MySQL and MariaDB scanner (docs/sql-parsing/mysql.md): statements, delimiter, client commands."""

from __future__ import annotations

import pytest

from dblift.core.exceptions import UnsafeStatementSplitError
from dblift.db.plugins.mysql.parser._script import MAX_DELIMITER_LENGTH, scan_script


def sql(script: str, *, mariadb: bool = False) -> list[str]:
    return [s.text for s in scan_script(script, mariadb=mariadb) if s.kind == "sql"]


def test_a_statement_record_has_text_line_and_terminator() -> None:
    records = scan_script("CREATE TABLE t (id INT);\n\nINSERT INTO t VALUES (1)")
    assert [(r.text, r.line, r.terminator, r.kind) for r in records] == [
        ("CREATE TABLE t (id INT)", 1, ";", "sql"),
        ("INSERT INTO t VALUES (1)", 3, None, "sql"),
    ]


def test_delimiter_lines_are_directive_records_and_set_the_terminator() -> None:
    records = scan_script("DELIMITER //\nSELECT 1//\nDELIMITER ;\nSELECT 2;")
    assert [(r.text, r.line, r.terminator, r.kind) for r in records] == [
        ("DELIMITER //", 1, None, "directive"),
        ("SELECT 1", 2, "//", "sql"),
        ("DELIMITER ;", 3, None, "directive"),
        ("SELECT 2", 4, ";", "sql"),
    ]


@pytest.mark.parametrize(
    "line",
    [
        "DELIMITER //",
        "delimiter //",
        "DeLiMiTeR //",
        "  DELIMITER //",
        "\tDELIMITER //",
        "DELIMITER\t//",
        "DELIMITER   //",
        "DELIMITER '//'",
        'DELIMITER "//"',
        "DELIMITER `//`",
        "DELIMITER // tail words",
        "DELIMITER '//' tail",
        "DELIMITER // -- note",
        "DELIMITER // # note",
        "DELIMITER // /* note */",
    ],
)
def test_the_delimiter_command_forms_the_client_reads(line: str) -> None:
    assert sql(f"{line}\nSELECT 1//\nDELIMITER ;\nSELECT 2;") == ["SELECT 1", "SELECT 2"]


def test_an_unquoted_argument_ends_at_a_space_not_at_a_tab() -> None:
    assert sql("DELIMITER //\t\nSELECT 1//\t\nSELECT 2;\n") == ["SELECT 1", "SELECT 2;"]


def test_a_delimiter_after_comment_only_lines_is_a_command() -> None:
    assert sql("-- c\n# c\n/* c */\nDELIMITER //\nSELECT 1//") == ["SELECT 1"]


@pytest.mark.parametrize(
    "script",
    [
        "SELECT 1 AS\ndelimiter;\nSELECT 2;",
        "SELECT 1 AS\ndelimiter x;\nSELECT 2;",
        "CREATE TABLE t (delimiter INT);\nSELECT delimiter FROM t;",
        "SELECT 1\nDELIMITER //\nSELECT 2//\nDELIMITER ;\nSELECT 3;",
        "SELECT 'a\nDELIMITER //\nb';\nSELECT 2;",
        'SELECT "a\nDELIMITER //\nb";',
        "SELECT 1 AS `a\nDELIMITER //\nb`;",
        "/*\nDELIMITER //\n*/\nSELECT 1;",
        "-- DELIMITER //\nSELECT 1;",
        "# DELIMITER //\nSELECT 1;",
        "delimiter_x\nSELECT 1;",
        "delimiters //\nSELECT 1;",
    ],
)
def test_the_word_delimiter_is_text_unless_it_starts_a_line_with_nothing_pending(
    script: str,
) -> None:
    assert not [r for r in scan_script(script) if r.kind == "directive"]


def test_the_delimiter_is_matched_as_a_plain_string_even_inside_a_word() -> None:
    assert sql("DELIMITER GO\nSELECT 1 AS AGOB GO\nDELIMITER ;") == ["SELECT 1 AS A", "B"]


def test_a_semicolon_is_text_while_a_custom_delimiter_is_active() -> None:
    assert sql("DELIMITER //\nSELECT 1; SELECT 2//\nDELIMITER ;") == ["SELECT 1; SELECT 2"]


def test_the_delimiter_inside_strings_identifiers_and_comments_is_text() -> None:
    script = "DELIMITER //\nSELECT '//', `a//b` /* // */ -- //\n# //\n//\nSELECT 2//\n"
    assert sql(script) == ["SELECT '//', `a//b` /* // */ -- //\n# //", "SELECT 2"]


def test_the_custom_delimiter_splits_inside_an_executable_comment() -> None:
    assert sql("DELIMITER //\nSELECT 1 /*! // */ + 1//") == ["SELECT 1 /*!", "*/ + 1"]


def test_a_longer_text_than_the_delimiter_leaves_the_rest_behind() -> None:
    assert sql("DELIMITER //\nSELECT 1///\nDELIMITER ;") == ["SELECT 1", "/\nDELIMITER ;"]


def test_empty_units_are_not_statements() -> None:
    assert sql("DELIMITER //\n//\n//\nSELECT 1//\nDELIMITER ;\n;;\n;") == ["SELECT 1"]


def test_the_delimiter_may_be_fifteen_characters_and_no_more() -> None:
    fifteen = "x" * MAX_DELIMITER_LENGTH
    assert sql(f"DELIMITER {fifteen}\nSELECT 1{fifteen}") == ["SELECT 1"]
    with pytest.raises(UnsafeStatementSplitError, match="longer than 15"):
        scan_script(f"DELIMITER {fifteen}x\nSELECT 1;")


@pytest.mark.parametrize(
    "line,message",
    [
        ("DELIMITER", "no argument"),
        ("DELIMITER ", "no argument"),
        ("DELIMITER;", "no argument"),
        ("DELIMITER ''", "no argument"),
        ('DELIMITER ""', "no argument"),
        ("DELIMITER '", "no argument"),
        ("DELIMITER \\", "backslash"),
        ("DELIMITER \\\\", "backslash"),
        ("DELIMITER '\\'", "backslash"),
        ("DELIMITER a\\b", "backslash"),
    ],
)
def test_a_delimiter_command_the_client_rejects_is_refused(line: str, message: str) -> None:
    with pytest.raises(UnsafeStatementSplitError, match=message):
        scan_script(f"{line}\nSELECT 1;")


@pytest.mark.parametrize(
    "script",
    [
        "SELECT 1; DELIMITER //\nSELECT 2//\nDELIMITER ;",
        "SELECT 1;\nSELECT 2; DELIMITER //\nSELECT 3//",
        "/* c */ DELIMITER //\nSELECT 1//",
        "/* a */ /* b */ DELIMITER //\nSELECT 1//",
    ],
)
def test_delimiter_that_does_not_start_its_line_is_refused(script: str) -> None:
    with pytest.raises(UnsafeStatementSplitError, match="not the first word"):
        scan_script(script)


def test_a_bom_is_skipped_and_crlf_is_read() -> None:
    assert sql("\ufeffDELIMITER //\r\nSELECT 1//\r\nDELIMITER ;\r\nSELECT 2;\r\n") == [
        "SELECT 1",
        "SELECT 2",
    ]


def test_a_nul_byte_is_refused() -> None:
    with pytest.raises(UnsafeStatementSplitError, match="line 2"):
        scan_script("SELECT 1;\nSELECT 2\x00;")


# --------------------------------------------------------------------------- comments and strings


@pytest.mark.parametrize(
    "script,expected",
    [
        ("SELECT 1--1;\nSELECT 2;", ["SELECT 1--1", "SELECT 2"]),
        ("SELECT 1 --+ c\n;", ["SELECT 1 --+ c"]),
        ("SELECT 1 ---\n;", ["SELECT 1 ---"]),
        ("SELECT 1 -- c;\n+ 1; SELECT 2;", ["SELECT 1 -- c;\n+ 1", "SELECT 2"]),
        ("SELECT 1 --\n+ 1;", ["SELECT 1 --\n+ 1"]),
        ("SELECT 1 --\t;\n+ 1;", ["SELECT 1 --\t;\n+ 1"]),
        ("SELECT 1 --\r\n+ 1;", ["SELECT 1 --\n+ 1"]),
        ("SELECT 1 --\x0b;\n+ 1;", ["SELECT 1 --\x0b;\n+ 1"]),
        ("SELECT 1 --\x0c;\n+ 1;", ["SELECT 1 --\x0c;\n+ 1"]),
        ("SELECT 1 --\x01c;\n+ 1;", ["SELECT 1 --\x01c", "+ 1"]),
        ("SELECT 1 --\u00a0c;\n+ 1;", ["SELECT 1 --\u00a0c", "+ 1"]),
        ("SELECT a#; x\nFROM t;", ["SELECT a#; x\nFROM t"]),
        ("SELECT 1#c;\n+ 1;", ["SELECT 1#c;\n+ 1"]),
        ("SELECT 1; --", ["SELECT 1"]),
    ],
)
def test_dash_and_hash_comments_as_the_client_reads_them(script: str, expected: list[str]) -> None:
    assert sql(script) == expected


def test_a_block_comment_ends_at_its_first_close_marker() -> None:
    assert sql("/* a /* b */ ; */ SELECT 1;") == ["*/ SELECT 1"]
    assert sql("SELECT 1 /* a ; b */ + 1; SELECT 2;") == ["SELECT 1 /* a ; b */ + 1", "SELECT 2"]


def test_comments_before_and_after_statements_belong_to_none() -> None:
    script = "-- header\nSELECT 1; -- trailing\n/* between */\nSELECT 2; # last\n"
    assert sql(script) == ["SELECT 1", "SELECT 2"]
    assert sql("-- only\n# comments\n/* here */") == []


def test_an_executable_comment_stays_in_the_statement_and_does_not_hide_the_delimiter() -> None:
    assert sql("/*!40014 SET FOREIGN_KEY_CHECKS=0 */;\nSELECT 1;") == [
        "/*!40014 SET FOREIGN_KEY_CHECKS=0 */",
        "SELECT 1",
    ]
    assert sql("SELECT 1 /*! ; */ + 1; SELECT 2;") == ["SELECT 1 /*!", "*/ + 1", "SELECT 2"]
    assert sql("SELECT 1 /*!+ 1 */ AS x; SELECT 2;") == ["SELECT 1 /*!+ 1 */ AS x", "SELECT 2"]
    assert sql("/*!99999 SELECT 1 */;\nSELECT 2;") == ["/*!99999 SELECT 1 */", "SELECT 2"]


def test_a_comment_character_inside_an_executable_comment_is_a_comment_to_the_end_of_the_line() -> (
    None
):
    assert sql("SELECT 1 /*! # c ; */ AS a;\nSELECT 2;") == [
        "SELECT 1 /*! # c ; */ AS a;\nSELECT 2"
    ]


def test_a_comment_opening_inside_an_executable_comment_is_refused() -> None:
    with pytest.raises(UnsafeStatementSplitError, match="inside an executable comment"):
        scan_script("SELECT 1 /*! /* c */ + 1 */;")


def test_an_executable_comment_flag_does_not_outlive_its_line() -> None:
    assert sql("SELECT 1 /*!\n/* c ; */ + 1\n*/ AS a;") == ["SELECT 1 /*!\n/* c ; */ + 1\n*/ AS a"]


def test_the_maria_executable_comment_is_a_comment_on_mysql_and_code_on_mariadb() -> None:
    script = "/*M!100500 SELECT 1 */; SELECT 2;"
    assert sql(script) == ["SELECT 2"]
    assert sql(script, mariadb=True) == ["/*M!100500 SELECT 1 */", "SELECT 2"]
    assert sql("SELECT 1 /*M! ; */ + 1;") == ["SELECT 1 /*M! ; */ + 1"]
    assert sql("SELECT 1 /*M! ; */ + 1;", mariadb=True) == ["SELECT 1 /*M!", "*/ + 1"]


def test_an_optimizer_hint_hides_the_delimiter_and_stays_in_the_text() -> None:
    assert sql("SELECT 1 /*+ ; */ + 1; SELECT 2;") == ["SELECT 1 /*+ ; */ + 1", "SELECT 2"]


@pytest.mark.parametrize(
    "script,message",
    [
        ("SELECT 1; /* c ; SELECT 2;", "unterminated block comment starting at line 1, column 11"),
        ("/* c\nSELECT 1;", "unterminated block comment starting at line 1, column 1"),
        ("SELECT /*+ x;\nSELECT 3;", "unterminated optimizer hint starting at line 1, column 8"),
        ("SELECT 'abc;\nSELECT 2;", "unterminated string literal starting at line 1, column 8"),
        ('SELECT "abc;', "unterminated string literal starting at line 1, column 8"),
        ("SELECT 1 AS `abc;", "unterminated quoted identifier starting at line 1, column 13"),
    ],
)
def test_an_unterminated_lexeme_is_refused_with_its_position(script: str, message: str) -> None:
    with pytest.raises(UnsafeStatementSplitError, match=message):
        scan_script(script)


@pytest.mark.parametrize(
    "script,expected",
    [
        ("SELECT 'a\\'; b'; SELECT 2;", ["SELECT 'a\\'; b'", "SELECT 2"]),
        ("SELECT 'a\\\\'; SELECT 2;", ["SELECT 'a\\\\'", "SELECT 2"]),
        ('SELECT "a\\"; b"; SELECT 2;', ['SELECT "a\\"; b"', "SELECT 2"]),
        ("SELECT 'it''s; ok'; SELECT 2;", ["SELECT 'it''s; ok'", "SELECT 2"]),
        ("SELECT 1 AS `a\\`; SELECT 2;", ["SELECT 1 AS `a\\`", "SELECT 2"]),
        ("SELECT 1 AS `a``b;c`; SELECT 2;", ["SELECT 1 AS `a``b;c`", "SELECT 2"]),
        ("SELECT 'line1\n;line2'; SELECT 2;", ["SELECT 'line1\n;line2'", "SELECT 2"]),
        ("SELECT 'a\\\nb;c'; SELECT 2;", ["SELECT 'a\\\nb;c'", "SELECT 2"]),
        ("SELECT '-- ; # /* ;'; SELECT 2;", ["SELECT '-- ; # /* ;'", "SELECT 2"]),
        ("SELECT 'a\\c', 'b\\G';", ["SELECT 'a\\c', 'b\\G'"]),
        ("SELECT 0x3B3B, X'3B', B'1'; SELECT 2;", ["SELECT 0x3B3B, X'3B', B'1'", "SELECT 2"]),
        ("SET @'a;b' = 1; SELECT @`c;d`;", ["SET @'a;b' = 1", "SELECT @`c;d`"]),
        ("SELECT (1;\n+ 2); SELECT 3;", ["SELECT (1", "+ 2)", "SELECT 3"]),
    ],
)
def test_strings_and_identifiers_as_the_client_reads_them(script: str, expected: list[str]) -> None:
    assert sql(script) == expected


# --------------------------------------------------------------------------- stored programs


PROGRAMS = [
    "CREATE PROCEDURE p() BEGIN SELECT 1; SELECT 2; END",
    "CREATE DEFINER=`root`@`%` PROCEDURE p() BEGIN SELECT 1; END",
    "CREATE DEFINER = root@localhost PROCEDURE p() BEGIN SELECT 1; END",
    "CREATE DEFINER = CURRENT_USER PROCEDURE p() BEGIN SELECT 1; END",
    "CREATE DEFINER = CURRENT_USER() PROCEDURE p() BEGIN SELECT 1; END",
    "create procedure if not exists p() begin select 1; select 2; end",
    "CREATE FUNCTION f() RETURNS INT DETERMINISTIC BEGIN DECLARE x INT; SET x = 1; RETURN x; END",
    "CREATE TRIGGER tr BEFORE INSERT ON t FOR EACH ROW BEGIN SET NEW.id = 1; SET NEW.v = 2; END",
    "CREATE EVENT ev ON SCHEDULE EVERY 1 DAY DO BEGIN SELECT 1; SELECT 2; END",
    "ALTER EVENT ev DO BEGIN SELECT 3; SELECT 4; END",
    "ALTER DEFINER = root@localhost EVENT ev DO BEGIN SELECT 3; SELECT 4; END",
    "CREATE PROCEDURE p() lbl: BEGIN BEGIN SELECT 1; END; SELECT 2; END lbl",
    "CREATE PROCEDURE p() BEGIN IF 1 = 1 THEN SELECT 1; ELSEIF 2 = 2 THEN SELECT 2; ELSE SELECT 3; END IF; END",
    "CREATE PROCEDURE p() BEGIN DECLARE i INT DEFAULT 0; WHILE i < 2 DO SET i = i + 1; END WHILE; END",
    "CREATE PROCEDURE p() BEGIN l: LOOP IF 1 THEN LEAVE l; END IF; END LOOP l; END",
    "CREATE PROCEDURE p() BEGIN SET @i = 0; REPEAT SET @i = @i + 1; UNTIL @i > 3 END REPEAT; END",
    "CREATE PROCEDURE p() BEGIN CASE WHEN 1 = 1 THEN SELECT 1; ELSE SELECT 2; END CASE; END",
    "CREATE PROCEDURE p() BEGIN CASE 1 WHEN 1 THEN SELECT 1; END CASE; END",
    "CREATE PROCEDURE p() BEGIN SELECT CASE WHEN 1 THEN 'a' ELSE CASE WHEN 2 THEN 'b' END END; END",
    "CREATE PROCEDURE p() BEGIN SET @x = (CASE WHEN 1 THEN 1 END); SELECT 2; END",
    "CREATE PROCEDURE p() BEGIN SELECT IF(1 = 1, 'a', 'b'); SELECT REPEAT('x', 3); END",
    "CREATE PROCEDURE p() BEGIN DECLARE CONTINUE HANDLER FOR SQLEXCEPTION BEGIN SELECT 'e'; END; SELECT 1; END",
    "CREATE PROCEDURE p() BEGIN SELECT 'BEGIN; END;'; SELECT \"end;\"; SELECT 1; END",
    "CREATE PROCEDURE p() BEGIN -- END;\n SELECT 1; /* END; */ SELECT 2; # END;\n END",
    "CREATE PROCEDURE p() BEGIN SELECT 1 AS `end`, 2 AS `begin`; SELECT 3; END",
    "CREATE PROCEDURE p() BEGIN SET @begin = 1; SET @end = 2; SELECT t.end, t.begin FROM t; END",
    "CREATE PROCEDURE p(IN a INT) BEGIN SELECT a; SELECT 2; END",
    "CREATE PROCEDURE p() BEGIN DECLARE c CURSOR FOR SELECT id FROM t; OPEN c; CLOSE c; END",
    "CREATE FUNCTION f(x INT) RETURNS VARCHAR(5) DETERMINISTIC BEGIN RETURN CASE x WHEN 1 THEN 'a' ELSE 'b' END; END",
]


@pytest.mark.parametrize("program", PROGRAMS)
def test_a_stored_program_body_stays_whole_under_the_semicolon_delimiter(program: str) -> None:
    assert sql(f"CREATE TABLE t0 (a INT);\n{program};\nSELECT 9;") == [
        "CREATE TABLE t0 (a INT)",
        program,
        "SELECT 9",
    ]


@pytest.mark.parametrize(
    "program",
    [
        "CREATE OR REPLACE PROCEDURE p() BEGIN SELECT 1; SELECT 2; END",
        "CREATE OR REPLACE TRIGGER tr BEFORE INSERT ON t FOR EACH ROW BEGIN SET NEW.id = 1; END",
        "CREATE OR REPLACE DEFINER=`root`@`%` PROCEDURE p() BEGIN SELECT 1; SELECT 2; END",
        "CREATE AGGREGATE FUNCTION agg(x INT) RETURNS INT BEGIN DECLARE t INT DEFAULT 0; LOOP FETCH GROUP NEXT ROW; SET t = t + x; END LOOP; END",
        "CREATE PROCEDURE p() BEGIN FOR i IN 1..3 DO SELECT i; END FOR; lbl: FOR j IN 4..5 DO SELECT j; END FOR lbl; END",
    ],
)
def test_the_mariadb_heads_and_the_for_loop(program: str) -> None:
    assert sql(f"{program}; SELECT 9;", mariadb=True) == [program, "SELECT 9"]


@pytest.mark.parametrize(
    "script,expected",
    [
        ("CREATE PROCEDURE p() SELECT 1; SELECT 2;", ["CREATE PROCEDURE p() SELECT 1", "SELECT 2"]),
        (
            "CREATE TRIGGER tr BEFORE INSERT ON t FOR EACH ROW SET NEW.id = 1; SELECT 2;",
            ["CREATE TRIGGER tr BEFORE INSERT ON t FOR EACH ROW SET NEW.id = 1", "SELECT 2"],
        ),
        (
            "CREATE FUNCTION f() RETURNS INT RETURN 1; SELECT 2;",
            ["CREATE FUNCTION f() RETURNS INT RETURN 1", "SELECT 2"],
        ),
        ("CREATE TABLE begin_t (a INT); SELECT 2;", ["CREATE TABLE begin_t (a INT)", "SELECT 2"]),
        (
            "CREATE VIEW v AS SELECT 1 AS begin; SELECT 2;",
            ["CREATE VIEW v AS SELECT 1 AS begin", "SELECT 2"],
        ),
        (
            "ALTER PROCEDURE p SQL SECURITY INVOKER; SELECT 2;",
            ["ALTER PROCEDURE p SQL SECURITY INVOKER", "SELECT 2"],
        ),
        (
            "BEGIN NOT ATOMIC SELECT 1; SELECT 2; END;",
            ["BEGIN NOT ATOMIC SELECT 1", "SELECT 2", "END"],
        ),
        (
            "BEGIN; INSERT INTO t VALUES (1); COMMIT;",
            ["BEGIN", "INSERT INTO t VALUES (1)", "COMMIT"],
        ),
    ],
)
def test_statements_that_are_not_stored_programs_split_at_the_semicolon(
    script: str, expected: list[str]
) -> None:
    assert sql(script, mariadb=True) == expected


def test_the_extension_is_off_under_a_custom_delimiter() -> None:
    script = "DELIMITER //\nCREATE PROCEDURE p() BEGIN SELECT 1; END; SELECT 2//\nDELIMITER ;"
    assert sql(script) == ["CREATE PROCEDURE p() BEGIN SELECT 1; END; SELECT 2"]


def test_a_body_without_its_end_is_refused_at_the_end_of_the_script() -> None:
    script = "SELECT 0;\nCREATE PROCEDURE p() BEGIN SELECT 1; SELECT 2;\nSELECT 3;"
    with pytest.raises(UnsafeStatementSplitError, match="opened at line 2 is not closed"):
        scan_script(script)


def test_the_column_of_an_unterminated_comment_or_hint_is_in_its_line() -> None:
    with pytest.raises(UnsafeStatementSplitError, match="line 3, column 3"):
        scan_script("SELECT 1;\nSELECT 2;\n  /* open")
    with pytest.raises(UnsafeStatementSplitError, match="hint starting at line 3, column 3"):
        scan_script("SELECT 1;\nSELECT 2;\n  /*+ open")


def test_the_statement_after_a_body_gets_its_own_line() -> None:
    records = scan_script("CREATE PROCEDURE p() BEGIN\n  SELECT 1;\nEND;\nSELECT 2;")
    assert [(r.line, r.terminator) for r in records] == [(1, ";"), (4, ";")]


def test_an_unclosed_body_under_a_custom_delimiter_still_ends_at_the_delimiter() -> None:
    script = "DELIMITER //\nCREATE PROCEDURE p() BEGIN SELECT 1//\nDELIMITER ;\nSELECT 2;"
    assert sql(script) == ["CREATE PROCEDURE p() BEGIN SELECT 1", "SELECT 2"]


def test_crlf_becomes_lf_inside_strings_and_bodies_as_the_client_sends_it() -> None:
    script = "CREATE TABLE t (a VARCHAR(20));\r\nINSERT INTO t VALUES ('x\r\ny');\r\n"
    assert sql(script) == ["CREATE TABLE t (a VARCHAR(20))", "INSERT INTO t VALUES ('x\ny')"]
    body = (
        "DELIMITER //\r\nCREATE PROCEDURE p()\r\nBEGIN\r\n  SELECT 1;\r\nEND//\r\nDELIMITER ;\r\n"
    )
    assert sql(body) == ["CREATE PROCEDURE p()\nBEGIN\n  SELECT 1;\nEND"]


def test_a_carriage_return_alone_is_not_a_line_end_and_stays_in_a_literal() -> None:
    assert sql("SELECT 'a\rb';\r\n") == ["SELECT 'a\rb'"]
    assert sql("SELECT 1;\rSELECT 2;\r") == ["SELECT 1", "SELECT 2"]


@pytest.mark.parametrize("comment", ["# c", "-- c", "--", "/*! # c", "/*! -- c"])
@pytest.mark.parametrize("mariadb", [False, True])
def test_a_comment_line_that_holds_a_carriage_return_alone_is_refused(
    comment: str, mariadb: bool
) -> None:
    script = f"SELECT 1;\nSELECT 2; {comment}\rSELECT 3;\r"
    with pytest.raises(UnsafeStatementSplitError, match="comment on line 2 holds a carriage") as e:
        scan_script(script, mariadb=mariadb)
    assert "client reads the rest of the script as part of the comment" in str(e.value)
    assert sql("SELECT 1; # c\r\nSELECT 2;\r\n") == ["SELECT 1", "SELECT 2"]


@pytest.mark.parametrize(
    "script",
    [
        "DELIMITER //\rSELECT 1//\rDELIMITER ;\rSELECT 2;\r",
        "DELIMITER //\rSELECT 1//\nDELIMITER ;\n",
        "DELIMITER //\nSELECT 1//\nDELIMITER ;\rSELECT 2;\n",
    ],
)
def test_a_carriage_return_inside_a_delimiter_line_is_refused(script: str) -> None:
    with pytest.raises(UnsafeStatementSplitError, match="DELIMITER on line"):
        scan_script(script)
    with pytest.raises(UnsafeStatementSplitError, match="mariadb client reads the rest"):
        scan_script(script, mariadb=True)


def test_a_delimiter_that_follows_a_carriage_return_alone_is_refused() -> None:
    script = "SELECT 1;\rDELIMITER //\nSELECT 2//\nDELIMITER ;\nSELECT 3;\n"
    with pytest.raises(UnsafeStatementSplitError, match="not the first word"):
        scan_script(script)


HINT_ACROSS_LINES = "SELECT /*+\n NO_BKA(t1) ;\n*/ 1 AS a;\nSELECT 2 AS b;\n"


def test_mysql_hides_the_delimiter_in_a_hint_on_its_opening_line_only() -> None:
    assert sql(HINT_ACROSS_LINES) == ["SELECT /*+\n NO_BKA(t1)", "*/ 1 AS a", "SELECT 2 AS b"]


def test_mariadb_reads_a_hint_as_one_comment_across_lines() -> None:
    assert sql(HINT_ACROSS_LINES, mariadb=True) == [
        "SELECT /*+\n NO_BKA(t1) ;\n*/ 1 AS a",
        "SELECT 2 AS b",
    ]


@pytest.mark.parametrize("mariadb", [False, True])
def test_a_hint_across_lines_is_one_statement_when_the_delimiter_is_on_its_first_line_or_absent(
    mariadb: bool,
) -> None:
    clean = "SELECT /*+\n NO_BKA(t1)\n*/ 1 AS a;\nSELECT 2 AS b;\n"
    assert sql(clean, mariadb=mariadb) == ["SELECT /*+\n NO_BKA(t1)\n*/ 1 AS a", "SELECT 2 AS b"]
    opening = "SELECT /*+ ;\n NO_BKA(t1) */ 1 AS a;\nSELECT 2 AS b;\n"
    assert sql(opening, mariadb=mariadb) == ["SELECT /*+ ;\n NO_BKA(t1) */ 1 AS a", "SELECT 2 AS b"]


@pytest.mark.parametrize("mariadb", [False, True])
def test_a_hint_that_is_never_closed_is_refused(mariadb: bool) -> None:
    with pytest.raises(UnsafeStatementSplitError, match="unterminated"):
        scan_script("SELECT /*+ x\n;\nSELECT 3;\n", mariadb=mariadb)
