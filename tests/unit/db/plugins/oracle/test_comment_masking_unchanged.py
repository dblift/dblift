"""The SQL*Plus comment masking output is pinned (the masking view keeps its own scanner).

A characterisation test: the expected values were recorded from the scanner as it is, so it passes unchanged
while that scanner is untouched and fails when its output moves.
"""

import json
from pathlib import Path

import pytest

from dblift.db.plugins.oracle.parser._comments import strip_comments, strip_sql_comments
from dblift.db.plugins.oracle.parser.sqlplus_context import extract_sqlplus_context

GOLDEN = Path(__file__).with_name("masking_golden.json")


def outcome(fn, script):
    try:
        return fn(script)
    except Exception as exc:  # noqa: BLE001 - the class and message are the contract
        return ["error", type(exc).__name__, str(exc)]


def context(script):
    found = extract_sqlplus_context(script)
    return [found.serveroutput, found.prompts]


def observed(script):
    return [
        outcome(strip_comments, script),
        outcome(strip_sql_comments, script),
        outcome(context, script),
    ]


DIRECTIVE_CASES = [
    (
        "PROMPT hi -- x",
        ["PROMPT hi", "PROMPT hi ", [False, ["hi"]]],
    ),
    (
        "DEFINE x = 'a -- b'",
        ["DEFINE x = 'a", "DEFINE x = 'a ", [False, []]],
    ),
    (
        "@f.sql -- c",
        ["@f.sql", "@f.sql ", [False, []]],
    ),
    (
        "COL a FORMAT a10 -- c",
        ["COL a FORMAT a10", "COL a FORMAT a10 ", [False, []]],
    ),
    (
        "SHOW foo -- c",
        ["SHOW foo", "SHOW foo ", [False, []]],
    ),
    (
        "SET TIME ON -- c",
        ["SET TIME ON", "SET TIME ON ", [False, []]],
    ),
    (
        "EXIT\n-- c",
        ["EXIT", "EXIT\n", [False, []]],
    ),
    (
        "REMA it's -- x",
        [
            [
                "error",
                "UnsafeStatementSplitError",
                "unterminated string opened at line 1, column 8",
            ],
            [
                "error",
                "UnsafeStatementSplitError",
                "unterminated string opened at line 1, column 8",
            ],
            [
                "error",
                "UnsafeStatementSplitError",
                "unterminated string opened at line 1, column 8",
            ],
        ],
    ),
    (
        "/* c */ PROMPT it's -- x",
        [
            [
                "error",
                "UnsafeStatementSplitError",
                "unterminated string opened at line 1, column 18",
            ],
            [
                "error",
                "UnsafeStatementSplitError",
                "unterminated string opened at line 1, column 18",
            ],
            [
                "error",
                "UnsafeStatementSplitError",
                "unterminated string opened at line 1, column 18",
            ],
        ],
    ),
    (
        "CREATE LIBRARY l AS 'x';\nPROMPT it's -- c",
        [
            "CREATE LIBRARY l AS 'x';\nPROMPT it's",
            "CREATE LIBRARY l AS 'x';\nPROMPT it's ",
            [False, ["it's"]],
        ],
    ),
    (
        "SELECT (1;\nPROMPT it's -- c\n);",
        ["SELECT (1;\nPROMPT it's \n);", "SELECT (1;\nPROMPT it's \n);", [False, ["it's"]]],
    ),
    (
        "SET LINESIZE 100-1 -- c",
        ["SET LINESIZE 100-1", "SET LINESIZE 100-1 ", [False, []]],
    ),
    (
        "SET NULL 'a-b' -- c",
        ["SET NULL 'a-b'", "SET NULL 'a-b' ", [False, []]],
    ),
    (
        "SET SERVEROUTPUT ON -- c\nSELECT 1 FROM dual;",
        [
            "SET SERVEROUTPUT ON \nSELECT 1 FROM dual;",
            "SET SERVEROUTPUT ON \nSELECT 1 FROM dual;",
            [True, []],
        ],
    ),
]

