"""The stored-program body rule: a ``;`` inside BEGIN ... END of a stored program does not end the statement."""

from dataclasses import replace
from pathlib import Path

import pytest

from dblift.core.exceptions import UnsafeStatementSplitError, UnsupportedMetaCommandError
from dblift.core.sql_parser.lexical_engine import LexicalEngine
from dblift.core.sql_parser.lexical_spec import LexicalSpec
from dblift.core.sql_parser.program_body import ProgramBody
from dblift.db.plugins.mariadb.lexical_spec import MARIADB_SPEC
from dblift.db.plugins.mysql.parser.lexical_spec import MYSQL_PROGRAMS, MYSQL_RULES, MYSQL_SPEC
from tests.support.splitter_spec.spec_tables import load_conformance_rows
from tests.support.splitter_spec.splitting import SplitOutcome

BOTH = pytest.mark.parametrize("spec", [MYSQL_SPEC, MARIADB_SPEC], ids=["mysql", "mariadb"])
SPEC_DIR = Path(__file__).resolve().parents[4] / "docs" / "sql-parsing"
ROW_BASES = {str(n) for n in (4, 5, 6, 7, 22)} | {str(n) for n in range(66, 80)}
ROW_IDS = {"M3", "M4", "M5", "M6"}
ROWS = [
    row
    for row in load_conformance_rows(SPEC_DIR)
    if row.dialect in ("mysql", "mariadb")
    and (row.row_id.rstrip("abcdefghijklmnopqrstuvwxyz") in ROW_BASES or row.row_id in ROW_IDS)
]
RUNS = [
    pytest.param(
        MYSQL_SPEC if row.dialect == "mysql" else MARIADB_SPEC,
        row,
        id=f"{row.dialect}-{row.row_id}",
    )
    for row in ROWS
] + [
    pytest.param(MARIADB_SPEC, row, id=f"mariadb-on-mysql-{row.row_id}")
    for row in ROWS
    if row.dialect == "mysql"
]


def observed(spec: LexicalSpec, script: str) -> list:
    try:
        return ["ok", LexicalEngine(spec).split_statements(script)]
    except (UnsafeStatementSplitError, UnsupportedMetaCommandError) as error:
        return ["error", type(error).__name__, str(error)]


def varied(**changes: object) -> LexicalSpec:
    program = replace(MYSQL_PROGRAMS, **changes)
    return replace(MYSQL_SPEC, delimiter_script=replace(MYSQL_RULES, program=program))


@pytest.mark.parametrize("spec, row", RUNS)
def test_spec_rows_are_read_by_the_engine(spec, row):
    try:
        outcome = SplitOutcome(statements=tuple(LexicalEngine(spec).split_statements(row.script)))
    except Exception as exc:  # noqa: BLE001 - the class is what the row expects
        outcome = SplitOutcome(statements=(), error=type(exc).__name__, detail=str(exc))
    assert outcome.matches(row.expectation), (row.row_id, row.script)


