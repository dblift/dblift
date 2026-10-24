"""SQL Server batches through the shared engine: separator lines and batch records.

Expected values were recorded from the splitter this engine replaces (the record fields
text, line, terminator, repeat, source_start and source_end, and the execution strings run
length encoded); the unterminated-lexeme wording is the shared engine's.
"""

import itertools
import logging
from dataclasses import replace

import pytest

from dblift.core.exceptions import UnsafeStatementSplitError
from dblift.core.sql_parser.lexical_engine import LexicalEngine
from dblift.db.plugins.sqlserver.parser.lexical_spec import SQLSERVER_SPEC

# Recorded: (name, script, outcome). Outcome: ("ok", records, strings) or ("error", class, message).
CASES = [
    ("row 1", "SELECT 1\nGO\n", ("ok", [("SELECT 1", 1, "GO", 1, 0, 12)], [["SELECT 1", 1]])),
    (
        "row 2",
        "CREATE TABLE t (id INT);\nGO\nGO\nSELECT 1;\n",
        (
            "ok",
            [("CREATE TABLE t (id INT);", 1, "GO", 1, 0, 28), ("SELECT 1;", 4, None, 1, 31, 41)],
            [["CREATE TABLE t (id INT);", 1], ["SELECT 1;", 1]],
        ),
    ),
    (
        "row 3",
        "DECLARE @x INT = 1;\nSELECT @x;\nGO",
        (
            "ok",
            [("DECLARE @x INT = 1;\nSELECT @x;", 1, "GO", 1, 0, 33)],
            [["DECLARE @x INT = 1;\nSELECT @x;", 1]],
        ),
    ),
    (
        "row 4",
        "CREATE PROCEDURE p AS\nSELECT 1;\nSELECT 2;\nGO\nEXEC p;",
        (
            "ok",
            [
                ("CREATE PROCEDURE p AS\nSELECT 1;\nSELECT 2;", 1, "GO", 1, 0, 45),
                ("EXEC p;", 5, None, 1, 45, 52),
            ],
            [["CREATE PROCEDURE p AS\nSELECT 1;\nSELECT 2;", 1], ["EXEC p;", 1]],
        ),
    ),
    (
        "row 5",
        "SELECT 'GO\n' AS s\nGO",
        ("ok", [("SELECT 'GO\n' AS s", 1, "GO", 1, 0, 20)], [["SELECT 'GO\n' AS s", 1]]),
    ),
    (
        "row 5a",
        "SELECT 'a\nGO\nb' AS s\nGO",
        ("ok", [("SELECT 'a\nGO\nb' AS s", 1, "GO", 1, 0, 23)], [["SELECT 'a\nGO\nb' AS s", 1]]),
    ),
    (
        "row 5b",
        "CREATE TABLE [a\nGO\nb] (id INT)\nGO",
        (
            "ok",
            [("CREATE TABLE [a\nGO\nb] (id INT)", 1, "GO", 1, 0, 33)],
            [["CREATE TABLE [a\nGO\nb] (id INT)", 1]],
        ),
    ),
    (
        "row 5e",
        "SELECT 'a\rGO';\nGO",
        ("ok", [("SELECT 'a\rGO';", 1, "GO", 1, 0, 17)], [["SELECT 'a\rGO';", 1]]),
    ),
    (
        "row 5f",
        "SELECT [x\rGO];\nGO",
        ("ok", [("SELECT [x\rGO];", 1, "GO", 1, 0, 17)], [["SELECT [x\rGO];", 1]]),
    ),
    (
        "row 6",
        "/* a /* b */ GO */\nSELECT 1\nGO",
        (
            "error",
            "UnsafeStatementSplitError",
            "text after GO on line 1: only a count and a '--' comment may follow it",
        ),
    ),
    (
        "row 6a",
        "SELECT /* a /* b */ */ 1\nGO",
        (
            "ok",
            [("SELECT /* a /* b */ */ 1", 1, "GO", 1, 0, 27)],
            [["SELECT /* a /* b */ */ 1", 1]],
        ),
    ),
    (
        "row 6b",
        "SELECT 1 /* a\nGO\n*/\nGO",
        ("ok", [("SELECT 1 /* a\nGO\n*/", 1, "GO", 1, 0, 22)], [["SELECT 1 /* a\nGO\n*/", 1]]),
    ),
    (
        "row 6c",
        "SELECT 1 /* a\nGO\n/* b */\nGO\n*/",
        (
            "ok",
            [("SELECT 1 /* a\nGO\n/* b */", 1, "GO", 1, 0, 28), ("*/", 5, None, 1, 28, 30)],
            [["SELECT 1 /* a\nGO\n/* b */", 1], ["*/", 1]],
        ),
    ),
    (
        "row 7",
        "SELECT [go] FROM t\ngo -- end\n",
        ("ok", [("SELECT [go] FROM t", 1, "GO", 1, 0, 29)], [["SELECT [go] FROM t", 1]]),
    ),
    (
        "row 7a",
        "SELECT 1\nGO /* c */\nSELECT 2",
        (
            "error",
            "UnsafeStatementSplitError",
            "text after GO on line 2: only a count and a '--' comment may follow it",
        ),
    ),
    (
        "row 7b",
        "SELECT 1\nGO--c\nSELECT 2",
        (
            "error",
            "UnsafeStatementSplitError",
            "GO on line 2: GO must be followed by a blank, a count or end of line; '--' directly after GO is read "
            "differently by sqlcmd clients",
        ),
    ),
    (
        "row 8",
        "INSERT INTO t VALUES (1)\nGO 3\n",
        (
            "ok",
            [("INSERT INTO t VALUES (1)", 1, "GO", 3, 0, 30)],
            [["INSERT INTO t VALUES (1)", 3]],
        ),
    ),
    (
        "row 8a",
        "INSERT INTO t VALUES (1)\nGO 0\nSELECT 2",
        (
            "ok",
            [("INSERT INTO t VALUES (1)", 1, "GO", 0, 0, 30), ("SELECT 2", 3, None, 1, 30, 38)],
            [["SELECT 2", 1]],
        ),
    ),
    (
        "row 8b",
        "SELECT 1\nGO 5x\nSELECT 2",
        (
            "error",
            "UnsafeStatementSplitError",
            "text after GO on line 2: only a count and a '--' comment may follow it",
        ),
    ),
    (
        "row 9",
        "SELECT N'it''s'\nGO",
        ("ok", [("SELECT N'it''s'", 1, "GO", 1, 0, 18)], [["SELECT N'it''s'", 1]]),
    ),
    (
        "row 10",
        "MERGE t USING s ON 1=1 WHEN MATCHED THEN DELETE OUTPUT $action;\nGO",
        (
            "ok",
            [
                (
                    "MERGE t USING s ON 1=1 WHEN MATCHED THEN DELETE OUTPUT $action;",
                    1,
                    "GO",
                    1,
                    0,
                    66,
                )
            ],
            [["MERGE t USING s ON 1=1 WHEN MATCHED THEN DELETE OUTPUT $action;", 1]],
        ),
    ),
    ("row 12", "GOTO label\nGO", ("ok", [("GOTO label", 1, "GO", 1, 0, 13)], [["GOTO label", 1]])),
    (
        "row 12a",
        "SELECT\n    go.id\nFROM t AS go\nGO",
        (
            "ok",
            [("SELECT\n    go.id\nFROM t AS go", 1, "GO", 1, 0, 32)],
            [["SELECT\n    go.id\nFROM t AS go", 1]],
        ),
    ),
    (
        "row 12b",
        "SELECT\n    go,\n    2 AS b\nFROM t\nGO",
        (
            "ok",
            [("SELECT\n    go,\n    2 AS b\nFROM t", 1, "GO", 1, 0, 35)],
            [["SELECT\n    go,\n    2 AS b\nFROM t", 1]],
        ),
    ),
    ("row 13", "SELECT 1 GO", ("ok", [("SELECT 1 GO", 1, None, 1, 0, 11)], [["SELECT 1 GO", 1]])),
    (
        "row 14",
        "SELECT 1\nGO;",
        (
            "error",
            "UnsafeStatementSplitError",
            "text after GO on line 2: only a count and a '--' comment may follow it",
        ),
    ),
    (
        "row 15",
        "SELECT 1 AS go;\nSELECT 2;\nGO",
        (
            "ok",
            [("SELECT 1 AS go;\nSELECT 2;", 1, "GO", 1, 0, 28)],
            [["SELECT 1 AS go;\nSELECT 2;", 1]],
        ),
    ),
    (
        "row 16",
        "SELECT go INT FROM t;\nSELECT 2;\nGO",
        (
            "ok",
            [("SELECT go INT FROM t;\nSELECT 2;", 1, "GO", 1, 0, 34)],
            [["SELECT go INT FROM t;\nSELECT 2;", 1]],
        ),
    ),
    (
        "row 25",
        "SELECT 1 /* x\nGO\nSELECT 2",
        (
            "error",
            "UnsafeStatementSplitError",
            "unterminated block comment opened at line 1, column 10",
        ),
    ),
    (
        "row 26",
        "SELECT 'abc\nGO\n",
        ("error", "UnsafeStatementSplitError", "unterminated string opened at line 1, column 8"),
    ),
    (
        "row 27",
        "USE db\nCREATE PROCEDURE p AS SELECT 1\nGO",
        (
            "ok",
            [("USE db\nCREATE PROCEDURE p AS SELECT 1", 1, "GO", 1, 0, 40)],
            [["USE db\nCREATE PROCEDURE p AS SELECT 1", 1]],
        ),
    ),
    ("row 29", ";\nGO\nSELECT 2", ("ok", [("SELECT 2", 3, None, 1, 5, 13)], [["SELECT 2", 1]])),
    (
        "row 30",
        "SELECT 1\nGO 1000001",
        ("error", "UnsafeStatementSplitError", "GO 1000001 on line 2 exceeds the limit of 1000000"),
    ),
    (
        "clean 'GO'",
        "SELECT 1\nGO\nSELECT 2",
        (
            "ok",
            [("SELECT 1", 1, "GO", 1, 0, 12), ("SELECT 2", 3, None, 1, 12, 20)],
            [["SELECT 1", 1], ["SELECT 2", 1]],
        ),
    ),
    (
        "clean 'go'",
        "SELECT 1\ngo\nSELECT 2",
        (
            "ok",
            [("SELECT 1", 1, "GO", 1, 0, 12), ("SELECT 2", 3, None, 1, 12, 20)],
            [["SELECT 1", 1], ["SELECT 2", 1]],
        ),
    ),
    (
        "clean 'Go'",
        "SELECT 1\nGo\nSELECT 2",
        (
            "ok",
            [("SELECT 1", 1, "GO", 1, 0, 12), ("SELECT 2", 3, None, 1, 12, 20)],
            [["SELECT 1", 1], ["SELECT 2", 1]],
        ),
    ),
    (
        "clean '   GO'",
        "SELECT 1\n   GO\nSELECT 2",
        (
            "ok",
            [("SELECT 1", 1, "GO", 1, 0, 15), ("SELECT 2", 3, None, 1, 15, 23)],
            [["SELECT 1", 1], ["SELECT 2", 1]],
        ),
    ),
    (
        "clean '\\tGO   '",
        "SELECT 1\n\tGO   \nSELECT 2",
        (
            "ok",
            [("SELECT 1", 1, "GO", 1, 0, 16), ("SELECT 2", 3, None, 1, 16, 24)],
            [["SELECT 1", 1], ["SELECT 2", 1]],
        ),
    ),
    (
        "clean 'GO -- trailing'",
        "SELECT 1\nGO -- trailing\nSELECT 2",
        (
            "ok",
            [("SELECT 1", 1, "GO", 1, 0, 24), ("SELECT 2", 3, None, 1, 24, 32)],
            [["SELECT 1", 1], ["SELECT 2", 1]],
        ),
    ),
    (
        "clean 'GO 2'",
        "SELECT 1\nGO 2\nSELECT 2",
        (
            "ok",
            [("SELECT 1", 1, "GO", 2, 0, 14), ("SELECT 2", 3, None, 1, 14, 22)],
            [["SELECT 1", 2], ["SELECT 2", 1]],
        ),
    ),
    (
        "clean 'GO\\t2  '",
        "SELECT 1\nGO\t2  \nSELECT 2",
        (
            "ok",
            [("SELECT 1", 1, "GO", 2, 0, 16), ("SELECT 2", 3, None, 1, 16, 24)],
            [["SELECT 1", 2], ["SELECT 2", 1]],
        ),
    ),
    (
        "clean 'GO 002'",
        "SELECT 1\nGO 002\nSELECT 2",
        (
            "ok",
            [("SELECT 1", 1, "GO", 2, 0, 16), ("SELECT 2", 3, None, 1, 16, 24)],
            [["SELECT 1", 2], ["SELECT 2", 1]],
        ),
    ),
    (
        "clean 'GO 2 -- c'",
        "SELECT 1\nGO 2 -- c\nSELECT 2",
        (
            "ok",
            [("SELECT 1", 1, "GO", 2, 0, 19), ("SELECT 2", 3, None, 1, 19, 27)],
            [["SELECT 1", 2], ["SELECT 2", 1]],
        ),
    ),
    (
        "clean 'GO 0'",
        "SELECT 1\nGO 0\nSELECT 2",
        (
            "ok",
            [("SELECT 1", 1, "GO", 0, 0, 14), ("SELECT 2", 3, None, 1, 14, 22)],
            [["SELECT 2", 1]],
        ),
    ),
    (
        "clean 'GO --c'",
        "SELECT 1\nGO --c\nSELECT 2",
        (
            "ok",
            [("SELECT 1", 1, "GO", 1, 0, 16), ("SELECT 2", 3, None, 1, 16, 24)],
            [["SELECT 1", 1], ["SELECT 2", 1]],
        ),
    ),
    (
        "line 'GO foo'",
        "SELECT 1\nGO foo\nSELECT 2",
        (
            "error",
            "UnsafeStatementSplitError",
            "text after GO on line 2: only a count and a '--' comment may follow it",
        ),
    ),
    (
        "line 'GO 5x'",
        "SELECT 1\nGO 5x\nSELECT 2",
        (
            "error",
            "UnsafeStatementSplitError",
            "text after GO on line 2: only a count and a '--' comment may follow it",
        ),
    ),
    (
        "line 'GO -1'",
        "SELECT 1\nGO -1\nSELECT 2",
        (
            "error",
            "UnsafeStatementSplitError",
            "text after GO on line 2: only a count and a '--' comment may follow it",
        ),
    ),
    (
        "line 'GO +2'",
        "SELECT 1\nGO +2\nSELECT 2",
        (
            "error",
            "UnsafeStatementSplitError",
            "text after GO on line 2: only a count and a '--' comment may follow it",
        ),
    ),
    (
        "line 'GO 2 3'",
        "SELECT 1\nGO 2 3\nSELECT 2",
        (
            "error",
            "UnsafeStatementSplitError",
            "text after GO on line 2: only a count and a '--' comment may follow it",
        ),
    ),
    (
        "line 'GO ;'",
        "SELECT 1\nGO ;\nSELECT 2",
        (
            "error",
            "UnsafeStatementSplitError",
            "text after GO on line 2: only a count and a '--' comment may follow it",
        ),
    ),
    (
        "line 'GO;'",
        "SELECT 1\nGO;\nSELECT 2",
        (
            "error",
            "UnsafeStatementSplitError",
            "text after GO on line 2: only a count and a '--' comment may follow it",
        ),
    ),
    (
        "line 'GO /* c */'",
        "SELECT 1\nGO /* c */\nSELECT 2",
        (
            "error",
            "UnsafeStatementSplitError",
            "text after GO on line 2: only a count and a '--' comment may follow it",
        ),
    ),
    (
        "line 'GO /* c'",
        "SELECT 1\nGO /* c\nSELECT 2",
        (
            "error",
            "UnsafeStatementSplitError",
            "text after GO on line 2: only a count and a '--' comment may follow it",
        ),
    ),
    (
        "line 'GO // c'",
        "SELECT 1\nGO // c\nSELECT 2",
        (
            "error",
            "UnsafeStatementSplitError",
            "text after GO on line 2: only a count and a '--' comment may follow it",
        ),
    ),
    (
        "line 'go(1)'",
        "SELECT 1\ngo(1)\nSELECT 2",
        (
            "error",
            "UnsafeStatementSplitError",
            "text after GO on line 2: only a count and a '--' comment may follow it",
        ),
    ),
    (
        "line 'go = 1'",
        "SELECT 1\ngo = 1\nSELECT 2",
        (
            "error",
            "UnsafeStatementSplitError",
            "text after GO on line 2: only a count and a '--' comment may follow it",
        ),
    ),
    (
        "line 'GO[1]'",
        "SELECT 1\nGO[1]\nSELECT 2",
        (
            "error",
            "UnsafeStatementSplitError",
            "text after GO on line 2: only a count and a '--' comment may follow it",
        ),
    ),
    (
        "line \"GO'x'\"",
        "SELECT 1\nGO'x'\nSELECT 2",
        (
            "error",
            "UnsafeStatementSplitError",
            "text after GO on line 2: only a count and a '--' comment may follow it",
        ),
    ),
    (
        "line 'go/*c*/'",
        "SELECT 1\ngo/*c*/\nSELECT 2",
        (
            "error",
            "UnsafeStatementSplitError",
            "text after GO on line 2: only a count and a '--' comment may follow it",
        ),
    ),
    (
        "line 'GO--c'",
        "SELECT 1\nGO--c\nSELECT 2",
        (
            "error",
            "UnsafeStatementSplitError",
            "GO on line 2: GO must be followed by a blank, a count or end of line; '--' directly after GO is read "
            "differently by sqlcmd clients",
        ),
    ),
    (
        "line 'GO--'",
        "SELECT 1\nGO--\nSELECT 2",
        (
            "error",
            "UnsafeStatementSplitError",
            "GO on line 2: GO must be followed by a blank, a count or end of line; '--' directly after GO is read "
            "differently by sqlcmd clients",
        ),
    ),
    (
        "line 'go--end'",
        "SELECT 1\ngo--end\nSELECT 2",
        (
            "error",
            "UnsafeStatementSplitError",
            "GO on line 2: GO must be followed by a blank, a count or end of line; '--' directly after GO is read "
            "differently by sqlcmd clients",
        ),
    ),
    (
        "line '  GO--c'",
        "SELECT 1\n  GO--c\nSELECT 2",
        (
            "error",
            "UnsafeStatementSplitError",
            "GO on line 2: GO must be followed by a blank, a count or end of line; '--' directly after GO is read "
            "differently by sqlcmd clients",
        ),
    ),
    (
        "line 'GO--c --d'",
        "SELECT 1\nGO--c --d\nSELECT 2",
        (
            "error",
            "UnsafeStatementSplitError",
            "GO on line 2: GO must be followed by a blank, a count or end of line; '--' directly after GO is read "
            "differently by sqlcmd clients",
        ),
    ),
    (
        "line 'GO 2--c'",
        "SELECT 1\nGO 2--c\nSELECT 2",
        (
            "error",
            "UnsafeStatementSplitError",
            "GO on line 2: GO must be followed by a blank, a count or end of line; '--' directly after GO is read "
            "differently by sqlcmd clients",
        ),
    ),
    (
        "line 'GO 0--'",
        "SELECT 1\nGO 0--\nSELECT 2",
        (
            "error",
            "UnsafeStatementSplitError",
            "GO on line 2: GO must be followed by a blank, a count or end of line; '--' directly after GO is read "
            "differently by sqlcmd clients",
        ),
    ),
    (
        "word 'GOTO label'",
        "SELECT 1\nGOTO label\nGO",
        ("ok", [("SELECT 1\nGOTO label", 1, "GO", 1, 0, 22)], [["SELECT 1\nGOTO label", 1]]),
    ),
    (
        "word 'GOO'",
        "SELECT 1\nGOO\nGO",
        ("ok", [("SELECT 1\nGOO", 1, "GO", 1, 0, 15)], [["SELECT 1\nGOO", 1]]),
    ),
    (
        "word 'GO_ON'",
        "SELECT 1\nGO_ON\nGO",
        ("ok", [("SELECT 1\nGO_ON", 1, "GO", 1, 0, 17)], [["SELECT 1\nGO_ON", 1]]),
    ),
    (
        "word 'GO$x'",
        "SELECT 1\nGO$x\nGO",
        ("ok", [("SELECT 1\nGO$x", 1, "GO", 1, 0, 16)], [["SELECT 1\nGO$x", 1]]),
    ),
    (
        "word 'GOLD INT'",
        "SELECT 1\nGOLD INT\nGO",
        ("ok", [("SELECT 1\nGOLD INT", 1, "GO", 1, 0, 20)], [["SELECT 1\nGOLD INT", 1]]),
    ),
    (
        "word '[go]'",
        "SELECT 1\n[go]\nGO",
        ("ok", [("SELECT 1\n[go]", 1, "GO", 1, 0, 16)], [["SELECT 1\n[go]", 1]]),
    ),
    (
        "word 'dbo.go'",
        "SELECT 1\ndbo.go\nGO",
        ("ok", [("SELECT 1\ndbo.go", 1, "GO", 1, 0, 18)], [["SELECT 1\ndbo.go", 1]]),
    ),
    (
        "word 'go.id'",
        "SELECT 1\ngo.id\nGO",
        ("ok", [("SELECT 1\ngo.id", 1, "GO", 1, 0, 17)], [["SELECT 1\ngo.id", 1]]),
    ),
    (
        "word 'go,'",
        "SELECT 1\ngo,\nGO",
        ("ok", [("SELECT 1\ngo,", 1, "GO", 1, 0, 15)], [["SELECT 1\ngo,", 1]]),
    ),
    (
        "word 'go@x'",
        "SELECT 1\ngo@x\nGO",
        ("ok", [("SELECT 1\ngo@x", 1, "GO", 1, 0, 16)], [["SELECT 1\ngo@x", 1]]),
    ),
    (
        "word 'go+1'",
        "SELECT 1\ngo+1\nGO",
        ("ok", [("SELECT 1\ngo+1", 1, "GO", 1, 0, 16)], [["SELECT 1\ngo+1", 1]]),
    ),
    (
        "word 'go)'",
        "SELECT 1\ngo)\nGO",
        ("ok", [("SELECT 1\ngo)", 1, "GO", 1, 0, 15)], [["SELECT 1\ngo)", 1]]),
    ),
    (
        "word 'go*2'",
        "SELECT 1\ngo*2\nGO",
        ("ok", [("SELECT 1\ngo*2", 1, "GO", 1, 0, 16)], [["SELECT 1\ngo*2", 1]]),
    ),
    (
        "word 'go:x'",
        "SELECT 1\ngo:x\nGO",
        ("ok", [("SELECT 1\ngo:x", 1, "GO", 1, 0, 16)], [["SELECT 1\ngo:x", 1]]),
    ),
    (
        "word 'go|1'",
        "SELECT 1\ngo|1\nGO",
        ("ok", [("SELECT 1\ngo|1", 1, "GO", 1, 0, 16)], [["SELECT 1\ngo|1", 1]]),
    ),
    (
        "word 'go<1'",
        "SELECT 1\ngo<1\nGO",
        ("ok", [("SELECT 1\ngo<1", 1, "GO", 1, 0, 16)], [["SELECT 1\ngo<1", 1]]),
    ),
    (
        "comment 'SELECT 1\\n/* c */ GO\\nSELECT 2'",
        "SELECT 1\n/* c */ GO\nSELECT 2",
        (
            "error",
            "UnsafeStatementSplitError",
            "GO after a comment on line 2: sqlcmd takes it as a command after one comment and as text after two; put "
            "it first on its line",
        ),
    ),
    (
        "comment 'SELECT 1\\n/* a */ /* b */ GO\\nSELECT 2'",
        "SELECT 1\n/* a */ /* b */ GO\nSELECT 2",
        (
            "error",
            "UnsafeStatementSplitError",
            "GO after a comment on line 2: sqlcmd takes it as a command after one comment and as text after two; put "
            "it first on its line",
        ),
    ),
    (
        "comment '/* a\\nb */ GO\\nSELECT 2'",
        "/* a\nb */ GO\nSELECT 2",
        (
            "error",
            "UnsafeStatementSplitError",
            "GO after a comment on line 2: sqlcmd takes it as a command after one comment and as text after two; put "
            "it first on its line",
        ),
    ),
    (
        "comment 'SELECT /* a\\n b */ GO\\nSELECT 2'",
        "SELECT /* a\n b */ GO\nSELECT 2",
        (
            "error",
            "UnsafeStatementSplitError",
            "GO after a comment on line 2: sqlcmd takes it as a command after one comment and as text after two; put "
            "it first on its line",
        ),
    ),
    (
        "comment '/* a /* b */ GO */\\nSELECT 1\\nGO'",
        "/* a /* b */ GO */\nSELECT 1\nGO",
        (
            "error",
            "UnsafeStatementSplitError",
            "text after GO on line 1: only a count and a '--' comment may follow it",
        ),
    ),
    (
        "head 'SELECT 1 GO'",
        "SELECT 1 GO",
        ("ok", [("SELECT 1 GO", 1, None, 1, 0, 11)], [["SELECT 1 GO", 1]]),
    ),
    (
        "head 'SELECT 1 AS go'",
        "SELECT 1 AS go",
        ("ok", [("SELECT 1 AS go", 1, None, 1, 0, 14)], [["SELECT 1 AS go", 1]]),
    ),
    ("head 'x;GO'", "x;GO", ("ok", [("x;GO", 1, None, 1, 0, 4)], [["x;GO", 1]])),
    (
        "head \"SELECT 'a' GO\"",
        "SELECT 'a' GO",
        ("ok", [("SELECT 'a' GO", 1, None, 1, 0, 13)], [["SELECT 'a' GO", 1]]),
    ),
    (
        "head 'SELECT [a] GO'",
        "SELECT [a] GO",
        ("ok", [("SELECT [a] GO", 1, None, 1, 0, 13)], [["SELECT [a] GO", 1]]),
    ),
    (
        "head 'SELECT 1 /* c */ GO'",
        "SELECT 1 /* c */ GO",
        ("ok", [("SELECT 1 /* c */ GO", 1, None, 1, 0, 19)], [["SELECT 1 /* c */ GO", 1]]),
    ),
    (
        "head \"SELECT 'GO\\n'\"",
        "SELECT 'GO\n'",
        ("ok", [("SELECT 'GO\n'", 1, None, 1, 0, 12)], [["SELECT 'GO\n'", 1]]),
    ),
    (
        "head 'SELECT [go]\\nGO'",
        "SELECT [go]\nGO",
        ("ok", [("SELECT [go]", 1, "GO", 1, 0, 14)], [["SELECT [go]", 1]]),
    ),
    (
        "head 'SELECT \"a\\nGO\\nb\"\\nGO'",
        'SELECT "a\nGO\nb"\nGO',
        ("ok", [('SELECT "a\nGO\nb"', 1, "GO", 1, 0, 18)], [['SELECT "a\nGO\nb"', 1]]),
    ),
    (
        "head 'SELECT 1 -- c\\nGO'",
        "SELECT 1 -- c\nGO",
        ("ok", [("SELECT 1 -- c", 1, "GO", 1, 0, 16)], [["SELECT 1 -- c", 1]]),
    ),
    (
        "head '-- c\\nGO\\nSELECT 1'",
        "-- c\nGO\nSELECT 1",
        ("ok", [("SELECT 1", 3, None, 1, 8, 16)], [["SELECT 1", 1]]),
    ),
    (
        "head 'SELECT 1\\n-- c\\n-- d\\nGO'",
        "SELECT 1\n-- c\n-- d\nGO",
        ("ok", [("SELECT 1\n-- c\n-- d", 1, "GO", 1, 0, 21)], [["SELECT 1\n-- c\n-- d", 1]]),
    ),
    (
        "nonblank 'SELECT 1\\n\\xa0GO\\nSELECT 2'",
        "SELECT 1\n\xa0GO\nSELECT 2",
        (
            "ok",
            [("SELECT 1\n\xa0GO\nSELECT 2", 1, None, 1, 0, 21)],
            [["SELECT 1\n\xa0GO\nSELECT 2", 1]],
        ),
    ),
    (
        "nonblank 'SELECT 1\\n\\x0cGO\\nSELECT 2'",
        "SELECT 1\n\x0cGO\nSELECT 2",
        (
            "ok",
            [("SELECT 1\n\x0cGO\nSELECT 2", 1, None, 1, 0, 21)],
            [["SELECT 1\n\x0cGO\nSELECT 2", 1]],
        ),
    ),
    (
        "nonblank 'SELECT 1\\n\\x1cGO\\nSELECT 2'",
        "SELECT 1\n\x1cGO\nSELECT 2",
        (
            "ok",
            [("SELECT 1\n\x1cGO\nSELECT 2", 1, None, 1, 0, 21)],
            [["SELECT 1\n\x1cGO\nSELECT 2", 1]],
        ),
    ),
    (
        "nonblank 'SELECT 1\\n\\x85GO\\nSELECT 2'",
        "SELECT 1\n\x85GO\nSELECT 2",
        (
            "ok",
            [("SELECT 1\n\x85GO\nSELECT 2", 1, None, 1, 0, 21)],
            [["SELECT 1\n\x85GO\nSELECT 2", 1]],
        ),
    ),
    (
        "nonblank 'SELECT 1\\n\\u2028GO\\nSELECT 2'",
        "SELECT 1\n\u2028GO\nSELECT 2",
        (
            "ok",
            [("SELECT 1\n\u2028GO\nSELECT 2", 1, None, 1, 0, 21)],
            [["SELECT 1\n\u2028GO\nSELECT 2", 1]],
        ),
    ),
    (
        "nonblank 'SELECT 1\\n\\x0bGO\\nSELECT 2'",
        "SELECT 1\n\x0bGO\nSELECT 2",
        (
            "ok",
            [("SELECT 1\n\x0bGO\nSELECT 2", 1, None, 1, 0, 21)],
            [["SELECT 1\n\x0bGO\nSELECT 2", 1]],
        ),
    ),
    (
        "nonblank 'SELECT 1\\n/* c */\\xa0GO\\nSELECT 2'",
        "SELECT 1\n/* c */\xa0GO\nSELECT 2",
        (
            "ok",
            [("SELECT 1\n/* c */\xa0GO\nSELECT 2", 1, None, 1, 0, 28)],
            [["SELECT 1\n/* c */\xa0GO\nSELECT 2", 1]],
        ),
    ),
    (
        "nonblank 'SELECT 1\\n/* c */\\x1cGO\\nSELECT 2'",
        "SELECT 1\n/* c */\x1cGO\nSELECT 2",
        (
            "ok",
            [("SELECT 1\n/* c */\x1cGO\nSELECT 2", 1, None, 1, 0, 28)],
            [["SELECT 1\n/* c */\x1cGO\nSELECT 2", 1]],
        ),
    ),
    (
        "nonblank 'SELECT 1\\n\\xa0GO\\nGO'",
        "SELECT 1\n\xa0GO\nGO",
        ("ok", [("SELECT 1\n\xa0GO", 1, "GO", 1, 0, 15)], [["SELECT 1\n\xa0GO", 1]]),
    ),
    (
        "nonblank 'SELECT 1\\n\\x1dGO\\nSELECT 2'",
        "SELECT 1\n\x1dGO\nSELECT 2",
        (
            "ok",
            [("SELECT 1\n\x1dGO\nSELECT 2", 1, None, 1, 0, 21)],
            [["SELECT 1\n\x1dGO\nSELECT 2", 1]],
        ),
    ),
    (
        "nonblank 'SELECT 1\\n\\x1eGO\\nSELECT 2'",
        "SELECT 1\n\x1eGO\nSELECT 2",
        (
            "ok",
            [("SELECT 1\n\x1eGO\nSELECT 2", 1, None, 1, 0, 21)],
            [["SELECT 1\n\x1eGO\nSELECT 2", 1]],
        ),
    ),
    (
        "nonblank 'SELECT 1\\n\\x1fGO\\nSELECT 2'",
        "SELECT 1\n\x1fGO\nSELECT 2",
        (
            "ok",
            [("SELECT 1\n\x1fGO\nSELECT 2", 1, None, 1, 0, 21)],
            [["SELECT 1\n\x1fGO\nSELECT 2", 1]],
        ),
    ),
    (
        "nonblank 'SELECT 1\\n\\u2029GO\\nSELECT 2'",
        "SELECT 1\n\u2029GO\nSELECT 2",
        (
            "ok",
            [("SELECT 1\n\u2029GO\nSELECT 2", 1, None, 1, 0, 21)],
            [["SELECT 1\n\u2029GO\nSELECT 2", 1]],
        ),
    ),
    (
        "bom",
        "\ufeffSELECT 1\nGO\nSELECT 2",
        (
            "ok",
            [("SELECT 1", 1, "GO", 1, 1, 13), ("SELECT 2", 3, None, 1, 13, 21)],
            [["SELECT 1", 1], ["SELECT 2", 1]],
        ),
    ),
    ("bom go", "\ufeffGO\nSELECT 1", ("ok", [("SELECT 1", 2, None, 1, 4, 12)], [["SELECT 1", 1]])),
    (
        "comment only",
        "-- only\nGO\nSELECT 2",
        ("ok", [("SELECT 2", 3, None, 1, 11, 19)], [["SELECT 2", 1]]),
    ),
    (
        "lead comment",
        "-- c\nSELECT 1\nGO",
        ("ok", [("-- c\nSELECT 1", 1, "GO", 1, 0, 16)], [["-- c\nSELECT 1", 1]]),
    ),
    (
        "crlf",
        "SELECT 1\r\nGO\r\nSELECT 2\r\nGO 2\r\n",
        (
            "ok",
            [("SELECT 1", 1, "GO", 1, 0, 14), ("SELECT 2", 3, "GO", 2, 14, 30)],
            [["SELECT 1", 1], ["SELECT 2", 2]],
        ),
    ),
    (
        "tail",
        "SELECT 1\nGO\nSELECT 2;",
        (
            "ok",
            [("SELECT 1", 1, "GO", 1, 0, 12), ("SELECT 2;", 3, None, 1, 12, 21)],
            [["SELECT 1", 1], ["SELECT 2;", 1]],
        ),
    ),
    ("go last", "SELECT 1\nGO", ("ok", [("SELECT 1", 1, "GO", 1, 0, 11)], [["SELECT 1", 1]])),
    ("go last 0", "SELECT 1\nGO 0", ("ok", [("SELECT 1", 1, "GO", 0, 0, 13)], [])),
    (
        "go zero",
        "INSERT INTO t VALUES (1)\nGO 0\nSELECT 2",
        (
            "ok",
            [("INSERT INTO t VALUES (1)", 1, "GO", 0, 0, 30), ("SELECT 2", 3, None, 1, 30, 38)],
            [["SELECT 2", 1]],
        ),
    ),
    (
        "go three",
        "INSERT INTO t VALUES (1)\nGO 3\n",
        (
            "ok",
            [("INSERT INTO t VALUES (1)", 1, "GO", 3, 0, 30)],
            [["INSERT INTO t VALUES (1)", 3]],
        ),
    ),
    (
        "blank lines",
        "\n  SELECT 1  /* c */\n\n  -- note\nGO\n",
        (
            "ok",
            [("SELECT 1  /* c */\n\n  -- note", 2, "GO", 1, 0, 35)],
            [["SELECT 1  /* c */\n\n  -- note", 1]],
        ),
    ),
    (
        "lines",
        "SELECT 1\nGO\n\n\n-- header\nSELECT 2\nGO\n",
        (
            "ok",
            [("SELECT 1", 1, "GO", 1, 0, 12), ("-- header\nSELECT 2", 5, "GO", 1, 12, 36)],
            [["SELECT 1", 1], ["-- header\nSELECT 2", 1]],
        ),
    ),
    ("nbsp", "\xa0", ("ok", [], [])),
    ("ff", "\x0c", ("ok", [], [])),
    ("spaces", "  \n", ("ok", [], [])),
    ("empty", "", ("ok", [], [])),
    ("vt", "\x0b", ("ok", [], [])),
    ("semi", "; ;\n", ("ok", [], [])),
    ("semis", ";;", ("ok", [], [])),
    ("semi row", "\n;\nGO\nSELECT 2", ("ok", [("SELECT 2", 4, None, 1, 6, 14)], [["SELECT 2", 1]])),
    (
        "placeholder",
        "SELECT ${a\nGO\nSELECT 2}",
        (
            "ok",
            [("SELECT ${a", 1, "GO", 1, 0, 14), ("SELECT 2}", 3, None, 1, 14, 23)],
            [["SELECT ${a", 1], ["SELECT 2}", 1]],
        ),
    ),
    (
        "comment between",
        "SELECT /* c */ 1\nGO",
        ("ok", [("SELECT /* c */ 1", 1, "GO", 1, 0, 19)], [["SELECT /* c */ 1", 1]]),
    ),
    (
        "after go comment",
        "SELECT 1\n/* a */\nGO\n/* b */ SELECT 2",
        (
            "ok",
            [("SELECT 1\n/* a */", 1, "GO", 1, 0, 20), ("/* b */ SELECT 2", 4, None, 1, 20, 36)],
            [["SELECT 1\n/* a */", 1], ["/* b */ SELECT 2", 1]],
        ),
    ),
    (
        "two gos",
        "GO\nGO\nSELECT 1\nGO\nGO",
        ("ok", [("SELECT 1", 3, "GO", 1, 6, 18)], [["SELECT 1", 1]]),
    ),
    (
        "go spaces eof",
        "SELECT 1\n  GO  ",
        ("ok", [("SELECT 1", 1, "GO", 1, 0, 15)], [["SELECT 1", 1]]),
    ),
    (
        "count 1000000",
        "SELECT 1\nGO 1000000\n",
        ("ok", [("SELECT 1", 1, "GO", 1000000, 0, 20)], [["SELECT 1", 1000000]]),
    ),
    (
        "count 1000001",
        "SELECT 1\nGO 1000001\n",
        ("error", "UnsafeStatementSplitError", "GO 1000001 on line 2 exceeds the limit of 1000000"),
    ),
    (
        "count 7 digits",
        "SELECT 1\nGO 0009999999\n",
        ("error", "UnsafeStatementSplitError", "GO 9999999 on line 2 exceeds the limit of 1000000"),
    ),
    (
        "count 8 digits",
        "SELECT 1\nGO 10000000\n",
        ("error", "UnsafeStatementSplitError", "GO count on line 2 exceeds the limit of 1000000"),
    ),
    (
        "count zeros",
        "SELECT 1\nGO 00000000000000000000000000000000000000000000000000\n",
        ("ok", [("SELECT 1", 1, "GO", 0, 0, 63)], []),
    ),
    ("count 3", "SELECT 1\nGO 3\n", ("ok", [("SELECT 1", 1, "GO", 3, 0, 14)], [["SELECT 1", 3]])),
    ("count 4", "SELECT 1\nGO 4\n", ("ok", [("SELECT 1", 1, "GO", 4, 0, 14)], [["SELECT 1", 4]])),
    (
        "unterminated string",
        "SELECT 'abc",
        ("error", "UnsafeStatementSplitError", "unterminated string opened at line 1, column 8"),
    ),
    (
        "unterminated bracket",
        "SELECT [abc",
        (
            "error",
            "UnsafeStatementSplitError",
            "unterminated bracketed identifier opened at line 1, column 8",
        ),
    ),
    (
        "unterminated quoted",
        'SELECT "abc',
        (
            "error",
            "UnsafeStatementSplitError",
            "unterminated quoted identifier opened at line 1, column 8",
        ),
    ),
    (
        "unterminated comment",
        "SELECT 1 /* x",
        (
            "error",
            "UnsafeStatementSplitError",
            "unterminated block comment opened at line 1, column 10",
        ),
    ),
    (
        "unterminated with go",
        "SELECT 'abc\nGO\n",
        ("error", "UnsafeStatementSplitError", "unterminated string opened at line 1, column 8"),
    ),
]