Q_QUOTE_CASES = [
    (
        "SELECT q'[a -- b]' FROM dual; -- c",
        ["SELECT q'[a -- b]' FROM dual;", "SELECT q'[a -- b]' FROM dual; ", [False, []]],
    ),
    (
        "SELECT q'{/* c */}' FROM dual;",
        ["SELECT q'{/* c */}' FROM dual;", "SELECT q'{/* c */}' FROM dual;", [False, []]],
    ),
    (
        "SELECT nq'!--!' FROM dual;",
        ["SELECT nq'!--!' FROM dual;", "SELECT nq'!--!' FROM dual;", [False, []]],
    ),
    (
        "SELECT q'(a -- b)' FROM dual; -- c",
        ["SELECT q'(a -- b)' FROM dual;", "SELECT q'(a -- b)' FROM dual; ", [False, []]],
    ),
    (
        "SELECT Q'<-- x>' FROM dual; /* c */",
        ["SELECT Q'<-- x>' FROM dual;", "SELECT Q'<-- x>' FROM dual; ", [False, []]],
    ),
    (
        "SELECT q'[a]b -- c]' FROM dual;",
        ["SELECT q'[a]b -- c]' FROM dual;", "SELECT q'[a]b -- c]' FROM dual;", [False, []]],
    ),
    (
        'SELECT "a--b" FROM dual; -- tail',
        ['SELECT "a--b" FROM dual;', 'SELECT "a--b" FROM dual; ', [False, []]],
    ),
    (
        'SELECT "a/*b" FROM dual; /* c */',
        ['SELECT "a/*b" FROM dual;', 'SELECT "a/*b" FROM dual; ', [False, []]],
    ),
]

SLASH_CASES = [
    (
        "BEGIN NULL; END;\n/\n-- c\nSELECT 1 FROM dual;",
        [
            "BEGIN NULL; END;\n/\n\nSELECT 1 FROM dual;",
            "BEGIN NULL; END;\n/\n\nSELECT 1 FROM dual;",
            [False, []],
        ],
    ),
    (
        "SELECT 4 / 2 -- c\nFROM dual;",
        ["SELECT 4 / 2 \nFROM dual;", "SELECT 4 / 2 \nFROM dual;", [False, []]],
    ),
    (
        "SELECT 1 FROM dual\n  /  \n-- c\nPROMPT p -- d\n",
        [
            "SELECT 1 FROM dual\n  /  \n\nPROMPT p",
            "SELECT 1 FROM dual\n / \n\nPROMPT p \n",
            [False, ["p"]],
        ],
    ),
    (
        "SELECT 4 /\nPROMPT it's -- c",
        [
            [
                "error",
                "UnsafeStatementSplitError",
                "unterminated string opened at line 2, column 10",
            ],
            [
                "error",
                "UnsafeStatementSplitError",
                "unterminated string opened at line 2, column 10",
            ],
            [
                "error",
                "UnsafeStatementSplitError",
                "unterminated string opened at line 2, column 10",
            ],
        ],
    ),
    (
        "SELECT 4 /\nSELECT 1 FROM dual; -- c",
        ["SELECT 4 /\nSELECT 1 FROM dual;", "SELECT 4 /\nSELECT 1 FROM dual; ", [False, []]],
    ),
    (
        "SELECT 1 FROM dual\n/\nPROMPT it's -- c",
        [
            "SELECT 1 FROM dual\n/\nPROMPT it's",
            "SELECT 1 FROM dual\n/\nPROMPT it's ",
            [False, ["it's"]],
        ],
    ),
]


@pytest.mark.parametrize("script, expected", DIRECTIVE_CASES)
def test_masking_directive_comment_cut(script, expected):
    assert observed(script) == expected


@pytest.mark.parametrize("script, expected", Q_QUOTE_CASES)
def test_masking_q_quote_hides_comment_markers(script, expected):
    assert observed(script) == expected


@pytest.mark.parametrize("script, expected", SLASH_CASES)
def test_masking_alone_on_line_slash(script, expected):
    assert observed(script) == expected


def test_masking_golden_subset_reaches_every_branch_of_the_masking_scanner():
    cases = json.loads(GOLDEN.read_text())
    assert len(cases) >= 10
    for case in cases:
        assert observed(case["script"]) == case["expected"], case["script"]