PROGRAMS = [
    [
        "CREATE PROCEDURE p() BEGIN SELECT 1; SELECT 2; END; SELECT 3;",
        ["ok", ["CREATE PROCEDURE p() BEGIN SELECT 1; SELECT 2; END", "SELECT 3"]],
        ["ok", ["CREATE PROCEDURE p() BEGIN SELECT 1; SELECT 2; END", "SELECT 3"]],
    ],
    [
        "CREATE DEFINER=`root`@`%` PROCEDURE p() BEGIN SELECT 1; SELECT 2; END; SELECT 3;",
        [
            "ok",
            ["CREATE DEFINER=`root`@`%` PROCEDURE p() BEGIN SELECT 1; SELECT 2; END", "SELECT 3"],
        ],
        [
            "ok",
            ["CREATE DEFINER=`root`@`%` PROCEDURE p() BEGIN SELECT 1; SELECT 2; END", "SELECT 3"],
        ],
    ],
    [
        "CREATE DEFINER = CURRENT_USER() PROCEDURE p() BEGIN SELECT 1; SELECT 2; END; SELECT 3;",
        [
            "ok",
            [
                "CREATE DEFINER = CURRENT_USER() PROCEDURE p() BEGIN SELECT 1; SELECT 2; END",
                "SELECT 3",
            ],
        ],
        [
            "ok",
            [
                "CREATE DEFINER = CURRENT_USER() PROCEDURE p() BEGIN SELECT 1; SELECT 2; END",
                "SELECT 3",
            ],
        ],
    ],
    [
        "CREATE DEFINER = CURRENT_USER PROCEDURE p() BEGIN SELECT 1; SELECT 2; END; SELECT 3;",
        [
            "ok",
            [
                "CREATE DEFINER = CURRENT_USER PROCEDURE p() BEGIN SELECT 1; SELECT 2; END",
                "SELECT 3",
            ],
        ],
        [
            "ok",
            [
                "CREATE DEFINER = CURRENT_USER PROCEDURE p() BEGIN SELECT 1; SELECT 2; END",
                "SELECT 3",
            ],
        ],
    ],
    [
        "CREATE DEFINER = u@h PROCEDURE p() BEGIN SELECT 1; SELECT 2; END; SELECT 3;",
        ["ok", ["CREATE DEFINER = u@h PROCEDURE p() BEGIN SELECT 1; SELECT 2; END", "SELECT 3"]],
        ["ok", ["CREATE DEFINER = u@h PROCEDURE p() BEGIN SELECT 1; SELECT 2; END", "SELECT 3"]],
    ],
    [
        "CREATE DEFINER = u PROCEDURE p() BEGIN SELECT 1; SELECT 2; END; SELECT 3;",
        ["ok", ["CREATE DEFINER = u PROCEDURE p() BEGIN SELECT 1; SELECT 2; END", "SELECT 3"]],
        ["ok", ["CREATE DEFINER = u PROCEDURE p() BEGIN SELECT 1; SELECT 2; END", "SELECT 3"]],
    ],
    [
        "CREATE DEFINER = 'u'@'h' FUNCTION f() RETURNS INT BEGIN SELECT 1; SELECT 2; END; SELECT 3;",
        [
            "ok",
            [
                "CREATE DEFINER = 'u'@'h' FUNCTION f() RETURNS INT BEGIN SELECT 1; SELECT 2; END",
                "SELECT 3",
            ],
        ],
        [
            "ok",
            [
                "CREATE DEFINER = 'u'@'h' FUNCTION f() RETURNS INT BEGIN SELECT 1; SELECT 2; END",
                "SELECT 3",
            ],
        ],
    ],
    [
        "CREATE DEFINER = (PROCEDURE p() BEGIN SELECT 1; SELECT 2; END; SELECT 3;",
        ["ok", ["CREATE DEFINER = (PROCEDURE p() BEGIN SELECT 1", "SELECT 2", "END", "SELECT 3"]],
        ["ok", ["CREATE DEFINER = (PROCEDURE p() BEGIN SELECT 1", "SELECT 2", "END", "SELECT 3"]],
    ],
    [
        "CREATE DEFINER = u, PROCEDURE p() BEGIN SELECT 1; SELECT 2; END; SELECT 3;",
        ["ok", ["CREATE DEFINER = u, PROCEDURE p() BEGIN SELECT 1", "SELECT 2", "END", "SELECT 3"]],
        ["ok", ["CREATE DEFINER = u, PROCEDURE p() BEGIN SELECT 1", "SELECT 2", "END", "SELECT 3"]],
    ],
    [
        "CREATE DEFINER = CURRENT_USER( PROCEDURE p() BEGIN SELECT 1; SELECT 2; END; SELECT 3;",
        [
            "ok",
            [
                "CREATE DEFINER = CURRENT_USER( PROCEDURE p() BEGIN SELECT 1",
                "SELECT 2",
                "END",
                "SELECT 3",
            ],
        ],
        [
            "ok",
            [
                "CREATE DEFINER = CURRENT_USER( PROCEDURE p() BEGIN SELECT 1",
                "SELECT 2",
                "END",
                "SELECT 3",
            ],
        ],
    ],
    [
        "CREATE DEFINER = CURRENT_USER() x PROCEDURE p() BEGIN SELECT 1; SELECT 2; END; SELECT 3;",
        [
            "ok",
            [
                "CREATE DEFINER = CURRENT_USER() x PROCEDURE p() BEGIN SELECT 1",
                "SELECT 2",
                "END",
                "SELECT 3",
            ],
        ],
        [
            "ok",
            [
                "CREATE DEFINER = CURRENT_USER() x PROCEDURE p() BEGIN SELECT 1",
                "SELECT 2",
                "END",
                "SELECT 3",
            ],
        ],
    ],
    [
        "CREATE DEFINER = u@ PROCEDURE p() BEGIN SELECT 1; SELECT 2; END; SELECT 3;",
        ["ok", ["CREATE DEFINER = u@ PROCEDURE p() BEGIN SELECT 1", "SELECT 2", "END", "SELECT 3"]],
        ["ok", ["CREATE DEFINER = u@ PROCEDURE p() BEGIN SELECT 1", "SELECT 2", "END", "SELECT 3"]],
    ],
    [
        "CREATE DEFINER = u@h, PROCEDURE p() BEGIN SELECT 1; SELECT 2; END; SELECT 3;",
        [
            "ok",
            ["CREATE DEFINER = u@h, PROCEDURE p() BEGIN SELECT 1", "SELECT 2", "END", "SELECT 3"],
        ],
        [
            "ok",
            ["CREATE DEFINER = u@h, PROCEDURE p() BEGIN SELECT 1", "SELECT 2", "END", "SELECT 3"],
        ],
    ],
    [
        "CREATE OR REPLACE FUNCTION f() RETURNS INT BEGIN SELECT 1; SELECT 2; END; SELECT 3;",
        [
            "ok",
            [
                "CREATE OR REPLACE FUNCTION f() RETURNS INT BEGIN SELECT 1; SELECT 2; END",
                "SELECT 3",
            ],
        ],
        [
            "ok",
            [
                "CREATE OR REPLACE FUNCTION f() RETURNS INT BEGIN SELECT 1; SELECT 2; END",
                "SELECT 3",
            ],
        ],
    ],
    [
        "CREATE OR REPLACE OR REPLACE FUNCTION f() RETURNS INT BEGIN SELECT 1; SELECT 2; END; SELECT "
        "3;",
        [
            "ok",
            [
                "CREATE OR REPLACE OR REPLACE FUNCTION f() RETURNS INT BEGIN SELECT 1; SELECT 2; END",
                "SELECT 3",
            ],
        ],
        [
            "ok",
            [
                "CREATE OR REPLACE OR REPLACE FUNCTION f() RETURNS INT BEGIN SELECT 1; SELECT 2; END",
                "SELECT 3",
            ],
        ],
    ],
    [
        "CREATE AGGREGATE FUNCTION g() RETURNS INT BEGIN SELECT 1; SELECT 2; END; SELECT 3;",
        [
            "ok",
            ["CREATE AGGREGATE FUNCTION g() RETURNS INT BEGIN SELECT 1; SELECT 2; END", "SELECT 3"],
        ],
        [
            "ok",
            ["CREATE AGGREGATE FUNCTION g() RETURNS INT BEGIN SELECT 1; SELECT 2; END", "SELECT 3"],
        ],
    ],
    [
        "ALTER AGGREGATE FUNCTION g() BEGIN SELECT 1; SELECT 2; END; SELECT 3;",
        ["ok", ["ALTER AGGREGATE FUNCTION g() BEGIN SELECT 1", "SELECT 2", "END", "SELECT 3"]],
        ["ok", ["ALTER AGGREGATE FUNCTION g() BEGIN SELECT 1", "SELECT 2", "END", "SELECT 3"]],
    ],
    [
        "CREATE EVENT e ON SCHEDULE EVERY 1 DAY DO BEGIN SELECT 1; SELECT 2; END; SELECT 3;",
        [
            "ok",
            ["CREATE EVENT e ON SCHEDULE EVERY 1 DAY DO BEGIN SELECT 1; SELECT 2; END", "SELECT 3"],
        ],
        [
            "ok",
            ["CREATE EVENT e ON SCHEDULE EVERY 1 DAY DO BEGIN SELECT 1; SELECT 2; END", "SELECT 3"],
        ],
    ],
    [
        "ALTER EVENT e DO BEGIN SELECT 1; SELECT 2; END; SELECT 3;",
        ["ok", ["ALTER EVENT e DO BEGIN SELECT 1; SELECT 2; END", "SELECT 3"]],
        ["ok", ["ALTER EVENT e DO BEGIN SELECT 1; SELECT 2; END", "SELECT 3"]],
    ],
    [
        "ALTER PROCEDURE p BEGIN SELECT 1; SELECT 2; END; SELECT 3;",
        ["ok", ["ALTER PROCEDURE p BEGIN SELECT 1", "SELECT 2", "END", "SELECT 3"]],
        ["ok", ["ALTER PROCEDURE p BEGIN SELECT 1", "SELECT 2", "END", "SELECT 3"]],
    ],
    [
        "ALTER DEFINER = u EVENT e DO BEGIN SELECT 1; SELECT 2; END; SELECT 3;",
        ["ok", ["ALTER DEFINER = u EVENT e DO BEGIN SELECT 1; SELECT 2; END", "SELECT 3"]],
        ["ok", ["ALTER DEFINER = u EVENT e DO BEGIN SELECT 1; SELECT 2; END", "SELECT 3"]],
    ],
    [
        "CREATE TRIGGER tr BEFORE INSERT ON t FOR EACH ROW BEGIN SELECT 1; SELECT 2; END; SELECT 3;",
        [
            "ok",
            [
                "CREATE TRIGGER tr BEFORE INSERT ON t FOR EACH ROW BEGIN SELECT 1; SELECT 2; END",
                "SELECT 3",
            ],
        ],
        [
            "ok",
            [
                "CREATE TRIGGER tr BEFORE INSERT ON t FOR EACH ROW BEGIN SELECT 1; SELECT 2; END",
                "SELECT 3",
            ],
        ],
    ],
    [
        "CREATE TABLE t (begin INT); SELECT 3;",
        ["ok", ["CREATE TABLE t (begin INT)", "SELECT 3"]],
        ["ok", ["CREATE TABLE t (begin INT)", "SELECT 3"]],
    ],
    [
        "CREATE PROCEDURE p() SELECT 1; SELECT 3;",
        ["ok", ["CREATE PROCEDURE p() SELECT 1", "SELECT 3"]],
        ["ok", ["CREATE PROCEDURE p() SELECT 1", "SELECT 3"]],
    ],
    [
        "CREATE VIEW v AS SELECT 1 BEGIN SELECT 1; SELECT 2; END; SELECT 3;",
        ["ok", ["CREATE VIEW v AS SELECT 1 BEGIN SELECT 1", "SELECT 2", "END", "SELECT 3"]],
        ["ok", ["CREATE VIEW v AS SELECT 1 BEGIN SELECT 1", "SELECT 2", "END", "SELECT 3"]],
    ],
    [
        "create procedure p() begin select 1; select 2; end; select 3;",
        ["ok", ["create procedure p() begin select 1; select 2; end", "select 3"]],
        ["ok", ["create procedure p() begin select 1; select 2; end", "select 3"]],
    ],
    [
        "CREATE DEFINER='a''b'@'%' PROCEDURE p() BEGIN SELECT 1; END; SELECT 2;",
        ["ok", ["CREATE DEFINER='a''b'@'%' PROCEDURE p() BEGIN SELECT 1", "END", "SELECT 2"]],
        ["ok", ["CREATE DEFINER='a''b'@'%' PROCEDURE p() BEGIN SELECT 1", "END", "SELECT 2"]],
    ],
    [
        "CREATE DEFINER=`a``b`@`%` PROCEDURE p() BEGIN SELECT 1; END; SELECT 2;",
        ["ok", ["CREATE DEFINER=`a``b`@`%` PROCEDURE p() BEGIN SELECT 1", "END", "SELECT 2"]],
        ["ok", ["CREATE DEFINER=`a``b`@`%` PROCEDURE p() BEGIN SELECT 1", "END", "SELECT 2"]],
    ],
    [
        "CREATE DEFINER='a'@'b''c' PROCEDURE p() BEGIN SELECT 1; END; SELECT 2;",
        ["ok", ["CREATE DEFINER='a'@'b''c' PROCEDURE p() BEGIN SELECT 1", "END", "SELECT 2"]],
        ["ok", ["CREATE DEFINER='a'@'b''c' PROCEDURE p() BEGIN SELECT 1", "END", "SELECT 2"]],
    ],
    [
        "CREATE PROCEDURE p() BEGIN SELECT 1; BEGIN SELECT 2; END; SELECT 3; END; SELECT 4;",
        [
            "ok",
            ["CREATE PROCEDURE p() BEGIN SELECT 1; BEGIN SELECT 2; END; SELECT 3; END", "SELECT 4"],
        ],
        [
            "ok",
            ["CREATE PROCEDURE p() BEGIN SELECT 1; BEGIN SELECT 2; END; SELECT 3; END", "SELECT 4"],
        ],
    ],
    [
        "CREATE PROCEDURE p() lbl: BEGIN w: WHILE 1 DO SET @i = 1; END WHILE w; END lbl; SELECT 3;",
        [
            "ok",
            [
                "CREATE PROCEDURE p() lbl: BEGIN w: WHILE 1 DO SET @i = 1; END WHILE w; END lbl",
                "SELECT 3",
            ],
        ],
        [
            "ok",
            [
                "CREATE PROCEDURE p() lbl: BEGIN w: WHILE 1 DO SET @i = 1; END WHILE w; END lbl",
                "SELECT 3",
            ],
        ],
    ],
    [
        "CREATE PROCEDURE p() BEGIN IF 1 THEN SELECT 1; ELSE SELECT 2; END IF; END; SELECT 3;",
        [
            "ok",
            [
                "CREATE PROCEDURE p() BEGIN IF 1 THEN SELECT 1; ELSE SELECT 2; END IF; END",
                "SELECT 3",
            ],
        ],
        [
            "ok",
            [
                "CREATE PROCEDURE p() BEGIN IF 1 THEN SELECT 1; ELSE SELECT 2; END IF; END",
                "SELECT 3",
            ],
        ],
    ],
    [
        "CREATE PROCEDURE p() BEGIN IF 1 THEN IF 2 THEN SELECT 1; END IF; END IF; END; SELECT 3;",
        [
            "ok",
            [
                "CREATE PROCEDURE p() BEGIN IF 1 THEN IF 2 THEN SELECT 1; END IF; END IF; END",
                "SELECT 3",
            ],
        ],
        [
            "ok",
            [
                "CREATE PROCEDURE p() BEGIN IF 1 THEN IF 2 THEN SELECT 1; END IF; END IF; END",
                "SELECT 3",
            ],
        ],
    ],
    [
        "CREATE PROCEDURE p() BEGIN LOOP SELECT 1; END LOOP; END; SELECT 3;",
        ["ok", ["CREATE PROCEDURE p() BEGIN LOOP SELECT 1; END LOOP; END", "SELECT 3"]],
        ["ok", ["CREATE PROCEDURE p() BEGIN LOOP SELECT 1; END LOOP; END", "SELECT 3"]],
    ],
    [
        "CREATE PROCEDURE p() BEGIN REPEAT SET @i = 1; UNTIL 1 END REPEAT; END; SELECT 3;",
        [
            "ok",
            ["CREATE PROCEDURE p() BEGIN REPEAT SET @i = 1; UNTIL 1 END REPEAT; END", "SELECT 3"],
        ],
        [
            "ok",
            ["CREATE PROCEDURE p() BEGIN REPEAT SET @i = 1; UNTIL 1 END REPEAT; END", "SELECT 3"],
        ],
    ],
    [
        "CREATE PROCEDURE p() BEGIN FOR i IN 1..3 DO SELECT i; END FOR; END; SELECT 3;",
        ["ok", ["CREATE PROCEDURE p() BEGIN FOR i IN 1..3 DO SELECT i; END FOR; END", "SELECT 3"]],
        ["ok", ["CREATE PROCEDURE p() BEGIN FOR i IN 1..3 DO SELECT i; END FOR; END", "SELECT 3"]],
    ],
    [
        "CREATE PROCEDURE p() BEGIN WHILE 1 DO SELECT 1; END WHILE; END; SELECT 3;",
        ["ok", ["CREATE PROCEDURE p() BEGIN WHILE 1 DO SELECT 1; END WHILE; END", "SELECT 3"]],
        ["ok", ["CREATE PROCEDURE p() BEGIN WHILE 1 DO SELECT 1; END WHILE; END", "SELECT 3"]],
    ],
    [
        "CREATE PROCEDURE p() BEGIN CASE WHEN 1 THEN SELECT 1; ELSE SELECT 2; END CASE; END; SELECT "
        "3;",
        [
            "ok",
            [
                "CREATE PROCEDURE p() BEGIN CASE WHEN 1 THEN SELECT 1; ELSE SELECT 2; END CASE; END",
                "SELECT 3",
            ],
        ],
        [
            "ok",
            [
                "CREATE PROCEDURE p() BEGIN CASE WHEN 1 THEN SELECT 1; ELSE SELECT 2; END CASE; END",
                "SELECT 3",
            ],
        ],
    ],
    [
        "CREATE PROCEDURE p() BEGIN SELECT CASE WHEN 1 THEN 2 END; END; SELECT 3;",
        ["ok", ["CREATE PROCEDURE p() BEGIN SELECT CASE WHEN 1 THEN 2 END; END", "SELECT 3"]],
        ["ok", ["CREATE PROCEDURE p() BEGIN SELECT CASE WHEN 1 THEN 2 END; END", "SELECT 3"]],
    ],
    [
        "CREATE PROCEDURE p() BEGIN CASE WHEN 1 THEN SELECT CASE WHEN 2 THEN 3 END; END CASE; END; "
        "SELECT 4;",
        [
            "ok",
            [
                "CREATE PROCEDURE p() BEGIN CASE WHEN 1 THEN SELECT CASE WHEN 2 THEN 3 END; END CASE; END",
                "SELECT 4",
            ],
        ],
        [
            "ok",
            [
                "CREATE PROCEDURE p() BEGIN CASE WHEN 1 THEN SELECT CASE WHEN 2 THEN 3 END; END CASE; END",
                "SELECT 4",
            ],
        ],
    ],
    [
        "CREATE PROCEDURE p() BEGIN SELECT IF(1, 2, 3); SELECT REPEAT('a', 2); END; SELECT 3;",
        [
            "ok",
            [
                "CREATE PROCEDURE p() BEGIN SELECT IF(1, 2, 3); SELECT REPEAT('a', 2); END",
                "SELECT 3",
            ],
        ],
        [
            "ok",
            [
                "CREATE PROCEDURE p() BEGIN SELECT IF(1, 2, 3); SELECT REPEAT('a', 2); END",
                "SELECT 3",
            ],
        ],
    ],
    [
        "CREATE PROCEDURE p() BEGIN SELECT (BEGIN); END; SELECT 3;",
        ["ok", ["CREATE PROCEDURE p() BEGIN SELECT (BEGIN); END", "SELECT 3"]],
        ["ok", ["CREATE PROCEDURE p() BEGIN SELECT (BEGIN); END", "SELECT 3"]],
    ],
    [
        "CREATE PROCEDURE p() BEGIN SELECT t.end, 1; END; SELECT 3;",
        ["ok", ["CREATE PROCEDURE p() BEGIN SELECT t.end, 1; END", "SELECT 3"]],
        ["ok", ["CREATE PROCEDURE p() BEGIN SELECT t.end, 1; END", "SELECT 3"]],
    ],
    [
        "CREATE PROCEDURE p() BEGIN SELECT @begin, @@end; END; SELECT 3;",
        ["ok", ["CREATE PROCEDURE p() BEGIN SELECT @begin, @@end; END", "SELECT 3"]],
        ["ok", ["CREATE PROCEDURE p() BEGIN SELECT @begin, @@end; END", "SELECT 3"]],
    ],
    [
        "CREATE PROCEDURE p() BEGIN SELECT x .END; END; SELECT 3;",
        ["ok", ["CREATE PROCEDURE p() BEGIN SELECT x .END; END", "SELECT 3"]],
        ["ok", ["CREATE PROCEDURE p() BEGIN SELECT x .END; END", "SELECT 3"]],
    ],
    [
        "CREATE PROCEDURE p() BEGIN SELECT `end`, 'end'; END; SELECT 3;",
        ["ok", ["CREATE PROCEDURE p() BEGIN SELECT `end`, 'end'; END", "SELECT 3"]],
        ["ok", ["CREATE PROCEDURE p() BEGIN SELECT `end`, 'end'; END", "SELECT 3"]],
    ],
    [
        "CREATE PROCEDURE p() BEGIN SELECT t. # c\nEND; SELECT 2; END; SELECT 3;",
        ["ok", ["CREATE PROCEDURE p() BEGIN SELECT t. # c\nEND; SELECT 2; END", "SELECT 3"]],
        ["ok", ["CREATE PROCEDURE p() BEGIN SELECT t. # c\nEND; SELECT 2; END", "SELECT 3"]],
    ],
    [
        "CREATE PROCEDURE p() BEGIN SELECT t.-- c\nEND; SELECT 2; END; SELECT 3;",
        ["ok", ["CREATE PROCEDURE p() BEGIN SELECT t.-- c\nEND; SELECT 2; END", "SELECT 3"]],
        ["ok", ["CREATE PROCEDURE p() BEGIN SELECT t.-- c\nEND; SELECT 2; END", "SELECT 3"]],
    ],
    [
        "CREATE PROCEDURE p() BEGIN SELECT t./* c */END; SELECT 2; END; SELECT 3;",
        ["ok", ["CREATE PROCEDURE p() BEGIN SELECT t./* c */END; SELECT 2; END", "SELECT 3"]],
        ["ok", ["CREATE PROCEDURE p() BEGIN SELECT t./* c */END; SELECT 2; END", "SELECT 3"]],
    ],
    [
        "CREATE PROCEDURE p() BEGIN SELECT t./* a\nb */END; SELECT 2; END; SELECT 3;",
        [
            "ok",
            ["CREATE PROCEDURE p() BEGIN SELECT t./* a\nb */END", "SELECT 2", "END", "SELECT 3"],
        ],
        [
            "ok",
            ["CREATE PROCEDURE p() BEGIN SELECT t./* a\nb */END", "SELECT 2", "END", "SELECT 3"],
        ],
    ],
    [
        "CREATE PROCEDURE p() BEGIN SELECT t.\nEND; SELECT 2; END; SELECT 3;",
        ["ok", ["CREATE PROCEDURE p() BEGIN SELECT t.\nEND", "SELECT 2", "END", "SELECT 3"]],
        ["ok", ["CREATE PROCEDURE p() BEGIN SELECT t.\nEND", "SELECT 2", "END", "SELECT 3"]],
    ],
    [
        "CREATE PROCEDURE p() BEGIN SELECT t.'a'END; SELECT 2; END; SELECT 3;",
        ["ok", ["CREATE PROCEDURE p() BEGIN SELECT t.'a'END", "SELECT 2", "END", "SELECT 3"]],
        ["ok", ["CREATE PROCEDURE p() BEGIN SELECT t.'a'END", "SELECT 2", "END", "SELECT 3"]],
    ],
    [
        "CREATE PROCEDURE p() BEGIN SELECT \xe9nd; END; SELECT 3;",
        ["ok", ["CREATE PROCEDURE p() BEGIN SELECT \xe9nd; END", "SELECT 3"]],
        ["ok", ["CREATE PROCEDURE p() BEGIN SELECT \xe9nd; END", "SELECT 3"]],
    ],
    [
        "CREATE PROCEDURE p() BEGIN SELECT a\xa0END; SELECT 2; END; SELECT 3;",
        ["ok", ["CREATE PROCEDURE p() BEGIN SELECT a\xa0END; SELECT 2; END", "SELECT 3"]],
        ["ok", ["CREATE PROCEDURE p() BEGIN SELECT a\xa0END; SELECT 2; END", "SELECT 3"]],
    ],
    [
        "CREATE PROCEDURE p() BEGIN SELECT 1; END\xa0; SELECT 3;",
        [
            "error",
            "UnsafeStatementSplitError",
            "stored-program body opened at line 1 is not closed before the end of the script",
        ],
        [
            "error",
            "UnsafeStatementSplitError",
            "stored-program body opened at line 1 is not closed before the end of the script",
        ],
    ],
    [
        "CREATE PROCEDURE p() BEGIN SELECT 1;\nexit\nSELECT 2; END; SELECT 3;",
        ["ok", ["CREATE PROCEDURE p() BEGIN SELECT 1;\nexit\nSELECT 2; END", "SELECT 3"]],
        ["ok", ["CREATE PROCEDURE p() BEGIN SELECT 1;\nexit\nSELECT 2; END", "SELECT 3"]],
    ],
    [
        "CREATE PROCEDURE p() BEGIN\nSELECT 1;\nstatus\nEND; SELECT 3;",
        ["ok", ["CREATE PROCEDURE p() BEGIN\nSELECT 1;\nstatus\nEND", "SELECT 3"]],
        ["ok", ["CREATE PROCEDURE p() BEGIN\nSELECT 1;\nstatus\nEND", "SELECT 3"]],
    ],
    [
        "CREATE PROCEDURE p() BEGIN SELECT 1;",
        [
            "error",
            "UnsafeStatementSplitError",
            "stored-program body opened at line 1 is not closed before the end of the script",
        ],
        [
            "error",
            "UnsafeStatementSplitError",
            "stored-program body opened at line 1 is not closed before the end of the script",
        ],
    ],
    [
        "CREATE PROCEDURE p() BEGIN SELECT 1; END",
        ["ok", ["CREATE PROCEDURE p() BEGIN SELECT 1; END"]],
        ["ok", ["CREATE PROCEDURE p() BEGIN SELECT 1; END"]],
    ],
    [
        "CREATE PROCEDURE p() BEGIN SELECT 1; /* END; */ SELECT 2; END; SELECT 3;",
        ["ok", ["CREATE PROCEDURE p() BEGIN SELECT 1; /* END; */ SELECT 2; END", "SELECT 3"]],
        ["ok", ["CREATE PROCEDURE p() BEGIN SELECT 1; /* END; */ SELECT 2; END", "SELECT 3"]],
    ],
    [
        "CREATE PROCEDURE p() BEGIN SELECT 'END;'; END; SELECT 3;",
        ["ok", ["CREATE PROCEDURE p() BEGIN SELECT 'END;'; END", "SELECT 3"]],
        ["ok", ["CREATE PROCEDURE p() BEGIN SELECT 'END;'; END", "SELECT 3"]],
    ],
    [
        "CREATE PROCEDURE p() BEGIN SET sql_mode='NO_BACKSLASH_ESCAPES'; END; SELECT 3;",
        [
            "error",
            "UnsafeStatementSplitError",
            "the statement on line 1 sets NO_BACKSLASH_ESCAPES: the mysql client then reads backslashes "
            "as ordinary characters, this splitter cannot follow",
        ],
        [
            "error",
            "UnsafeStatementSplitError",
            "the statement on line 1 sets NO_BACKSLASH_ESCAPES: the mariadb client then reads "
            "backslashes as ordinary characters, this splitter cannot follow",
        ],
    ],
    [
        "CREATE PROCEDURE p() BEGIN SELECT 'NO_BACKSLASH_ESCAPES'; END; SELECT 3;",
        ["ok", ["CREATE PROCEDURE p() BEGIN SELECT 'NO_BACKSLASH_ESCAPES'; END", "SELECT 3"]],
        ["ok", ["CREATE PROCEDURE p() BEGIN SELECT 'NO_BACKSLASH_ESCAPES'; END", "SELECT 3"]],
    ],
    [
        "CREATE PROCEDURE p() BEGIN SELECT 1 /*! ; */; END; SELECT 3;",
        ["ok", ["CREATE PROCEDURE p() BEGIN SELECT 1 /*! ; */; END", "SELECT 3"]],
        ["ok", ["CREATE PROCEDURE p() BEGIN SELECT 1 /*! ; */; END", "SELECT 3"]],
    ],
    [
        "CREATE PROCEDURE p() BEGIN SELECT 1; END;;\nSELECT 3;",
        ["ok", ["CREATE PROCEDURE p() BEGIN SELECT 1; END", "SELECT 3"]],
        ["ok", ["CREATE PROCEDURE p() BEGIN SELECT 1; END", "SELECT 3"]],
    ],
    [
        "DELIMITER //\nCREATE PROCEDURE p() BEGIN SELECT 1; SELECT 2; END//\nDELIMITER ;\nSELECT 3;",
        ["ok", ["CREATE PROCEDURE p() BEGIN SELECT 1; SELECT 2; END", "SELECT 3"]],
        ["ok", ["CREATE PROCEDURE p() BEGIN SELECT 1; SELECT 2; END", "SELECT 3"]],
    ],
    [
        "DELIMITER $$\nCREATE PROCEDURE p() BEGIN SELECT 1; END;\nSELECT 3$$\n",
        ["ok", ["CREATE PROCEDURE p() BEGIN SELECT 1; END;\nSELECT 3"]],
        ["ok", ["CREATE PROCEDURE p() BEGIN SELECT 1; END;\nSELECT 3"]],
    ],
    [
        "BEGIN NOT ATOMIC SELECT 1; END; SELECT 3;",
        ["ok", ["BEGIN NOT ATOMIC SELECT 1", "END", "SELECT 3"]],
        ["ok", ["BEGIN NOT ATOMIC SELECT 1", "END", "SELECT 3"]],
    ],
    [
        "BEGIN; SELECT 1; COMMIT;",
        ["ok", ["BEGIN", "SELECT 1", "COMMIT"]],
        ["ok", ["BEGIN", "SELECT 1", "COMMIT"]],
    ],
    [
        "CREATE PROCEDURE p() BEGIN SELECT 1; END; CREATE PROCEDURE q() BEGIN SELECT 2; END; SELECT "
        "3;",
        [
            "ok",
            [
                "CREATE PROCEDURE p() BEGIN SELECT 1; END",
                "CREATE PROCEDURE q() BEGIN SELECT 2; END",
                "SELECT 3",
            ],
        ],
        [
            "ok",
            [
                "CREATE PROCEDURE p() BEGIN SELECT 1; END",
                "CREATE PROCEDURE q() BEGIN SELECT 2; END",
                "SELECT 3",
            ],
        ],
    ],
    [
        "CREATE PROCEDURE p() BEGIN END; SELECT 3;",
        ["ok", ["CREATE PROCEDURE p() BEGIN END", "SELECT 3"]],
        ["ok", ["CREATE PROCEDURE p() BEGIN END", "SELECT 3"]],
    ],
    [
        "CREATE PROCEDURE p() BEGIN SELECT 1; END END; SELECT 3;",
        ["ok", ["CREATE PROCEDURE p() BEGIN SELECT 1; END END", "SELECT 3"]],
        ["ok", ["CREATE PROCEDURE p() BEGIN SELECT 1; END END", "SELECT 3"]],
    ],
    [
        "CREATE PROCEDURE p() BEGIN CASE x WHEN 1 THEN SELECT 1; END CASE; END; SELECT 3;",
        [
            "ok",
            ["CREATE PROCEDURE p() BEGIN CASE x WHEN 1 THEN SELECT 1; END CASE; END", "SELECT 3"],
        ],
        [
            "ok",
            ["CREATE PROCEDURE p() BEGIN CASE x WHEN 1 THEN SELECT 1; END CASE; END", "SELECT 3"],
        ],
    ],
    [
        "CREATE PROCEDURE p() BEGIN IF x THEN SELECT 1; END IF; IF y THEN SELECT 2; END IF; END; "
        "SELECT 3;",
        [
            "ok",
            [
                "CREATE PROCEDURE p() BEGIN IF x THEN SELECT 1; END IF; IF y THEN SELECT 2; END IF; END",
                "SELECT 3",
            ],
        ],
        [
            "ok",
            [
                "CREATE PROCEDURE p() BEGIN IF x THEN SELECT 1; END IF; IF y THEN SELECT 2; END IF; END",
                "SELECT 3",
            ],
        ],
    ],
    [
        "CREATE PROCEDURE p() BEGIN DECLARE CONTINUE HANDLER FOR SQLEXCEPTION BEGIN SELECT 1; END; "
        "SELECT 2; END; SELECT 3;",
        [
            "ok",
            [
                "CREATE PROCEDURE p() BEGIN DECLARE CONTINUE HANDLER FOR SQLEXCEPTION BEGIN SELECT 1; END; "
                "SELECT 2; END",
                "SELECT 3",
            ],
        ],
        [
            "ok",
            [
                "CREATE PROCEDURE p() BEGIN DECLARE CONTINUE HANDLER FOR SQLEXCEPTION BEGIN SELECT 1; END; "
                "SELECT 2; END",
                "SELECT 3",
            ],
        ],
    ],
    [
        "CREATE PROCEDURE p() BEGIN IF(1) THEN SELECT 1; END IF; END; SELECT 3;",
        ["ok", ["CREATE PROCEDURE p() BEGIN IF(1) THEN SELECT 1; END IF; END", "SELECT 3"]],
        ["ok", ["CREATE PROCEDURE p() BEGIN IF(1) THEN SELECT 1; END IF; END", "SELECT 3"]],
    ],
    [
        "CREATE PROCEDURE p() BEGIN SELECT 1; END; CASE; SELECT 3;",
        ["ok", ["CREATE PROCEDURE p() BEGIN SELECT 1; END", "CASE", "SELECT 3"]],
        ["ok", ["CREATE PROCEDURE p() BEGIN SELECT 1; END", "CASE", "SELECT 3"]],
    ],
    [
        "ALTER AGGREGATE EVENT e DO BEGIN SELECT 1; END; SELECT 3;",
        ["ok", ["ALTER AGGREGATE EVENT e DO BEGIN SELECT 1", "END", "SELECT 3"]],
        ["ok", ["ALTER AGGREGATE EVENT e DO BEGIN SELECT 1", "END", "SELECT 3"]],
    ],
    [
        "CREATE PROCEDURE p() BEGIN SELECT CASE WHEN a THEN IF(b,1,2) ELSE 3 END; SELECT 4; END; "
        "SELECT 5;",
        [
            "ok",
            [
                "CREATE PROCEDURE p() BEGIN SELECT CASE WHEN a THEN IF(b,1,2) ELSE 3 END; SELECT 4; END",
                "SELECT 5",
            ],
        ],
        [
            "ok",
            [
                "CREATE PROCEDURE p() BEGIN SELECT CASE WHEN a THEN IF(b,1,2) ELSE 3 END; SELECT 4; END",
                "SELECT 5",
            ],
        ],
    ],
    [
        "DELIMITER //\nCREATE PROCEDURE p() BEGIN SELECT 1//\nSELECT 2//\n",
        ["ok", ["CREATE PROCEDURE p() BEGIN SELECT 1", "SELECT 2"]],
        ["ok", ["CREATE PROCEDURE p() BEGIN SELECT 1", "SELECT 2"]],
    ],
    [
        "CREATE PROCEDURE p() BEGIN SELECT CASE WHEN a THEN CASE WHEN b THEN IF(c,1,2) ELSE 3 END "
        "END; SELECT 4; END; SELECT 5;",
        [
            "ok",
            [
                "CREATE PROCEDURE p() BEGIN SELECT CASE WHEN a THEN CASE WHEN b THEN IF(c,1,2) ELSE 3 END "
                "END; SELECT 4; END",
                "SELECT 5",
            ],
        ],
        [
            "ok",
            [
                "CREATE PROCEDURE p() BEGIN SELECT CASE WHEN a THEN CASE WHEN b THEN IF(c,1,2) ELSE 3 END "
                "END; SELECT 4; END",
                "SELECT 5",
            ],
        ],
    ],
    [
        "CREATE PROCEDURE p() BEGIN SELECT 1 /*! END */; SELECT 2; END; SELECT 3;",
        ["ok", ["CREATE PROCEDURE p() BEGIN SELECT 1 /*! END */", "SELECT 2", "END", "SELECT 3"]],
        ["ok", ["CREATE PROCEDURE p() BEGIN SELECT 1 /*! END */", "SELECT 2", "END", "SELECT 3"]],
    ],
    [
        "CREATE /* c */ PROCEDURE p() BEGIN SELECT 1; END; SELECT 3;",
        ["ok", ["CREATE /* c */ PROCEDURE p() BEGIN SELECT 1; END", "SELECT 3"]],
        ["ok", ["CREATE /* c */ PROCEDURE p() BEGIN SELECT 1; END", "SELECT 3"]],
    ],
    [
        "DELIMITER //\nCREATE PROCEDURE p() BEGIN SELECT 1;",
        ["ok", ["CREATE PROCEDURE p() BEGIN SELECT 1;"]],
        ["ok", ["CREATE PROCEDURE p() BEGIN SELECT 1;"]],
    ],
    [
        "CREATE PROCEDURE p() BEGIN IF 1 THEN SELECT 1; END; IF 2 THEN SELECT 2; END IF; END; SELECT "
        "3;",
        [
            "ok",
            [
                "CREATE PROCEDURE p() BEGIN IF 1 THEN SELECT 1; END; IF 2 THEN SELECT 2; END IF; END",
                "SELECT 3",
            ],
        ],
        [
            "ok",
            [
                "CREATE PROCEDURE p() BEGIN IF 1 THEN SELECT 1; END; IF 2 THEN SELECT 2; END IF; END",
                "SELECT 3",
            ],
        ],
    ],
    [
        "CREATE PROCEDURE p() BEGIN LOOP SELECT 1; END (LOOP); SELECT 2; END; SELECT 3;",
        ["ok", ["CREATE PROCEDURE p() BEGIN LOOP SELECT 1; END (LOOP); SELECT 2; END", "SELECT 3"]],
        ["ok", ["CREATE PROCEDURE p() BEGIN LOOP SELECT 1; END (LOOP); SELECT 2; END", "SELECT 3"]],
    ],
    [
        "CREATE PROCEDURE p() BEGIN SELECT CASE WHEN 1 THEN CASE x WHEN 1 THEN 2 END END; IF 1 THEN "
        "SELECT 1; END IF; END; SELECT 3;",
        [
            "ok",
            [
                "CREATE PROCEDURE p() BEGIN SELECT CASE WHEN 1 THEN CASE x WHEN 1 THEN 2 END END; IF 1 "
                "THEN SELECT 1; END IF; END",
                "SELECT 3",
            ],
        ],
        [
            "ok",
            [
                "CREATE PROCEDURE p() BEGIN SELECT CASE WHEN 1 THEN CASE x WHEN 1 THEN 2 END END; IF 1 "
                "THEN SELECT 1; END IF; END",
                "SELECT 3",
            ],
        ],
    ],
    [
        "CREATE PROCEDURE p() BEGIN SET x = CASE WHEN 1 THEN CASE WHEN 2 THEN 3 END ELSE 4 END; "
        "SELECT 2; END; SELECT 3;",
        [
            "ok",
            [
                "CREATE PROCEDURE p() BEGIN SET x = CASE WHEN 1 THEN CASE WHEN 2 THEN 3 END ELSE 4 END; "
                "SELECT 2; END",
                "SELECT 3",
            ],
        ],
        [
            "ok",
            [
                "CREATE PROCEDURE p() BEGIN SET x = CASE WHEN 1 THEN CASE WHEN 2 THEN 3 END ELSE 4 END; "
                "SELECT 2; END",
                "SELECT 3",
            ],
        ],
    ],
    [
        "CREATE /*+ x\n*/ PROCEDURE p() BEGIN SELECT 1; END; SELECT 3;",
        ["ok", ["CREATE /*+ x\n*/ PROCEDURE p() BEGIN SELECT 1", "END", "SELECT 3"]],
        ["ok", ["CREATE /*+ x\n*/ PROCEDURE p() BEGIN SELECT 1; END", "SELECT 3"]],
    ],
    [
        "CREATE PROCEDURE p() BEGIN SELECT 1; END END IF; SELECT 2;",
        ["ok", ["CREATE PROCEDURE p() BEGIN SELECT 1; END END IF", "SELECT 2"]],
        ["ok", ["CREATE PROCEDURE p() BEGIN SELECT 1; END END IF", "SELECT 2"]],
    ],
    [
        "CREATE PROCEDURE p() BEGIN END; IF 1 THEN SELECT 1; END IF; SELECT 2;",
        ["ok", ["CREATE PROCEDURE p() BEGIN END", "IF 1 THEN SELECT 1", "END IF", "SELECT 2"]],
        ["ok", ["CREATE PROCEDURE p() BEGIN END", "IF 1 THEN SELECT 1", "END IF", "SELECT 2"]],
    ],
    [
        "CREATE DEFINER = u@% PROCEDURE p() BEGIN SELECT 1; END; SELECT 3;",
        ["ok", ["CREATE DEFINER = u@% PROCEDURE p() BEGIN SELECT 1", "END", "SELECT 3"]],
        ["ok", ["CREATE DEFINER = u@% PROCEDURE p() BEGIN SELECT 1", "END", "SELECT 3"]],
    ],
    [
        "CREATE PROCEDURE p(x INT DEFAULT (BEGIN)) SELECT 1; SELECT 3;",
        ["ok", ["CREATE PROCEDURE p(x INT DEFAULT (BEGIN)) SELECT 1", "SELECT 3"]],
        ["ok", ["CREATE PROCEDURE p(x INT DEFAULT (BEGIN)) SELECT 1", "SELECT 3"]],
    ],
    [
        "CREATE PROCEDURE p() BEGIN SELECT 1; END; SELECT 3;\n"
        "DELIMITER //\n"
        "CREATE PROCEDURE q() BEGIN SELECT 1; SELECT 2; END//\n"
        "DELIMITER ;\n"
        "SELECT 4;",
        [
            "ok",
            [
                "CREATE PROCEDURE p() BEGIN SELECT 1; END",
                "SELECT 3",
                "CREATE PROCEDURE q() BEGIN SELECT 1; SELECT 2; END",
                "SELECT 4",
            ],
        ],
        [
            "ok",
            [
                "CREATE PROCEDURE p() BEGIN SELECT 1; END",
                "SELECT 3",
                "CREATE PROCEDURE q() BEGIN SELECT 1; SELECT 2; END",
                "SELECT 4",
            ],
        ],
    ],
]