def engine(spec=SQLSERVER_SPEC):
    return LexicalEngine(spec)


def records(script, spec=SQLSERVER_SPEC):
    return [
        (r.text, r.line, r.terminator, r.repeat, r.source_start, r.source_end)
        for r in engine(spec).split(script)
    ]


def strings(script, spec=SQLSERVER_SPEC):
    return [[k, len(list(g))] for k, g in itertools.groupby(engine(spec).split_statements(script))]


def texts(script, spec=SQLSERVER_SPEC):
    return [r.text for r in engine(spec).split(script)]


@pytest.mark.parametrize("name, script, outcome", CASES, ids=[c[0] for c in CASES])
def test_matches_the_recorded_outcome(name, script, outcome):
    if outcome[0] == "error":
        _, error_class, message = outcome
        for call in (records, strings):
            with pytest.raises(UnsafeStatementSplitError) as raised:
                call(script)
            assert (type(raised.value).__name__, str(raised.value)) == (error_class, message)
        return
    _, expected_records, expected_strings = outcome
    assert records(script) == expected_records
    assert strings(script) == expected_strings


@pytest.mark.parametrize(
    "line, count",
    [("GO", 1), ("go", 1), ("   GO", 1), ("GO\t2  ", 2), ("GO 002", 2), ("GO 0", 0)],
)
def test_go_line_separates_with_its_count(line, count):
    found = engine().split(f"SELECT 1\n{line}\nSELECT 2")
    assert [(r.text, r.repeat) for r in found] == [("SELECT 1", count), ("SELECT 2", 1)]


