"""Client commands, escapes, the session-mode refusal and the order of refusals of a client script."""

import json
from dataclasses import replace
from pathlib import Path

import pytest

from dblift.core.exceptions import UnsafeStatementSplitError, UnsupportedMetaCommandError
from dblift.core.sql_parser.lexical_engine import LexicalEngine
from dblift.core.sql_parser.lexical_spec import LexicalSpec
from dblift.db.plugins.mariadb.lexical_spec import MARIADB_SPEC
from dblift.db.plugins.mysql.parser.lexical_spec import MYSQL_RULES, MYSQL_SPEC
from tests.support.splitter_spec.spec_tables import load_conformance_rows
from tests.support.splitter_spec.splitting import SplitOutcome

BOTH = pytest.mark.parametrize("spec", [MYSQL_SPEC, MARIADB_SPEC], ids=["mysql", "mariadb"])
SPEC_DIR = Path(__file__).resolve().parents[4] / "docs" / "sql-parsing"
ROW_BASES = {"20", "21", "25", "48", "49", "50", "51", "52", "53", "54", "55", "65"} | {
    str(n) for n in range(56, 65)
}
ROWS = [
    row
    for row in load_conformance_rows(SPEC_DIR)
    if row.dialect in ("mysql", "mariadb")
    and row.row_id.rstrip("abcdefghijklmnopqrstuvwxyz") in ROW_BASES
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
    return replace(MYSQL_SPEC, delimiter_script=replace(MYSQL_RULES, **changes))


def refused(script: str, spec: LexicalSpec = MYSQL_SPEC) -> bool:
    return observed(spec, script)[0] == "error"


@pytest.mark.parametrize("spec, row", RUNS)
def test_spec_rows_are_read_by_the_engine(spec, row):
    try:
        outcome = SplitOutcome(statements=tuple(LexicalEngine(spec).split_statements(row.script)))
    except Exception as exc:  # noqa: BLE001 - the class is what the row expects
        outcome = SplitOutcome(statements=(), error=type(exc).__name__, detail=str(exc))
    assert outcome.matches(row.expectation), (row.row_id, row.script)


AFTER = [
    [
        "/* c */ exit\nSELECT 1;",
        [
            "error",
            "UnsupportedMetaCommandError",
            "mysql client command 'exit' after a comment on line 1: clients and versions differ on "
            "whether it is a command",
        ],
        [
            "error",
            "UnsupportedMetaCommandError",
            "mariadb client command 'exit' after a comment on line 1: clients and versions differ on "
            "whether it is a command",
        ],
    ],
    [
        "/*!50000 x */ status\nSELECT 1;",
        [
            "error",
            "UnsupportedMetaCommandError",
            "mysql client command 'status' after a comment on line 1: clients and versions differ on "
            "whether it is a command",
        ],
        [
            "error",
            "UnsupportedMetaCommandError",
            "mariadb client command 'status' after a comment on line 1: clients and versions differ on "
            "whether it is a command",
        ],
    ],
    [
        "/*+ x */ quit\nSELECT 1;",
        [
            "error",
            "UnsupportedMetaCommandError",
            "mysql client command 'quit' after a comment on line 1: clients and versions differ on "
            "whether it is a command",
        ],
        [
            "error",
            "UnsupportedMetaCommandError",
            "mariadb client command 'quit' after a comment on line 1: clients and versions differ on "
            "whether it is a command",
        ],
    ],
    [
        "/*+ x\n*/ exit\nSELECT 1;",
        ["ok", ["*/ exit\nSELECT 1"]],
        [
            "error",
            "UnsupportedMetaCommandError",
            "mariadb client command 'exit' after a comment on line 2: clients and versions differ on "
            "whether it is a command",
        ],
    ],
    [
        "SELECT 1 /* c */ exit\n;",
        ["ok", ["SELECT 1 /* c */ exit"]],
        ["ok", ["SELECT 1 /* c */ exit"]],
    ],
    [
        "/*! x */ exit\nSELECT 1;",
        [
            "error",
            "UnsupportedMetaCommandError",
            "mysql client command 'exit' after a comment on line 1: clients and versions differ on "
            "whether it is a command",
        ],
        [
            "error",
            "UnsupportedMetaCommandError",
            "mariadb client command 'exit' after a comment on line 1: clients and versions differ on "
            "whether it is a command",
        ],
    ],
    [
        "SELECT 1 /*! x */ exit\n;",
        ["ok", ["SELECT 1 /*! x */ exit"]],
        ["ok", ["SELECT 1 /*! x */ exit"]],
    ],
    [
        "/*! x */\nexit\nSELECT 1;",
        [
            "error",
            "UnsupportedMetaCommandError",
            "mysql client command 'exit' on line 2: dblift does not run client commands",
        ],
        [
            "error",
            "UnsupportedMetaCommandError",
            "mariadb client command 'exit' on line 2: dblift does not run client commands",
        ],
    ],
    [
        "/*! x */\nstatus\nSELECT 1;",
        ["ok", ["/*! x */\nstatus\nSELECT 1"]],
        ["ok", ["/*! x */\nstatus\nSELECT 1"]],
    ],
    [
        "/*! x\n*/ exit\nSELECT 1;",
        ["ok", ["/*! x\n*/ exit\nSELECT 1"]],
        ["ok", ["/*! x\n*/ exit\nSELECT 1"]],
    ],
    [
        "/* a\nb */ exit\n;",
        [
            "error",
            "UnsupportedMetaCommandError",
            "mysql client command 'exit' after a comment on line 2: clients and versions differ on "
            "whether it is a command",
        ],
        [
            "error",
            "UnsupportedMetaCommandError",
            "mariadb client command 'exit' after a comment on line 2: clients and versions differ on "
            "whether it is a command",
        ],
    ],
    [
        "/*! x */\nquit;\nSELECT 1;",
        [
            "error",
            "UnsupportedMetaCommandError",
            "mysql client command 'quit' on line 2: dblift does not run client commands",
        ],
        [
            "error",
            "UnsupportedMetaCommandError",
            "mariadb client command 'quit' on line 2: dblift does not run client commands",
        ],
    ],
    [
        "/*! x */ SELECT 1\nexit\n;",
        ["ok", ["/*! x */ SELECT 1\nexit"]],
        ["ok", ["/*! x */ SELECT 1\nexit"]],
    ],
    [
        "/* c */ go\nSELECT 1;",
        [
            "error",
            "UnsupportedMetaCommandError",
            "mysql client command 'go' after a comment on line 1: clients and versions differ on "
            "whether it is a command",
        ],
        [
            "error",
            "UnsupportedMetaCommandError",
            "mariadb client command 'go' after a comment on line 1: clients and versions differ on "
            "whether it is a command",
        ],
    ],
    [
        "/* c */ use db\nSELECT 1;",
        [
            "error",
            "UnsupportedMetaCommandError",
            "mysql client command 'use' after a comment on line 1: clients and versions differ on "
            "whether it is a command",
        ],
        [
            "error",
            "UnsupportedMetaCommandError",
            "mariadb client command 'use' after a comment on line 1: clients and versions differ on "
            "whether it is a command",
        ],
    ],
    [
        "/* c */ DELIMITER //\nSELECT 1//",
        [
            "error",
            "UnsafeStatementSplitError",
            "DELIMITER is not the first word of line 1: the mysql client silently drops the statements "
            "that follow",
        ],
        [
            "error",
            "UnsafeStatementSplitError",
            "DELIMITER is not the first word of line 1: the mariadb client silently drops the "
            "statements that follow",
        ],
    ],
    [
        "/* c */ /* d */ exit\n;",
        [
            "error",
            "UnsupportedMetaCommandError",
            "mysql client command 'exit' after a comment on line 1: clients and versions differ on "
            "whether it is a command",
        ],
        [
            "error",
            "UnsupportedMetaCommandError",
            "mariadb client command 'exit' after a comment on line 1: clients and versions differ on "
            "whether it is a command",
        ],
    ],
    [
        "/*! a */ /*! b */\nexit\n;",
        [
            "error",
            "UnsupportedMetaCommandError",
            "mysql client command 'exit' on line 2: dblift does not run client commands",
        ],
        [
            "error",
            "UnsupportedMetaCommandError",
            "mariadb client command 'exit' on line 2: dblift does not run client commands",
        ],
    ],
    [
        "/*! a */ SELECT\n/*! b */\nexit\n;",
        ["ok", ["/*! a */ SELECT\n/*! b */\nexit"]],
        ["ok", ["/*! a */ SELECT\n/*! b */\nexit"]],
    ],
]

SESSION = [
    [
        "SET sql_mode='NO_BACKSLASH_ESCAPES';SELECT 1",
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
        "PREPARE s FROM 'SET sql_mode=\"NO_BACKSLASH_ESCAPES\"';",
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
        "/*!50000 SET sql_mode='NO_BACKSLASH_ESCAPES' */;",
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
        "/*M!100500 SET sql_mode='NO_BACKSLASH_ESCAPES' */;",
        ["ok", []],
        [
            "error",
            "UnsafeStatementSplitError",
            "the statement on line 1 sets NO_BACKSLASH_ESCAPES: the mariadb client then reads "
            "backslashes as ordinary characters, this splitter cannot follow",
        ],
    ],
    [
        "SELECT 1 /* NO_BACKSLASH_ESCAPES */;",
        ["ok", ["SELECT 1 /* NO_BACKSLASH_ESCAPES */"]],
        ["ok", ["SELECT 1 /* NO_BACKSLASH_ESCAPES */"]],
    ],
    ["# NO_BACKSLASH_ESCAPES SET\nSELECT 1;", ["ok", ["SELECT 1"]], ["ok", ["SELECT 1"]]],
    [
        "UPDATE t SET c = 'NO_BACKSLASH_ESCAPES';",
        ["ok", ["UPDATE t SET c = 'NO_BACKSLASH_ESCAPES'"]],
        ["ok", ["UPDATE t SET c = 'NO_BACKSLASH_ESCAPES'"]],
    ],
    [
        "CREATE TABLE t (m SET('NO_BACKSLASH_ESCAPES','b'));",
        ["ok", ["CREATE TABLE t (m SET('NO_BACKSLASH_ESCAPES','b'))"]],
        ["ok", ["CREATE TABLE t (m SET('NO_BACKSLASH_ESCAPES','b'))"]],
    ],
    [
        "SELECT REPLACE(@@sql_mode, 'NO_BACKSLASH_ESCAPES', '');",
        ["ok", ["SELECT REPLACE(@@sql_mode, 'NO_BACKSLASH_ESCAPES', '')"]],
        ["ok", ["SELECT REPLACE(@@sql_mode, 'NO_BACKSLASH_ESCAPES', '')"]],
    ],
    [
        "set sql_mode = concat(@@sql_mode, ',no_backslash_escapes');",
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
        "SELECT 'NO_BACKSLASH_ESCAPES' AS SET_;",
        ["ok", ["SELECT 'NO_BACKSLASH_ESCAPES' AS SET_"]],
        ["ok", ["SELECT 'NO_BACKSLASH_ESCAPES' AS SET_"]],
    ],
    [
        "SET NAMES utf8; SELECT 1",
        ["ok", ["SET NAMES utf8", "SELECT 1"]],
        ["ok", ["SET NAMES utf8", "SELECT 1"]],
    ],
    [
        "SET @a = 'NO_BACKSLASH_ESCAPES'; SELECT 2;",
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
        "  /*!50000 PREPARE s FROM 'NO_BACKSLASH_ESCAPES' */;",
        ["ok", ["/*!50000 PREPARE s FROM 'NO_BACKSLASH_ESCAPES' */"]],
        ["ok", ["/*!50000 PREPARE s FROM 'NO_BACKSLASH_ESCAPES' */"]],
    ],
    [
        "SELECT 1;\nSET GLOBAL sql_mode = 'NO_BACKSLASH_ESCAPES'",
        [
            "error",
            "UnsafeStatementSplitError",
            "the statement on line 2 sets NO_BACKSLASH_ESCAPES: the mysql client then reads backslashes "
            "as ordinary characters, this splitter cannot follow",
        ],
        [
            "error",
            "UnsafeStatementSplitError",
            "the statement on line 2 sets NO_BACKSLASH_ESCAPES: the mariadb client then reads "
            "backslashes as ordinary characters, this splitter cannot follow",
        ],
    ],
    [
        "SET /*! x */ sql_mode='NO_BACKSLASH_ESCAPES';",
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
        "SELECT NO_BACKSLASH_ESCAPES;",
        ["ok", ["SELECT NO_BACKSLASH_ESCAPES"]],
        ["ok", ["SELECT NO_BACKSLASH_ESCAPES"]],
    ],
    [
        "SELECT `NO_BACKSLASH_ESCAPES` , SET;",
        ["ok", ["SELECT `NO_BACKSLASH_ESCAPES` , SET"]],
        ["ok", ["SELECT `NO_BACKSLASH_ESCAPES` , SET"]],
    ],
    [
        "DELIMITER //\nSET sql_mode='NO_BACKSLASH_ESCAPES'//",
        [
            "error",
            "UnsafeStatementSplitError",
            "the statement on line 2 sets NO_BACKSLASH_ESCAPES: the mysql client then reads backslashes "
            "as ordinary characters, this splitter cannot follow",
        ],
        [
            "error",
            "UnsafeStatementSplitError",
            "the statement on line 2 sets NO_BACKSLASH_ESCAPES: the mariadb client then reads "
            "backslashes as ordinary characters, this splitter cannot follow",
        ],
    ],
    [
        "SET sql_mode='NO_BACKSLASH_ESCAPES'",
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
]

ESCAPE = [
    [
        "SELECT 1 \\\n;",
        [
            "error",
            "UnsupportedMetaCommandError",
            "mysql client command a backslash at the end of a line on line 1: dblift does not run "
            "client commands",
        ],
        [
            "error",
            "UnsupportedMetaCommandError",
            "mariadb client command a backslash at the end of a line on line 1: dblift does not run "
            "client commands",
        ],
    ],
    [
        "SELECT 1 \\",
        [
            "error",
            "UnsupportedMetaCommandError",
            "mysql client command a backslash at the end of a line on line 1: dblift does not run "
            "client commands",
        ],
        [
            "error",
            "UnsupportedMetaCommandError",
            "mariadb client command a backslash at the end of a line on line 1: dblift does not run "
            "client commands",
        ],
    ],
    [
        "SELECT 1 /*! \\G */;",
        [
            "error",
            "UnsupportedMetaCommandError",
            "mysql client command \\G on line 1: dblift does not run client commands",
        ],
        [
            "error",
            "UnsupportedMetaCommandError",
            "mariadb client command \\G on line 1: dblift does not run client commands",
        ],
    ],
    [
        "SELECT /*+ a\n\\G */ 1;",
        [
            "error",
            "UnsupportedMetaCommandError",
            "mysql client command \\G on line 2: dblift does not run client commands",
        ],
        ["ok", ["SELECT /*+ a\n\\G */ 1"]],
    ],
    ["SELECT 1 \\N, 2;", ["ok", ["SELECT 1 \\N, 2"]], ["ok", ["SELECT 1 \\N, 2"]]],
    ["\\N", ["ok", ["\\N"]], ["ok", ["\\N"]]],
    ["SELECT 'a\\G' AS x;", ["ok", ["SELECT 'a\\G' AS x"]], ["ok", ["SELECT 'a\\G' AS x"]]],
    ["SELECT `a\\G`;", ["ok", ["SELECT `a\\G`"]], ["ok", ["SELECT `a\\G`"]]],
    ["SELECT 1 -- \\G\n;", ["ok", ["SELECT 1 -- \\G"]], ["ok", ["SELECT 1 -- \\G"]]],
    ["SELECT 1 /* \\G */;", ["ok", ["SELECT 1 /* \\G */"]], ["ok", ["SELECT 1 /* \\G */"]]],
    ["SELECT 1 # \\G\n;", ["ok", ["SELECT 1 # \\G"]], ["ok", ["SELECT 1 # \\G"]]],
    [
        "SELECT /*+ a \\G */ 1;",
        [
            "error",
            "UnsupportedMetaCommandError",
            "backslash inside an optimizer hint on line 1: the mysql client runs it as a command",
        ],
        ["ok", ["SELECT /*+ a \\G */ 1"]],
    ],
    [
        "SELECT 1;\n\\G",
        [
            "error",
            "UnsupportedMetaCommandError",
            "mysql client command \\G on line 2: dblift does not run client commands",
        ],
        [
            "error",
            "UnsupportedMetaCommandError",
            "mariadb client command \\G on line 2: dblift does not run client commands",
        ],
    ],
]

TABLE_VARIANTS = [
    "",
    ";",
    ";;",
    " ;",
    " ; ;",
    "\t",
    " \x0b",
    " x",
    " x;",
    " 'x'",
    "x",
    " -- c",
    " /* c */;",
    "//",
    " //",
]

TABLE = {
    "?": "RRRRRRRRRRRRRRRRttRRttRRRRttRRRRRRRRRRRRRRRRRRRRRRttRRRRRRRR",
    "CHARSET": "RRRRRRRRRRRRRRRRRRRRttRRRRttRRRRRRRRRRRRRRRRRRRRRRttRRRRRRRR",
    "CLEAR": "RRRRRRRRRRRRRRttttttttttttttttRRRRRRRRRRRRRRttttttttttttRRRR",
    "CONNECT": "RRRRRRRRRRRRRRRRRRRRttRRRRttRRRRRRRRRRRRRRRRRRRRRRttRRRRRRRR",
    "EDIT": "RRRRRRRRRRRRRRttttttttttttttttRRRRRRRRRRRRRRttttttttttttRRRR",
    "EGO": "RRttttttttRRRRttttttttttttttttRRttttttttRRRRtttttttttttttttt",
    "EXIT": "RRRRRRRRRRRRRRttttttttttttttttRRRRRRRRRRRRRRttttttttttttRRRR",
    "FOO": "tttttttttttttttttttttttttttttttttttttttttttttttttttttttttttt",
    "GO": "RRttttttttRRRRttttttttttttttttRRttttttttRRRRtttttttttttttttt",
    "HELP": "RRRRRRRRRRRRRRRRttRRttRRRRttRRRRRRRRRRRRRRRRRRRRRRttRRRRRRRR",
    "NOPAGER": "RRRRRRRRRRRRRRttttttttttttttttRRRRRRRRRRRRRRttttttttttttRRRR",
    "NOTEE": "RRRRRRRRRRRRRRttttttttttttttttRRRRRRRRRRRRRRttttttttttttRRRR",
    "NOWARNING": "RRRRRRRRRRRRRRttttttttttttttttRRRRRRRRRRRRRRttttttttttttRRRR",
    "PAGER": "RRRRRRRRRRRRRRRRRRRRttRRRRttRRRRRRRRRRRRRRRRRRRRRRttRRRRRRRR",
    "PRINT": "RRRRRRRRRRRRRRttttttttttttttttRRRRRRRRRRRRRRttttttttttttRRRR",
    "PROMPT": "RRRRRRRRRRRRRRRRRRRRttRRRRttRRRRRRRRRRRRRRRRRRRRRRttRRRRRRRR",
    "QUERY_ATTRIBUTES": "RRRRRRRRRRRRRRRRRRRRttRRRRttRRRRRRRRRRRRRRRRRRRRRRttRRRRRRRR",
    "QUIT": "RRRRRRRRRRRRRRttttttttttttttttRRRRRRRRRRRRRRttttttttttttRRRR",
    "REHASH": "RRRRRRRRRRRRRRttttttttttttttttRRRRRRRRRRRRRRttttttttttttRRRR",
    "RESETCONNECTION": "RRRRRRRRRRRRRRttttttttttttttttRRRRRRRRRRRRRRttttttttttttRRRR",
    "SOURCE": "RRRRRRRRRRRRRRRRRRRRttRRRRttRRRRRRRRRRRRRRRRRRRRRRttRRRRRRRR",
    "SSL_SESSION_DATA_PRINT": "RRRRRRRRRRRRRRRRRRRRttRRRRttRRRRRRRRRRRRRRRRRRRRRRttRRRRRRRR",
    "STATUS": "RRRRRRRRRRRRRRttttttttttttttttRRRRRRRRRRRRRRttttttttttttRRRR",
    "SYSTEM": "RRRRRRRRRRRRRRRRRRRRttRRRRttRRRRRRRRRRRRRRRRRRRRRRttRRRRRRRR",
    "TEE": "RRRRRRRRRRRRRRRRRRRRttRRRRttRRRRRRRRRRRRRRRRRRRRRRttRRRRRRRR",
    "USE": "RRttttttttRRRRRRttRRttRRRRttRRRRttttRRRRRRRRRRRRRRttRRRRtttt",
    "WARNINGS": "RRRRRRRRRRRRRRttttttttttttttttRRRRRRRRRRRRRRttttttttttttRRRR",
    "use_x": "tttttttttttttttttttttttttttttttttttttttttttttttttttttttttttt",
}


def expected_for(spec: LexicalSpec, entry: list) -> list:
    return entry[1] if spec is MYSQL_SPEC else entry[2]


@BOTH
@pytest.mark.parametrize(
    "group", [AFTER, SESSION, ESCAPE], ids=["after-comment", "session", "escape"]
)
def test_recorded_cases(spec, group):
    for entry in group:
        assert observed(spec, entry[0]) == expected_for(spec, entry), entry[0]


@BOTH
def test_every_printable_backslash_follower(spec):
    for code in range(33, 127):
        char = chr(code)
        result = observed(spec, f"SELECT 1 \\{char}\n;")
        if char == "N":
            assert result == ["ok", [f"SELECT 1 \\{char}"]]
        else:
            assert result == [
                "error",
                "UnsupportedMetaCommandError",
                f"{spec.client_name} client command \\{char} on line 1: dblift does not run client commands",
            ]


@pytest.mark.parametrize("word", list(TABLE))
def test_line_head_command_sets(word):
    outcomes = ""
    for prefix in ("", "DELIMITER //\n"):
        for variant in TABLE_VARIANTS:
            for text in (word, word.lower()):
                script = prefix + text + variant + "\nSELECT 1" + ("//" if prefix else ";")
                result = observed(MYSQL_SPEC, script)
                outcomes += (
                    "t"
                    if result[0] == "ok"
                    else "R" if result[1].startswith("Unsupported") else "E"
                )
    assert outcomes == TABLE[word]
    assert (
        observed(MARIADB_SPEC, word + "\nSELECT 1;")[0]
        == observed(MYSQL_SPEC, word + "\nSELECT 1;")[0]
    )


@BOTH
def test_a_refused_command_names_the_word_as_written(spec):
    assert observed(spec, "Status\nSELECT 1;") == [
        "error",
        "UnsupportedMetaCommandError",
        f"{spec.client_name} client command 'Status' on line 1: dblift does not run client commands",
    ]


FIELD_CASES = [
    ("bare_commands", "go\nSELECT 1;"),
    ("terminated_commands", "rehash;\nSELECT 1;"),
    ("argument_commands", "source /x;\nSELECT 1;"),
    ("unterminated_commands", "use db\nSELECT 1;"),
    ("exit_commands", "/*! x */\nexit\nSELECT 1;"),
]


@pytest.mark.parametrize("field, script", FIELD_CASES, ids=[c[0] for c in FIELD_CASES])
def test_each_command_set_is_read(field, script):
    assert refused(script)
    assert not refused(script, varied(**{field: frozenset()}))


def test_statement_words_are_read():
    assert not refused("use;\nSELECT 1;")
    assert refused("use;\nSELECT 1;", varied(statement_words=frozenset()))
    assert refused("use db;;\nSELECT 1;") is False


def test_command_words_and_lines_are_read_from_the_rules():
    assert refused("?\nSELECT 1;")
    assert not refused("?\nSELECT 1;", varied(line_word=r"[A-Za-z_]+"))
    renamed = varied(bare_commands=frozenset({"FOO"}))
    assert refused("foo\nSELECT 1;", renamed)
    assert not refused("go\nSELECT 1;", renamed)


def test_the_escape_character_and_its_text_followers_are_read():
    assert refused("SELECT 1 \\G\n;")
    assert not refused("SELECT 1 \\G\n;", varied(escape="~"))
    assert refused("SELECT 1 ~G\n;", varied(escape="~"))
    assert not refused("SELECT \\N;")
    assert refused("SELECT \\N;", varied(escape_text=frozenset()))
    assert not refused("SELECT \\n;", varied(escape_text=frozenset({"n"})))


def test_the_session_mode_name_and_verbs_are_read():
    prepare = "PREPARE s FROM 'SET sql_mode=\"NO_BACKSLASH_ESCAPES\"';"
    assert refused(prepare)
    assert not refused(prepare, varied(session_mode_verbs=("SET",)))
    assert refused("SET sql_mode='X_MODE';", varied(session_mode="X_MODE"))
    assert not refused("SET sql_mode='NO_BACKSLASH_ESCAPES';", varied(session_mode="X_MODE"))
    assert refused("/*!50000 SET x='NO_BACKSLASH_ESCAPES' */;")
    assert not refused(
        "/*!50000 SET x='NO_BACKSLASH_ESCAPES' */;", varied(executable_openers=("/*X!",))
    )


def test_the_executable_openers_of_the_rules_carry_into_the_session_check():
    script = "/*M!100500 SET sql_mode='NO_BACKSLASH_ESCAPES' */;"
    assert not refused(script, MYSQL_SPEC)
    assert refused(script, MARIADB_SPEC)


@BOTH
def test_a_later_command_line_after_a_statement_is_text_until_it_ends(spec):
    assert observed(spec, "SELECT 1\nexit\n;") == ["ok", ["SELECT 1\nexit"]]
    assert refused("SELECT 1;\nexit\n;", spec)
    assert refused("DELIMITER //\nSELECT 1//\nexit\n//", spec)


PAIRS = json.loads((Path(__file__).parent / "mysql_refusal_pairs.json").read_text())


@pytest.mark.parametrize("index", range(0, len(PAIRS["rows"]), 1))
def test_refusals_are_raised_in_source_order(index):
    script, mysql, mariadb = PAIRS["rows"][index]
    for spec, code in ((MYSQL_SPEC, mysql), (MARIADB_SPEC, mariadb)):
        result = observed(spec, script)
        if code < 0:
            assert result[0] == "ok", script
        else:
            assert result[0] == "error" and result[1:] == PAIRS["errors"][code], script


# built with chr(): a formatter or an editor must not be able to turn them into invisible literals
LS = chr(0x2028)
SEC = chr(0x00A7)
EA = chr(0x00E9)


def test_the_quirk_characters_are_the_ones_meant():
    assert (ord(LS), ord(SEC), ord(EA)) == (0x2028, 0xA7, 0xE9)


@BOTH
def test_preserved_quirks_match_the_recorded_values(spec):
    def statements(script: str) -> list:
        return LexicalEngine(spec).split_statements(script)

    # a trailing NBSP or U+2028 is stripped from a statement; a leading one is kept
    assert statements("SELECT 1\xa0;") == ["SELECT 1"]
    assert statements(f"SELECT 1{LS};") == ["SELECT 1"]
    assert statements("\xa0SELECT 1;") == ["\xa0SELECT 1"]
    # a delimiter counts characters, not bytes
    assert statements(f"DELIMITER {SEC}\nSELECT 1{SEC}\nSELECT 2{SEC}\nDELIMITER ;") == [
        "SELECT 1",
        "SELECT 2",
    ]
    assert statements("DELIMITER " + EA * 15 + "\nSELECT 1" + EA * 15) == ["SELECT 1"]
    assert statements("DELIMITER " + EA * 8 + "\nSELECT 1" + EA * 8) == ["SELECT 1"]
    with pytest.raises(UnsafeStatementSplitError, match="longer than 15 characters"):
        LexicalEngine(spec).split("DELIMITER " + EA * 16 + "\nSELECT 1;")
    # `delimiter` followed only by a vertical tab or form feed is the command, with that delimiter
    assert statements("delimiter\x0b\nSELECT 1;") == ["SELECT 1;"]
    assert statements("DELIMITER \x0c\nSELECT 1;") == ["SELECT 1;"]


@BOTH
def test_a_bare_command_is_followed_by_blanks_that_include_a_carriage_return(spec):
    assert observed(spec, "SELECT 1;\ngo \r")[0] == "error"
    assert observed(spec, "SELECT 1;\ngo \x0b")[0] == "error"


def test_the_closer_of_an_open_hint_ends_the_executable_comment_only_text():
    script = "/*! x */ /*+ a\n*/ \nexit\nSELECT 1;"
    assert observed(MYSQL_SPEC, script) == ["ok", ["/*! x */ /*+ a\n*/ \nexit\nSELECT 1"]]
    # a mariadb hint is a block comment: the text before the exit line is comments only
    assert observed(MARIADB_SPEC, script)[0] == "error"


@BOTH
@pytest.mark.parametrize(
    "script",
    [
        "SELECT 1 /* SET NO_BACKSLASH_ESCAPES */;",
        "SELECT 1 # SET NO_BACKSLASH_ESCAPES\n;",
        "SET @a = 1 -- NO_BACKSLASH_ESCAPES\n;",
    ],
)
def test_the_session_mode_name_in_a_comment_of_the_statement_is_not_a_setting(spec, script):
    assert observed(spec, script)[0] == "ok"


@BOTH
def test_a_nul_is_refused_before_a_command_and_the_session_mode_waits_for_its_statement_end(spec):
    assert observed(spec, "exit\nSELECT 1\x00;") == [
        "error",
        "UnsafeStatementSplitError",
        f"NUL byte on line 2: the {spec.client_name} client refuses it unless --binary-mode is set",
    ]
    assert observed(spec, "SET sql_mode='NO_BACKSLASH_ESCAPES', @a = 1 \\G\n;") == [
        "error",
        "UnsupportedMetaCommandError",
        f"{spec.client_name} client command \\G on line 1: dblift does not run client commands",
    ]
    assert (
        observed(spec, "SET sql_mode='NO_BACKSLASH_ESCAPES';\nexit\n")[1]
        == "UnsafeStatementSplitError"
    )


@BOTH
@pytest.mark.parametrize(
    "script",
    ["/*! ; */ ?", "/*! ; */ go\nSELECT 1;", "SELECT 1; /*! ; */ status", "/*! a ; b */ exit"],
)
def test_a_command_after_an_executable_comment_is_refused_when_a_delimiter_ends_the_statement_inside_it(
    spec, script
):
    """The statement the delimiter ends inside the comment does not forget how the comment began."""
    error = observed(spec, script)
    assert error[:2] == ["error", "UnsupportedMetaCommandError"]
    assert "after a comment on line 1" in error[2]