@BOTH
@pytest.mark.parametrize("index", range(len(PROGRAMS)))
def test_recorded_program_heads_and_bodies(spec, index):
    script, mysql, mariadb = PROGRAMS[index]
    assert observed(spec, script) == (mysql if spec is MYSQL_SPEC else mariadb), script


BODY = "BEGIN SELECT 1; SELECT 2; END"


def whole(script: str, spec: LexicalSpec = MYSQL_SPEC) -> bool:
    """The body is one record and the statement after it is the only other one."""
    result = observed(spec, script)
    return result[0] == "ok" and len(result[1]) == 2 and result[1][0].endswith("END")


FIELD_CASES = [
    ("head_verbs", {"head_verbs": frozenset({"CREATE"})}, f"ALTER EVENT e DO {BODY}; SELECT 3;"),
    ("fillers", {"fillers": frozenset()}, f"CREATE OR REPLACE FUNCTION f() {BODY}; SELECT 3;"),
    (
        "create_only_fillers",
        {"create_only_fillers": frozenset()},
        f"CREATE AGGREGATE FUNCTION f() {BODY}; SELECT 3;",
    ),
    ("create_verb", {"create_verb": "MAKE"}, f"CREATE PROCEDURE p() {BODY}; SELECT 3;"),
    ("definer", {"definer": "OWNER"}, f"CREATE DEFINER = u@h PROCEDURE p() {BODY}; SELECT 3;"),
    (
        "current_user",
        {"current_user": "WHO"},
        f"CREATE DEFINER = CURRENT_USER() PROCEDURE p() {BODY}; SELECT 3;",
    ),
    (
        "kinds",
        {"kinds": frozenset({"PROCEDURE"})},
        f"CREATE TRIGGER t BEFORE INSERT ON x {BODY}; SELECT 3;",
    ),
    ("alter_kinds", {"alter_kinds": frozenset()}, f"ALTER EVENT e DO {BODY}; SELECT 3;"),
    ("body_open", {"body_open": "START"}, f"CREATE PROCEDURE p() {BODY}; SELECT 3;"),
    ("body_close", {"body_close": "FINISH"}, f"CREATE PROCEDURE p() {BODY}; SELECT 3;"),
    (
        "block_words",
        {"block_words": frozenset({"LOOP", "WHILE", "REPEAT", "CASE", "FOR"})},
        "CREATE PROCEDURE p() BEGIN IF 1 THEN SELECT 1; END IF; SELECT 2; END; SELECT 3;",
    ),
    (
        "case_word",
        {"case_word": "SWITCH"},
        "CREATE PROCEDURE p() BEGIN SELECT CASE WHEN 1 THEN 2 END; SELECT 3; END; SELECT 4;",
    ),
    (
        "statement_starts",
        {"statement_starts": frozenset({";", ":", "BEGIN", "ELSE", "DO", "LOOP", "REPEAT"})},
        "CREATE PROCEDURE p() BEGIN IF 1 THEN IF 2 THEN SELECT 1; END IF; END IF; SELECT 5; END; SELECT 3;",
    ),
]