@pytest.mark.parametrize("line", ["GO--c", "GO 2--c", "go--end"])
def test_glued_comment_refused(line):
    with pytest.raises(UnsafeStatementSplitError, match="directly after GO") as raised:
        engine().split(f"SELECT 1\n{line}\nSELECT 2")
    assert "line 2" in str(raised.value)


@pytest.mark.parametrize(
    "script",
    [
        "SELECT 1\n/* c */ GO\nSELECT 2",
        "SELECT 1\n/* a */ /* b */ GO\nSELECT 2",
        "/* a\nb */ GO\nSELECT 2",
    ],
)
def test_go_after_a_comment_is_refused(script):
    with pytest.raises(UnsafeStatementSplitError, match="GO after a comment"):
        engine().split(script)


@pytest.mark.parametrize(
    "script",
    [
        "SELECT 1 GO",
        "SELECT 1 AS go",
        "x;GO",
        "SELECT 'a' GO",
        "SELECT [a] GO",
        "SELECT 'a\nGO\nb'",
        "SELECT [a\nGO\nb]",
        'SELECT "a\nGO\nb"',
        "SELECT 1 /* a\nGO\nb */",
        "SELECT 1 -- c GO",
    ],
)
def test_command_is_read_only_at_the_line_head(script):
    assert texts(script) == [script]


def test_count_limit_is_the_spec_field():
    rules = replace(SQLSERVER_SPEC.batch_script, max_repeat=3)
    spec = replace(SQLSERVER_SPEC, batch_script=rules)
    assert len(engine(spec).split_statements("SELECT 1\nGO 3\n")) == 3
    with pytest.raises(UnsafeStatementSplitError, match="GO 4 on line 2 exceeds the limit of 3"):
        engine(spec).split("SELECT 1\nGO 4\n")
    assert engine().split("SELECT 1\nGO 1000000\n")[0].repeat == 1_000_000
    with pytest.raises(UnsafeStatementSplitError, match="GO 1000001 on line 2 exceeds the limit"):
        engine().split("SELECT 1\nGO 1000001\n")


@pytest.mark.parametrize(
    "digits",
    ["9" * 5000, "0" * 5000 + "9" * 7, "1" + "0" * 7],
    ids=["nines", "zeros-then-nines", "ten-million"],
)
def test_a_count_with_more_digits_than_the_limit_allows_is_refused(digits):
    with pytest.raises(UnsafeStatementSplitError, match="exceeds the limit"):
        engine().split(f"SELECT 1\nGO {digits}\n")


def test_a_count_of_only_zeros_is_go_zero_however_long():
    assert engine().split("SELECT 1\nGO " + "0" * 5000 + "\n")[0].repeat == 0