@pytest.mark.parametrize("field, changes, script", FIELD_CASES, ids=[c[0] for c in FIELD_CASES])
def test_every_program_rule_is_read(field, changes, script):
    assert whole(script)
    assert not whole(script, varied(**changes))


def test_program_body_tracks_a_head_and_a_stack():
    body = ProgramBody(MYSQL_PROGRAMS)
    for word in ("CREATE", "DEFINER"):
        body.word(word)
    body.punct("=")
    body.word("CURRENT_USER")
    body.punct("(")
    body.punct(")")
    for word in ("PROCEDURE", "P"):
        body.word(word)
    assert body.is_program and not body.open
    body.punct("(")
    body.punct(")")
    body.word("BEGIN")
    assert body.open
    body.word("IF")
    body.word("END")
    assert body.open
    body.word("IF")
    body.word("END")
    assert not body.open
    body.reset()
    assert not body.is_program


def test_a_qualified_word_is_a_name_and_a_quoted_one_a_name_too():
    body = ProgramBody(MYSQL_PROGRAMS)
    for word in ("CREATE", "PROCEDURE", "P"):
        body.word(word)
    body.word("BEGIN")
    body.quoted()
    body.quoted()
    assert body.open
    body.word("END")
    assert not body.open


@BOTH
def test_a_stored_program_under_a_custom_delimiter_has_no_analysis_fragments(spec):
    script = (
        "DELIMITER //\nCREATE PROCEDURE p() BEGIN SELECT 1; SELECT 2; END//\nSELECT 3; SELECT 4//\n"
    )
    records = [r for r in LexicalEngine(spec).split(script) if r.kind == "sql"]
    assert [r.analysis_statements for r in records] == [None, ("SELECT 3", "SELECT 4")]