def test_record_fields_that_do_not_compare_are_asserted():
    first, second = engine().split("\ufeffSELECT 1\nGO\nSELECT 2")
    assert (first.source_start, first.source_end, first.line) == (1, 13, 1)
    assert (second.source_start, second.source_end, second.line) == (13, 21, 3)
    assert (first.kind, first.multi, first.analysis_statements) == ("sql", False, ("SELECT 1",))


def test_split_statements_repeats_and_go_zero_logs(caplog):
    with caplog.at_level(logging.INFO, logger="dblift.core.sql_parser.lexical_engine"):
        assert engine().split_statements("INSERT INTO t VALUES (1)\nGO 0\nSELECT 2") == ["SELECT 2"]
    notice = [r for r in caplog.records if "GO 0 follows" in r.getMessage()]
    assert [(r.name, r.levelname, r.getMessage()) for r in notice] == [
        (
            "dblift.core.sql_parser.lexical_engine",
            "INFO",
            "GO 0 follows the batch starting on line 1: it is not run",
        )
    ]
    assert engine().split_statements("SELECT 1\nGO 3\n") == ["SELECT 1"] * 3


@pytest.mark.parametrize(
    "script, expected",
    [("\n;\nGO\nSELECT 2", ["SELECT 2"]), ("; ;\n", []), (";;", [])],
)
def test_semicolon_only_batch_is_not_a_statement(script, expected):
    assert texts(script) == expected


@pytest.mark.parametrize(
    "blank", ["\xa0", "\x0c", "\x1c", "\x1d", "\x1e", "\x1f", "\x85", "\u2028", "\u2029", "\x0b"]
)
def test_a_non_blank_before_go_makes_it_text(blank):
    script = f"SELECT 1\n{blank}GO\nSELECT 2"
    assert texts(script) == [script]
    assert texts(f"SELECT 1\n/* c */{blank}GO\nSELECT 2") == [
        f"SELECT 1\n/* c */{blank}GO\nSELECT 2"
    ]


@pytest.mark.parametrize("script", ["\xa0", "\x0c", "\x0b"])
def test_blank_but_not_empty_input_has_no_record(script):
    assert records(script) == []
    assert strings(script) == []


@pytest.mark.parametrize("script", ["  \n", ""])
def test_an_empty_script_has_no_record(script):
    assert records(script) == []
    assert strings(script) == []


def test_batch_script_reads_comment_extents():
    assert texts("-- only\nGO\nSELECT 2") == ["SELECT 2"]
    assert records("-- only\nGO\nSELECT 2")[0][4] == 11
    assert texts("SELECT /* c */ 1\nGO") == ["SELECT /* c */ 1"]
    assert texts("SELECT 1\n/* a */\nGO\n/* b */ SELECT 2") == [
        "SELECT 1\n/* a */",
        "/* b */ SELECT 2",
    ]


def test_placeholder_batches():
    assert texts("SELECT ${a\nGO\nSELECT 2}") == ["SELECT ${a", "SELECT 2}"]


@pytest.mark.parametrize(
    "script, wording",
    [
        ("SELECT 'abc", "unterminated string opened at line 1, column 8"),
        ("SELECT [abc", "unterminated bracketed identifier opened at line 1, column 8"),
        ('SELECT "abc', "unterminated quoted identifier opened at line 1, column 8"),
        ("SELECT 1 /* x", "unterminated block comment opened at line 1, column 10"),
    ],
)
def test_unterminated_lexemes_use_the_shared_wording(script, wording):
    with pytest.raises(UnsafeStatementSplitError, match=wording):
        engine().split(script)


@pytest.mark.parametrize(
    "script",
    [
        "SELECT 1\n\xa0 /* c */ GO\nSELECT 2",
        "SELECT 1\n\x1c/* a */ /* b */ go\nSELECT 2",
    ],
)
def test_a_comment_after_a_non_blank_does_not_restore_the_line_head(script):
    assert texts(script) == [script]


def test_a_comment_that_began_on_an_earlier_line_restores_the_line_head():
    with pytest.raises(UnsafeStatementSplitError, match="GO after a comment on line 3"):
        engine().split("SELECT 1\n\x0c/* a\nb */ GO\nSELECT 2")


def varied(**changes):
    return replace(SQLSERVER_SPEC, batch_script=replace(SQLSERVER_SPEC.batch_script, **changes))


def test_separator_is_a_spec_field():
    spec = varied(separator="STOP")
    assert texts("SELECT 1\nSTOP\nSELECT 2", spec) == ["SELECT 1", "SELECT 2"]
    assert texts("SELECT 1\nGO\nSELECT 2", spec) == ["SELECT 1\nGO\nSELECT 2"]


def test_word_alphabet_is_a_spec_field():
    assert texts("SELECT 1\nGO 2\nSELECT 2", varied(word_part="A-Za-z0-9_@#$ ")) == [
        "SELECT 1\nGO 2\nSELECT 2"
    ]
    assert texts("SELECT 1\nGO\nSELECT 2", varied(word_start="A-FH-Za-z_@#$")) == [
        "SELECT 1\nGO\nSELECT 2"
    ]


def test_command_followers_are_a_spec_field():
    with pytest.raises(UnsafeStatementSplitError, match="directly after GO"):
        engine().split("SELECT 1\nGO--c\nSELECT 2")
    assert texts("SELECT 1\nGO--c\nSELECT 2", varied(command_followers=frozenset(" \t\r"))) == [
        "SELECT 1\nGO--c\nSELECT 2"
    ]


def test_tail_comment_is_a_spec_field():
    assert texts("SELECT 1\nGO # c\nSELECT 2", varied(tail_comment="#")) == ["SELECT 1", "SELECT 2"]
    with pytest.raises(UnsafeStatementSplitError, match="only a count and a '#' comment"):
        engine(varied(tail_comment="#")).split("SELECT 1\nGO -- c\nSELECT 2")


def test_blanks_are_a_spec_field():
    script = "SELECT 1\n\xa0GO\nSELECT 2"
    assert texts(script) == [script]
    assert texts(script, varied(blanks=" \t\r\xa0")) == ["SELECT 1", "SELECT 2"]


def test_ignored_in_code_is_a_spec_field():
    assert texts(",\nGO\nSELECT 2") == [",", "SELECT 2"]
    assert texts(",\nGO\nSELECT 2", varied(ignored_in_code=";,")) == ["SELECT 2"]


def test_separator_followers_are_a_spec_field():
    with pytest.raises(UnsafeStatementSplitError, match="text after GO on line 2"):
        engine().split("SELECT 1\nGO;\nSELECT 2")
    assert texts("SELECT 1\nGO;\nSELECT 2", varied(separator_followers=frozenset())) == [
        "SELECT 1\nGO;\nSELECT 2"
    ]
    assert texts("SELECT 1\nGO,\nSELECT 2") == ["SELECT 1\nGO,\nSELECT 2"]
    with pytest.raises(UnsafeStatementSplitError, match="text after GO on line 2"):
        engine(varied(separator_followers=frozenset(";,"))).split("SELECT 1\nGO,\nSELECT 2")


def test_the_comment_marker_of_the_glue_check_is_the_spec_field():
    spec = varied(tail_comment="=")
    with pytest.raises(UnsafeStatementSplitError, match="'=' directly after GO"):
        engine(spec).split("SELECT 1\nGO=c\nSELECT 2")
    with pytest.raises(UnsafeStatementSplitError, match="text after GO on line 2"):
        engine().split("SELECT 1\nGO=c\nSELECT 2")


def test_the_blanks_of_the_separator_tail_are_the_spec_field():
    spec = varied(blanks=" \t\r\xa0", command_followers=frozenset(" \t\r\xa0-=(['/"))
    assert texts("SELECT 1\nGO\xa0\nSELECT 2", spec) == ["SELECT 1", "SELECT 2"]
    assert texts("SELECT 1\nGO\xa0\nSELECT 2") == ["SELECT 1\nGO\xa0\nSELECT 2"]
