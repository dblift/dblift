"""How a SQL Server batch is divided into the statements analysis reads.

Expected values were recorded from the heuristic this engine replaces (the analysis
statements of every batch record, or the refusal).
"""

from dataclasses import replace

import pytest

from dblift.core.sql_parser.lexical_engine import LexicalEngine
from dblift.db.plugins.sqlserver.parser.lexical_spec import SQLSERVER_SPEC

# Recorded: (name, script, outcome). Outcome: ("ok", analysis tuples per record) or ("error", class, message).
CASES = [
    (
        "case 0",
        "DECLARE @x INT = 1;\nSELECT @x;\nGO\nCREATE TABLE a (id INT);\nCREATE INDEX ix_a ON a (id);\n",
        (
            "ok",
            [
                ("DECLARE @x INT = 1;", "SELECT @x;"),
                ("CREATE TABLE a (id INT);", "CREATE INDEX ix_a ON a (id);"),
            ],
        ),
    ),
    (
        "case 1",
        "INSERT INTO t VALUES (1);\nINSERT INTO t VALUES (2);\nGO 3\n",
        ("ok", [("INSERT INTO t VALUES (1);", "INSERT INTO t VALUES (2);")]),
    ),
    (
        "case 2",
        "INSERT INTO t VALUES (1);\nGO 0\nSELECT 2;\n",
        ("ok", [("INSERT INTO t VALUES (1);",), ("SELECT 2;",)]),
    ),
    (
        "case 3",
        "SELECT 'a;b'; /* ; */ SELECT 2;\n"
        "GO\n"
        "CREATE PROCEDURE dbo.p AS\n"
        "BEGIN\n"
        "  SELECT 1;\n"
        "  SELECT 2;\n"
        "END;\n"
        "GO\n",
        (
            "ok",
            [
                ("SELECT 'a;b';", "/* ; */ SELECT 2;"),
                ("CREATE PROCEDURE dbo.p AS\nBEGIN\n  SELECT 1;\n  SELECT 2;\nEND;",),
            ],
        ),
    ),
    ("case 4", "SELECT [a;b]; SELECT 2;", ("ok", [("SELECT [a;b];", "SELECT 2;")])),
    ("case 5", 'SELECT "a;b"; SELECT 2;', ("ok", [('SELECT "a;b";', "SELECT 2;")])),
    ("case 6", "SELECT 'a;b'; SELECT 2;", ("ok", [("SELECT 'a;b';", "SELECT 2;")])),
    ("case 7", "SELECT 1 /* a;b */; SELECT 2;", ("ok", [("SELECT 1 /* a;b */;", "SELECT 2;")])),
    ("case 8", "SELECT 1 -- a;b\n; SELECT 2;", ("ok", [("SELECT 1 -- a;b\n;", "SELECT 2;")])),
    (
        "case 9",
        "IF 1=1 BEGIN SELECT CASE WHEN 1=1 THEN 1 ELSE 0 END; DROP TABLE users; END; SELECT 2;",
        (
            "ok",
            [
                (
                    "IF 1=1 BEGIN SELECT CASE WHEN 1=1 THEN 1 ELSE 0 END; DROP TABLE users; END;",
                    "SELECT 2;",
                )
            ],
        ),
    ),
    (
        "case 10",
        "CREATE PROCEDURE p @MinPrice INT AS BEGIN SELECT N'x;y', @MinPrice; END",
        ("ok", [("CREATE PROCEDURE p @MinPrice INT AS BEGIN SELECT N'x;y', @MinPrice; END",)]),
    ),
    (
        "case 11",
        "BEGIN TRANSACTION; SELECT 1; COMMIT;",
        ("ok", [("BEGIN TRANSACTION;", "SELECT 1;", "COMMIT;")]),
    ),
    ("case 12", "BEGIN SELECT 1; SELECT 2; END;", ("ok", [("BEGIN SELECT 1; SELECT 2; END;",)])),
    (
        "case 13",
        "ALTER TABLE users\nDROP COLUMN legacy_flag;",
        ("ok", [("ALTER TABLE users\nDROP COLUMN legacy_flag;",)]),
    ),
    (
        "case 14",
        "ALTER TABLE users\nDROP CONSTRAINT old_key;",
        ("ok", [("ALTER TABLE users\nDROP CONSTRAINT old_key;",)]),
    ),
    (
        "case 15",
        "ALTER TABLE users\nALTER COLUMN name VARCHAR(50);",
        ("ok", [("ALTER TABLE users\nALTER COLUMN name VARCHAR(50);",)]),
    ),
    (
        "case 16",
        "ALTER TABLE users ADD display_name VARCHAR(50)\nDROP TABLE victims;",
        ("ok", [("ALTER TABLE users ADD display_name VARCHAR(50)", "DROP TABLE victims;")]),
    ),
    ("case 17", "SELECT 1 DROP DROP", ("ok", [("SELECT 1 DROP DROP",)])),
    (
        "case 18",
        "\ufeff SELECT 1;\nGO 0 -- skipped\nSELECT 2;\nGO 2\n",
        ("ok", [("SELECT 1;",), ("SELECT 2;",)]),
    ),
    ("case 19", "SELECT 1 @end", ("ok", [("SELECT 1 @end",)])),
    (
        "case 20",
        "BEGIN SELECT 1; @end SELECT 2; END; SELECT 3;",
        ("ok", [("BEGIN SELECT 1; @end SELECT 2; END;", "SELECT 3;")]),
    ),
    ("case 21", "BEGIN SELECT 1; #end SELECT 2;", ("ok", [("BEGIN SELECT 1; #end SELECT 2;",)])),
    ("case 22", "BEGIN SELECT 1; a@end SELECT 2;", ("ok", [("BEGIN SELECT 1; a@end SELECT 2;",)])),
    ("case 23", "BEGIN SELECT 1; 1END SELECT 2;", ("ok", [("BEGIN SELECT 1; 1END SELECT 2;",)])),
    (
        "case 24",
        "BEGIN SELECT 1; \xe9END SELECT 2;",
        ("ok", [("BEGIN SELECT 1; \xe9END SELECT 2;",)]),
    ),
    (
        "case 25",
        "BEGIN SELECT 1; $action END; SELECT 2;",
        ("ok", [("BEGIN SELECT 1; $action END;", "SELECT 2;")]),
    ),
    ("case 26", "BEGIN TRAN; SELECT 1; COMMIT;", ("ok", [("BEGIN TRAN;", "SELECT 1;", "COMMIT;")])),
    ("case 27", "BEGIN TRANSACTION t; SELECT 1;", ("ok", [("BEGIN TRANSACTION t;", "SELECT 1;")])),
    (
        "case 28",
        "BEGIN DISTRIBUTED TRANSACTION; SELECT 1;",
        ("ok", [("BEGIN DISTRIBUTED TRANSACTION;", "SELECT 1;")]),
    ),
    (
        "case 29",
        "BEGIN CONVERSATION TIMER (@h) TIMEOUT = 1; SELECT 2;",
        ("ok", [("BEGIN CONVERSATION TIMER (@h) TIMEOUT = 1;", "SELECT 2;")]),
    ),
    (
        "case 30",
        "BEGIN DIALOG CONVERSATION @h FROM SERVICE s; SELECT 2;",
        ("ok", [("BEGIN DIALOG CONVERSATION @h FROM SERVICE s;", "SELECT 2;")]),
    ),
    ("case 31", "BEGIN; SELECT 1;", ("ok", [("BEGIN; SELECT 1;",)])),
    (
        "case 32",
        "BEGIN\nSELECT 1;\nEND\nSELECT 2;",
        ("ok", [("BEGIN\nSELECT 1;\nEND\nSELECT 2;",)]),
    ),
    (
        "case 33",
        "BEGIN TRY SELECT 1; END TRY BEGIN CATCH SELECT 2; END CATCH SELECT 3;",
        ("ok", [("BEGIN TRY SELECT 1; END TRY BEGIN CATCH SELECT 2; END CATCH SELECT 3;",)]),
    ),
    (
        "case 34",
        "SELECT CASE WHEN 1=1 THEN 1 END; SELECT 2;",
        ("ok", [("SELECT CASE WHEN 1=1 THEN 1 END;", "SELECT 2;")]),
    ),
    ("case 35", "CASE END END; SELECT 1;", ("ok", [("CASE END END;", "SELECT 1;")])),
    ("case 36", "END; SELECT 1;", ("ok", [("END;", "SELECT 1;")])),
    ("case 37", "END END SELECT 1; SELECT 2;", ("ok", [("END END SELECT 1;", "SELECT 2;")])),
    (
        "case 38",
        "CREATE PROC p AS SELECT 1; SELECT 2;",
        ("ok", [("CREATE PROC p AS SELECT 1; SELECT 2;",)]),
    ),
    (
        "case 39",
        "CREATE PROCEDURE p AS SELECT 1; SELECT 2;",
        ("ok", [("CREATE PROCEDURE p AS SELECT 1; SELECT 2;",)]),
    ),
    (
        "case 40",
        "ALTER PROC p AS SELECT 1; SELECT 2;",
        ("ok", [("ALTER PROC p AS SELECT 1; SELECT 2;",)]),
    ),
    (
        "case 41",
        "ALTER PROCEDURE p AS SELECT 1; SELECT 2",
        ("ok", [("ALTER PROCEDURE p AS SELECT 1; SELECT 2",)]),
    ),
    (
        "case 42",
        "CREATE OR ALTER PROC p AS SELECT 1; SELECT 2;",
        ("ok", [("CREATE OR ALTER PROC p AS SELECT 1; SELECT 2;",)]),
    ),
    (
        "case 43",
        "CREATE OR REPLACE PROC p AS SELECT 1; SELECT 2;",
        ("ok", [("CREATE OR REPLACE PROC p AS SELECT 1; SELECT 2;",)]),
    ),
    (
        "case 44",
        "CREATE OR FOO PROC p AS SELECT 1; SELECT 2;",
        ("ok", [("CREATE OR FOO PROC p AS SELECT 1;", "SELECT 2;")]),
    ),
    (
        "case 45",
        "CREATE TRIGGER tr ON t AFTER INSERT AS SELECT 1; SELECT 2;",
        ("ok", [("CREATE TRIGGER tr ON t AFTER INSERT AS SELECT 1; SELECT 2;",)]),
    ),
    (
        "case 46",
        "ALTER TRIGGER tr ON t AFTER INSERT AS SELECT 1; SELECT 2;",
        ("ok", [("ALTER TRIGGER tr ON t AFTER INSERT AS SELECT 1; SELECT 2;",)]),
    ),
    (
        "case 47",
        "CREATE FUNCTION f() RETURNS INT AS BEGIN RETURN 1; END; SELECT 2;",
        ("ok", [("CREATE FUNCTION f() RETURNS INT AS BEGIN RETURN 1; END; SELECT 2;",)]),
    ),
    (
        "case 48",
        "ALTER FUNCTION f() RETURNS INT AS RETURN 1; SELECT 2;",
        ("ok", [("ALTER FUNCTION f() RETURNS INT AS RETURN 1; SELECT 2;",)]),
    ),
    (
        "case 49",
        "CREATE OR ALTER TRIGGER tr ON t AFTER INSERT AS SELECT 1; SELECT 2;",
        ("ok", [("CREATE OR ALTER TRIGGER tr ON t AFTER INSERT AS SELECT 1; SELECT 2;",)]),
    ),
    (
        "case 50",
        "CREATE OR ALTER FUNCTION f() RETURNS INT AS RETURN 1; SELECT 2;",
        ("ok", [("CREATE OR ALTER FUNCTION f() RETURNS INT AS RETURN 1; SELECT 2;",)]),
    ),
    ("case 51", "CREATE PROC", ("ok", [("CREATE PROC",)])),
    ("case 52", "CREATE OR ALTER", ("ok", [("CREATE OR ALTER",)])),
    ("case 53", "CREATE OR REPLACE", ("ok", [("CREATE OR REPLACE",)])),
    ("case 54", "ALTER OR PROC x; SELECT 2;", ("ok", [("ALTER OR PROC x;", "SELECT 2;")])),
    (
        "case 55",
        "CREATE /* c */ PROC p AS SELECT 1; SELECT 2;",
        ("ok", [("CREATE /* c */ PROC p AS SELECT 1; SELECT 2;",)]),
    ),
    (
        "case 56",
        "CREATE\nPROC p AS SELECT 1; SELECT 2;",
        ("ok", [("CREATE\nPROC p AS SELECT 1; SELECT 2;",)]),
    ),
    (
        "case 57",
        "SELECT 1; CREATE PROC p AS SELECT 2; SELECT 3;",
        ("ok", [("SELECT 1;", "CREATE PROC p AS SELECT 2;", "SELECT 3;")]),
    ),
    (
        "case 58",
        "SELECT 1\nCREATE TABLE t (a INT)\nDROP TABLE u\nTRUNCATE TABLE v",
        ("ok", [("SELECT 1", "CREATE TABLE t (a INT)", "DROP TABLE u", "TRUNCATE TABLE v")]),
    ),
    (
        "case 59",
        "SELECT 1 /* c */ CREATE TABLE t (a INT)",
        ("ok", [("SELECT 1 /* c */ CREATE TABLE t (a INT)",)]),
    ),
    ("case 60", "/* c */ CREATE TABLE t (a INT)", ("ok", [("/* c */ CREATE TABLE t (a INT)",)])),
    (
        "case 61",
        "SELECT 1\n/* c */ CREATE TABLE t (a INT)",
        ("ok", [("SELECT 1\n/* c */ CREATE TABLE t (a INT)",)]),
    ),
    (
        "case 62",
        "CREATE TABLE t (a INT)\nCREATE TABLE u (a INT)",
        ("ok", [("CREATE TABLE t (a INT)", "CREATE TABLE u (a INT)")]),
    ),
    (
        "case 63",
        "SELECT 1\n  \n  CREATE TABLE t (a INT)",
        ("ok", [("SELECT 1", "CREATE TABLE t (a INT)")]),
    ),
    ("case 64", "SELECT 1\n\tDROP TABLE t", ("ok", [("SELECT 1", "DROP TABLE t")])),
    ("case 65", "SELECT 1\n\xa0DROP TABLE t", ("ok", [("SELECT 1", "DROP TABLE t")])),
    ("case 66", "SELECT 1\n\x0cDROP TABLE t", ("ok", [("SELECT 1", "DROP TABLE t")])),
    ("case 67", "SELECT 1\n'x' DROP TABLE t", ("ok", [("SELECT 1\n'x' DROP TABLE t",)])),
    ("case 68", "SELECT 'a\nb'\nDROP TABLE t", ("ok", [("SELECT 'a\nb'", "DROP TABLE t")])),
    ("case 69", "SELECT 'a\nb' DROP TABLE t", ("ok", [("SELECT 'a\nb' DROP TABLE t",)])),
    ("case 70", "/* a\nb */ DROP TABLE t", ("ok", [("/* a\nb */ DROP TABLE t",)])),
    (
        "case 71",
        "SELECT 1\n/* a\nb */ DROP TABLE t",
        ("ok", [("SELECT 1\n/* a\nb */ DROP TABLE t",)]),
    ),
    (
        "case 72",
        "ALTER TABLE t\nALTER COLUMN c INT\nDROP COLUMN d",
        ("ok", [("ALTER TABLE t\nALTER COLUMN c INT\nDROP COLUMN d",)]),
    ),
    (
        "case 73",
        "ALTER TABLE t ADD c INT\nALTER TABLE u ADD d INT",
        ("ok", [("ALTER TABLE t ADD c INT", "ALTER TABLE u ADD d INT")]),
    ),
    (
        "case 74",
        "ALTER TABLE t\nADD CONSTRAINT k PRIMARY KEY (a)",
        ("ok", [("ALTER TABLE t\nADD CONSTRAINT k PRIMARY KEY (a)",)]),
    ),
    (
        "case 75",
        "ALTER INDEX i ON t REBUILD\nDROP INDEX j ON t",
        ("ok", [("ALTER INDEX i ON t REBUILD", "DROP INDEX j ON t")]),
    ),
    (
        "case 76",
        "ALTER TABLE t\nDROP COLUMN c\nDROP CONSTRAINT k",
        ("ok", [("ALTER TABLE t\nDROP COLUMN c\nDROP CONSTRAINT k",)]),
    ),
    (
        "case 77",
        "ALTER /* c */ TABLE t\nDROP COLUMN c",
        ("ok", [("ALTER /* c */ TABLE t\nDROP COLUMN c",)]),
    ),
    ("case 78", "ALTER TABLE t;\nDROP COLUMN c", ("ok", [("ALTER TABLE t;", "DROP COLUMN c")])),
    ("case 79", "alter table t\ndrop column c", ("ok", [("alter table t\ndrop column c",)])),
    ("case 80", "ALTER TABLE t\nDROP", ("ok", [("ALTER TABLE t", "DROP")])),
    ("case 81", "SELECT 1; SELECT 2", ("ok", [("SELECT 1;", "SELECT 2")])),
    ("case 82", "SELECT (1;2)", ("ok", [("SELECT (1;", "2)")])),
    ("case 83", "SELECT 1;;", ("ok", [("SELECT 1;",)])),
    ("case 84", ";", ("ok", [])),
    ("case 85", ";;", ("ok", [])),
    ("case 86", "; ;", ("ok", [])),
    ("case 87", "SELECT 1 ;", ("ok", [("SELECT 1 ;",)])),
    ("case 88", "/* c */;", ("ok", [])),
    ("case 89", "/* c */", ("ok", [])),
    ("case 90", "-- c", ("ok", [])),
    ("case 91", "SELECT 1;\n-- c\n", ("ok", [("SELECT 1;",)])),
    ("case 92", "SELECT 1; /* c */", ("ok", [("SELECT 1;",)])),
    ("case 93", "SELECT 1; -- c\nSELECT 2", ("ok", [("SELECT 1;", "-- c\nSELECT 2")])),
    ("case 94", "x ; y ; z", ("ok", [("x ;", "y ;", "z")])),
    ("case 95", "SELECT 1;SELECT 2;SELECT 3", ("ok", [("SELECT 1;", "SELECT 2;", "SELECT 3")])),
    ("case 96", "\xa0", ("ok", [])),
    ("case 97", "\x0c", ("ok", [])),
    ("case 98", "\x0b", ("ok", [])),
    ("case 99", "  ;  ", ("ok", [])),
    ("case 100", "\x0c;", ("ok", [(";",)])),
    ("case 101", "SELECT 1\nGO\n\x0c\nGO\nSELECT 2", ("ok", [("SELECT 1",), ("SELECT 2",)])),
    ("case 102", "GO\nGO", ("ok", [])),
    ("case 103", "SELECT 1\nGO\nGO\nSELECT 2", ("ok", [("SELECT 1",), ("SELECT 2",)])),
    ("case 104", "SELECT [end]; SELECT 2;", ("ok", [("SELECT [end];", "SELECT 2;")])),
    ("case 105", "BEGIN SELECT [end]; SELECT 2;", ("ok", [("BEGIN SELECT [end]; SELECT 2;",)])),
    (
        "case 106",
        "BEGIN SELECT 'end'; SELECT 2; END; SELECT 3;",
        ("ok", [("BEGIN SELECT 'end'; SELECT 2; END;", "SELECT 3;")]),
    ),
    ("case 107", 'BEGIN SELECT "end"; SELECT 2;', ("ok", [('BEGIN SELECT "end"; SELECT 2;',)])),
    (
        "case 108",
        "BEGIN SELECT 1 /* end */; SELECT 2;",
        ("ok", [("BEGIN SELECT 1 /* end */; SELECT 2;",)]),
    ),
    (
        "case 109",
        "BEGIN SELECT 1 -- end\n; SELECT 2;",
        ("ok", [("BEGIN SELECT 1 -- end\n; SELECT 2;",)]),
    ),
    (
        "case 110",
        "CREATE TABLE t (a INT,\nb INT);\nCREATE TABLE u (a INT);",
        ("ok", [("CREATE TABLE t (a INT,\nb INT);", "CREATE TABLE u (a INT);")]),
    ),
    ("case 111", "SELECT\n1;\nSELECT\n2;", ("ok", [("SELECT\n1;", "SELECT\n2;")])),
    (
        "case 112",
        "SELECT 1\r\nDROP TABLE t\r\nGO\r\nSELECT 2;",
        ("ok", [("SELECT 1", "DROP TABLE t"), ("SELECT 2;",)]),
    ),
    ("case 113", "SELECT 1;\r\nSELECT 2;\r\n", ("ok", [("SELECT 1;", "SELECT 2;")])),
    ("batch start 0", "\xa0 DROP TABLE t", ("ok", [("DROP TABLE t",)])),
    ("batch start 1", "\x0cDROP TABLE t", ("ok", [("DROP TABLE t",)])),
    ("batch start 2", "\x1c DROP t", ("ok", [("\x1c DROP t",)])),
    ("batch start 3", "x\nGO\n\xa0DROP t", ("ok", [("x",), ("DROP t",)])),
    ("batch start 4", "\x85DROP TABLE t", ("ok", [("DROP TABLE t",)])),
    ("batch start 5", "\u2028 CREATE TABLE t (a INT)", ("ok", [("CREATE TABLE t (a INT)",)])),
    ("batch start 6", "\x1dTRUNCATE TABLE t", ("ok", [("\x1dTRUNCATE TABLE t",)])),
    ("batch start 7", "\x0b DROP t", ("ok", [("DROP t",)])),
    (
        "batch start 8",
        "SELECT 1\nGO\n\x0c DROP TABLE t\nGO\n\xa0CREATE TABLE u (a INT)",
        ("ok", [("SELECT 1",), ("DROP TABLE t",), ("CREATE TABLE u (a INT)",)]),
    ),
    ("batch start 9", "\xa0 \xa0DROP TABLE t; SELECT 2", ("ok", [("DROP TABLE t;", "SELECT 2")])),
]


def engine(spec=SQLSERVER_SPEC):
    return LexicalEngine(spec)


def parts(script, spec=SQLSERVER_SPEC):
    """The analysis statements of every executable batch, flattened."""
    return [
        statement
        for record in engine(spec).split(script)
        if record.repeat > 0
        for statement in record.analysis_statements
    ]


def batch_rules(**changes):
    return replace(SQLSERVER_SPEC, batch_script=replace(SQLSERVER_SPEC.batch_script, **changes))


def division(**changes):
    rules = replace(SQLSERVER_SPEC.batch_script.division, **changes)
    return replace(
        SQLSERVER_SPEC, batch_script=replace(SQLSERVER_SPEC.batch_script, division=rules)
    )


@pytest.mark.parametrize("name, script, outcome", CASES, ids=[c[0] for c in CASES])
def test_matches_the_recorded_division(name, script, outcome):
    assert outcome[0] == "ok"
    assert [r.analysis_statements for r in engine().split(script)] == outcome[1]


def test_routine_head_batch_is_one_statement():
    for head in (
        "CREATE PROC",
        "CREATE PROCEDURE",
        "ALTER PROC",
        "ALTER TRIGGER",
        "CREATE FUNCTION",
    ):
        assert len(parts(f"{head} p AS SELECT 1; SELECT 2;")) == 1
    for head in ("CREATE OR ALTER PROC", "CREATE OR REPLACE FUNCTION"):
        assert len(parts(f"{head} p AS SELECT 1; SELECT 2;")) == 1
    assert len(parts("CREATE OR FOO PROC p AS SELECT 1; SELECT 2;")) == 2
    assert len(parts("ALTER OR PROC p; SELECT 2;")) == 2


@pytest.mark.parametrize("word", ["TRAN", "TRANSACTION", "DISTRIBUTED", "CONVERSATION", "DIALOG"])
def test_begin_transaction_is_not_a_block(word):
    assert parts(f"BEGIN {word} x; SELECT 1;") == [f"BEGIN {word} x;", "SELECT 1;"]


def test_case_end_does_not_close_a_block():
    script = "BEGIN SELECT CASE WHEN 1=1 THEN 1 END; SELECT 2; END; SELECT 3;"
    assert parts(script) == ["BEGIN SELECT CASE WHEN 1=1 THEN 1 END; SELECT 2; END;", "SELECT 3;"]


def test_ddl_head_splits_only_at_a_line_start():
    assert parts("SELECT 1\nDROP TABLE t") == ["SELECT 1", "DROP TABLE t"]
    assert parts("DROP TABLE t DROP TABLE u") == ["DROP TABLE t DROP TABLE u"]
    assert parts("SELECT 1 /* c */ CREATE TABLE t (a INT)") == [
        "SELECT 1 /* c */ CREATE TABLE t (a INT)"
    ]
    assert parts("SELECT 'a\nb' DROP TABLE t") == ["SELECT 'a\nb' DROP TABLE t"]
    assert parts("SELECT 'a\nb'\nDROP TABLE t") == ["SELECT 'a\nb'", "DROP TABLE t"]


def test_alter_table_clause_is_not_a_split():
    assert parts("ALTER TABLE t\nDROP COLUMN c;") == ["ALTER TABLE t\nDROP COLUMN c;"]
    assert parts("ALTER TABLE t ADD c INT\nDROP TABLE u;") == [
        "ALTER TABLE t ADD c INT",
        "DROP TABLE u;",
    ]


@pytest.mark.parametrize("word", ["@end", "#end", "a@end", "$action"])
def test_division_words_come_from_code_spans(word):
    script = f"BEGIN SELECT 1; {word} SELECT 2; END; SELECT 3;"
    assert parts(script) == [f"BEGIN SELECT 1; {word} SELECT 2; END;", "SELECT 3;"]


def test_division_keeps_literals_comments_and_brackets_intact():
    assert parts("SELECT 'a;b'; /* ; */ SELECT 2; [x;y]; -- ;\nSELECT 3;") == [
        "SELECT 'a;b';",
        "/* ; */ SELECT 2;",
        "[x;y];",
        "-- ;\nSELECT 3;",
    ]


def test_routine_heads_are_a_spec_field():
    assert len(parts("CREATE PROC p AS SELECT 1; SELECT 2;")) == 1
    assert len(parts("CREATE PROC p AS SELECT 1; SELECT 2;", division(routine_heads=()))) == 2


def test_block_open_is_a_spec_field():
    spec = division(block_open="LOOP")
    assert parts("LOOP SELECT 1; SELECT 2; END; SELECT 3;", spec) == [
        "LOOP SELECT 1; SELECT 2; END;",
        "SELECT 3;",
    ]
    assert parts("BEGIN SELECT 1; SELECT 2; END;", spec) == ["BEGIN SELECT 1;", "SELECT 2;", "END;"]


def test_block_open_exempt_is_a_spec_field():
    assert parts("BEGIN TRAN; SELECT 1; COMMIT;") == ["BEGIN TRAN;", "SELECT 1;", "COMMIT;"]
    assert parts("BEGIN TRAN; SELECT 1; COMMIT;", division(block_open_exempt=frozenset())) == [
        "BEGIN TRAN; SELECT 1; COMMIT;"
    ]


def test_case_word_is_a_spec_field():
    script = "BEGIN SELECT CASE WHEN 1=1 THEN 1 END; SELECT 2; END; SELECT 3;"
    assert len(parts(script)) == 2
    assert len(parts(script, division(case_word="SWITCH"))) == 4


def test_block_close_is_a_spec_field():
    script = "BEGIN SELECT 1; END; SELECT 2;"
    assert parts(script) == ["BEGIN SELECT 1; END;", "SELECT 2;"]
    assert parts(script, division(block_close="FINISH")) == [script]


def test_split_heads_are_a_spec_field():
    assert parts("SELECT 1\nDROP TABLE t") == ["SELECT 1", "DROP TABLE t"]
    assert parts("SELECT 1\nDROP TABLE t", division(split_heads=frozenset({"CREATE"}))) == [
        "SELECT 1\nDROP TABLE t"
    ]


def test_clause_exemptions_are_a_spec_field():
    script = "ALTER TABLE t\nDROP COLUMN c;"
    assert parts(script) == [script]
    assert len(parts(script, division(clause_exemptions=()))) == 2


EQUIVALENCE_CASES = [
    ("\nCREATE\x0c", [("CREATE", 2, 1, False, ("CREATE",))]),
    (
        "\nGO\n\xa0truncate\ndrop\u2028ALTER ; ",
        [("truncate\ndrop\u2028ALTER ;", 3, 1, False, ("truncate", "drop\u2028ALTER ;"))],
    ),
    (
        "\x85PROCEDURE\n\xa0REPLACE\x85DROP",
        [("PROCEDURE\n\xa0REPLACE\x85DROP", 1, 1, False, ("PROCEDURE\n\xa0REPLACE\x85DROP",))],
    ),
    (
        "\u2028BEGIN\n-- c\ntrigger\xa0TRUNCATE\x0b ",
        [("BEGIN\n-- c\ntrigger\xa0TRUNCATE", 1, 1, False, ("BEGIN\n-- c\ntrigger\xa0TRUNCATE",))],
    ),
    (
        "\n\xa0CREATE; ALTER\n  begin\n  or;;",
        [("CREATE; ALTER\n  begin\n  or;;", 2, 1, False, ("ALTER\n  begin\n  or;;",))],
    ),
    (
        "\x0cCREATE\n\nPROC\n\x1c CREATE\xa0REPLACE\nGO\n\xa0",
        [
            (
                "CREATE\n\nPROC\n\x1c CREATE\xa0REPLACE",
                1,
                1,
                True,
                ("CREATE\n\nPROC\n\x1c CREATE\xa0REPLACE",),
            ),
        ],
    ),
    (
        "\x85CREATE\n  TABLE ; TRUNCATE\x85PROC\n",
        [
            (
                "CREATE\n  TABLE ; TRUNCATE\x85PROC",
                1,
                1,
                False,
                ("CREATE\n  TABLE ;", "TRUNCATE\x85PROC"),
            )
        ],
    ),
    (
        " ; ALTER\u2028create\nGO\nproc /* c */ procedure\x85",
        [
            ("; ALTER\u2028create", 1, 1, True, ("ALTER\u2028create",)),
            ("proc /* c */ procedure", 3, 1, False, ("proc /* c */ procedure",)),
        ],
    ),
    (
        "\n\xa0ALTEROR\nfunction\x0ctrigger\n",
        [("ALTEROR\nfunction\x0ctrigger", 2, 1, False, ("ALTEROR\nfunction\x0ctrigger",))],
    ),
    (
        "\u2028ALTER\nTRIGGER;\nend\nFUNCTION\xa0",
        [("ALTER\nTRIGGER;\nend\nFUNCTION", 1, 1, False, ("ALTER\nTRIGGER;\nend\nFUNCTION",))],
    ),
    (
        "\x0b ALTER\n\x1c CASE\nGO\nALTER\n-- c\nTABLE\nGO\n\xa0",
        [
            ("ALTER\n\x1c CASE", 1, 1, True, ("ALTER\n\x1c CASE",)),
            ("ALTER\n-- c\nTABLE", 4, 1, True, ("ALTER\n-- c\nTABLE",)),
        ],
    ),
    (
        "\x0cDROP\nGO\nTRUNCATE\n-- c\norBEGIN\nGO\n\xa0",
        [
            ("DROP", 1, 1, True, ("DROP",)),
            ("TRUNCATE\n-- c\norBEGIN", 3, 1, True, ("TRUNCATE\n-- c\norBEGIN",)),
        ],
    ),
    (
        "\u2028drop\x0cprocedure\n  procedure /* c */ END\xa0",
        [
            (
                "drop\x0cprocedure\n  procedure /* c */ END",
                1,
                1,
                False,
                ("drop\x0cprocedure\n  procedure /* c */ END",),
            )
        ],
    ),
    (
        "\x0cDROP\n\xa0begin\n\x1c TABLE case\n\n",
        [("DROP\n\xa0begin\n\x1c TABLE case", 1, 1, False, ("DROP\n\xa0begin\n\x1c TABLE case",))],
    ),
    (
        "\xa0truncate\nDROP\x0cCREATE;create;;",
        [
            (
                "truncate\nDROP\x0cCREATE;create;;",
                1,
                1,
                False,
                ("truncate", "DROP\x0cCREATE;", "create;"),
            )
        ],
    ),
    (
        "\n\xa0truncate\nGO\n\xa0PROC\n\xa0TRUNCATE; ALTER ; ",
        [
            ("truncate", 2, 1, True, ("",)),
            ("PROC\n\xa0TRUNCATE; ALTER ;", 4, 1, False, ("PROC", "ALTER ;")),
        ],
    ),
    (
        "\nTRUNCATETABLE\xa0PROC DROP; ",
        [("TRUNCATETABLE\xa0PROC DROP;", 2, 1, False, ("TRUNCATETABLE\xa0PROC DROP;",))],
    ),
    (
        ";\nOR CREATE /* c */ FUNCTION\nGO\n\xa0TRUNCATE",
        [
            (";\nOR CREATE /* c */ FUNCTION", 1, 1, True, ("OR CREATE /* c */ FUNCTION",)),
            ("TRUNCATE", 4, 1, False, ("TRUNCATE",)),
        ],
    ),
    (
        "\n\nOR\x85OR\n\xa0END\nOR\n\xa0",
        [("OR\x85OR\n\xa0END\nOR", 3, 1, False, ("OR\x85OR\n\xa0END\nOR",))],
    ),
    (
        "\x85OR\u2028function\x0cALTER ; REPLACE\n",
        [
            (
                "OR\u2028function\x0cALTER ; REPLACE",
                1,
                1,
                False,
                ("OR\u2028function\x0cALTER ;", "REPLACE"),
            )
        ],
    ),
    (
        "\x85OR ; CASE\nOR; PROC\n",
        [("OR ; CASE\nOR; PROC", 1, 1, False, ("OR ;", "CASE\nOR;", "PROC"))],
    ),
    (
        "\nGO\nreplace truncate\nGO\n\xa0PROCEDUREPROCEDURE\n\xa0",
        [
            ("replace truncate", 3, 1, True, ("replace truncate",)),
            ("PROCEDUREPROCEDURE", 5, 1, False, ("PROCEDUREPROCEDURE",)),
        ],
    ),
    (
        "\n\nREPLACE\xa0PROCEDURE\nTABLE\xa0TRIGGER;",
        [
            (
                "REPLACE\xa0PROCEDURE\nTABLE\xa0TRIGGER;",
                3,
                1,
                False,
                ("REPLACE\xa0PROCEDURE\nTABLE\xa0TRIGGER;",),
            )
        ],
    ),
    (
        "\nREPLACE; BEGIN\n\nCASE;\nFUNCTION ",
        [
            (
                "REPLACE; BEGIN\n\nCASE;\nFUNCTION",
                2,
                1,
                False,
                ("REPLACE;", "BEGIN\n\nCASE;\nFUNCTION"),
            )
        ],
    ),
    (
        "\n\x1c PROC; DROP;DROP\n\x1c table ",
        [
            (
                "\x1c PROC; DROP;DROP\n\x1c table",
                2,
                1,
                False,
                ("\x1c PROC;", "DROP;", "DROP\n\x1c table"),
            )
        ],
    ),
    (
        "\xa0proc\nGO\n\xa0PROC\x0b replace\nBEGIN; ",
        [
            ("proc", 1, 1, True, ("proc",)),
            ("PROC\x0b replace\nBEGIN;", 3, 1, False, ("PROC\x0b replace\nBEGIN;",)),
        ],
    ),
    (
        "\x0cproc\nTABLE;TRIGGER ; END ",
        [("proc\nTABLE;TRIGGER ; END", 1, 1, False, ("proc\nTABLE;", "TRIGGER ;", "END"))],
    ),
    (
        "\nGO\nPROCEDURE\n  CREATE\xa0BEGIN ; CASE;",
        [
            (
                "PROCEDURE\n  CREATE\xa0BEGIN ; CASE;",
                3,
                1,
                False,
                ("PROCEDURE", "CREATE\xa0BEGIN ; CASE;"),
            )
        ],
    ),
    (
        "\n\nPROCEDURE\xa0REPLACE\x0cALTER\ncreate;\n",
        [
            (
                "PROCEDURE\xa0REPLACE\x0cALTER\ncreate;",
                3,
                1,
                False,
                ("PROCEDURE\xa0REPLACE\x0cALTER", "create;"),
            )
        ],
    ),
    (
        "procedure\xa0FUNCTION ; OR\x0b ALTER",
        [
            (
                "procedure\xa0FUNCTION ; OR\x0b ALTER",
                1,
                1,
                False,
                ("procedure\xa0FUNCTION ;", "OR\x0b ALTER"),
            )
        ],
    ),
    (
        "\n  procedure\n  CASE\x85PROCEDURE; DROP\nGO 2\n",
        [
            (
                "procedure\n  CASE\x85PROCEDURE; DROP",
                2,
                2,
                True,
                ("procedure\n  CASE\x85PROCEDURE;", "DROP"),
            )
        ],
    ),
    (
        " /* c */ TRIGGER\x85TRUNCATE\x85TABLE /* c */ TRUNCATE\n",
        [
            (
                "/* c */ TRIGGER\x85TRUNCATE\x85TABLE /* c */ TRUNCATE",
                1,
                1,
                False,
                ("/* c */ TRIGGER\x85TRUNCATE\x85TABLE /* c */ TRUNCATE",),
            )
        ],
    ),
    (
        "\nTRIGGER\nprocedure;CASE OR;;",
        [("TRIGGER\nprocedure;CASE OR;;", 2, 1, False, ("TRIGGER\nprocedure;", "CASE OR;"))],
    ),
    (
        ";TRIGGER\nEND /* c */ DROP REPLACE\n\n",
        [
            (
                ";TRIGGER\nEND /* c */ DROP REPLACE",
                1,
                1,
                False,
                ("TRIGGER\nEND /* c */ DROP REPLACE",),
            )
        ],
    ),
    (
        ";FUNCTION DROP /* c */ REPLACEPROC;\n",
        [
            (
                ";FUNCTION DROP /* c */ REPLACEPROC;",
                1,
                1,
                False,
                ("FUNCTION DROP /* c */ REPLACEPROC;",),
            )
        ],
    ),
    (
        "FUNCTION\nPROC\x85trigger\n  PROCEDURE\xa0",
        [
            (
                "FUNCTION\nPROC\x85trigger\n  PROCEDURE",
                1,
                1,
                False,
                ("FUNCTION\nPROC\x85trigger\n  PROCEDURE",),
            )
        ],
    ),
    (
        "\u2028FUNCTION\u2028TABLE\nGO\nBEGIN; TRIGGER ; ",
        [
            ("FUNCTION\u2028TABLE", 1, 1, True, ("FUNCTION\u2028TABLE",)),
            ("BEGIN; TRIGGER ;", 3, 1, False, ("BEGIN; TRIGGER ;",)),
        ],
    ),
    (
        "\x0b table\x0b ALTER\x0cCREATE /* c */ FUNCTION\n  ",
        [
            (
                "table\x0b ALTER\x0cCREATE /* c */ FUNCTION",
                1,
                1,
                False,
                ("table\x0b ALTER\x0cCREATE /* c */ FUNCTION",),
            )
        ],
    ),
    (
        " TABLE ; replace\n-- c\nTRUNCATE\n-- c\nTABLE\n",
        [
            (
                "TABLE ; replace\n-- c\nTRUNCATE\n-- c\nTABLE",
                1,
                1,
                False,
                ("TABLE ;", "replace\n-- c", "TRUNCATE\n-- c\nTABLE"),
            )
        ],
    ),
    (
        "\n-- c\nTABLE\n\nFUNCTIONPROC\n\nBEGIN ",
        [
            (
                "-- c\nTABLE\n\nFUNCTIONPROC\n\nBEGIN",
                2,
                1,
                False,
                ("-- c\nTABLE\n\nFUNCTIONPROC\n\nBEGIN",),
            )
        ],
    ),
    (
        "\nTABLE\nCASE\nFUNCTION\u2028END\nGO\n\xa0",
        [
            ("TABLE\nCASE\nFUNCTION\u2028END", 2, 1, True, ("TABLE\nCASE\nFUNCTION\u2028END",)),
        ],
    ),
    (
        "\n-- c\nBEGIN\x85TRUNCATE ; END;\nCASE\x0b ",
        [
            (
                "-- c\nBEGIN\x85TRUNCATE ; END;\nCASE",
                2,
                1,
                False,
                ("-- c\nBEGIN\x85TRUNCATE ; END;", "CASE"),
            )
        ],
    ),
    (
        ";\nBEGIN;TRIGGER\x0b DROP\n\x1c CREATE\nGO\n",
        [
            (
                ";\nBEGIN;TRIGGER\x0b DROP\n\x1c CREATE",
                1,
                1,
                True,
                ("BEGIN;TRIGGER\x0b DROP\n\x1c CREATE",),
            )
        ],
    ),
    (
        " /* c */ BEGIN;\nEND /* c */ REPLACE ; ALTER\n\n",
        [
            (
                "/* c */ BEGIN;\nEND /* c */ REPLACE ; ALTER",
                1,
                1,
                False,
                ("/* c */ BEGIN;\nEND /* c */ REPLACE ;", "ALTER"),
            )
        ],
    ),
    (
        "\nend\x85DROP;TRIGGER\nGO\n\xa0drop\x0c",
        [
            ("end\x85DROP;TRIGGER", 2, 1, True, ("end\x85DROP;", "TRIGGER")),
            ("drop", 4, 1, False, ("drop",)),
        ],
    ),
    (
        " /* c */ END\x0cPROC\n\nBEGINTRUNCATE;\n",
        [
            (
                "/* c */ END\x0cPROC\n\nBEGINTRUNCATE;",
                1,
                1,
                False,
                ("/* c */ END\x0cPROC\n\nBEGINTRUNCATE;",),
            )
        ],
    ),
    (
        "\n\xa0END;\nBEGIN\ncreate\nGO\nOR\n  ",
        [
            ("END;\nBEGIN\ncreate", 2, 1, True, ("END;", "BEGIN\ncreate")),
            ("OR", 6, 1, False, ("OR",)),
        ],
    ),
    (
        ";\nCASE /* c */ ALTER; TRUNCATE\xa0REPLACE\n\x1c ",
        [
            (
                ";\nCASE /* c */ ALTER; TRUNCATE\xa0REPLACE\n\x1c",
                1,
                1,
                False,
                ("CASE /* c */ ALTER;", "TRUNCATE\xa0REPLACE\n\x1c"),
            )
        ],
    ),
    (
        "\n\xa0case\x0b REPLACE; PROC ; PROC",
        [("case\x0b REPLACE; PROC ; PROC", 2, 1, False, ("case\x0b REPLACE;", "PROC ;", "PROC"))],
    ),
    (
        "\n  case\x0cFUNCTION FUNCTION PROCEDURE\n\x1c ",
        [
            (
                "case\x0cFUNCTION FUNCTION PROCEDURE\n\x1c",
                2,
                1,
                False,
                ("case\x0cFUNCTION FUNCTION PROCEDURE\n\x1c",),
            )
        ],
    ),
    (
        " drop; PROC ; TABLE;\nCREATE ; ALTER\x85CASE;\nTRIGGER\x85alter\x85REPLACE function ",
        [
            (
                "drop; PROC ; TABLE;\nCREATE ; ALTER\x85CASE;\nTRIGGER\x85alter\x85REPLACE function",
                1,
                1,
                False,
                (
                    "drop;",
                    "PROC ;",
                    "TABLE;",
                    "CREATE ;",
                    "ALTER\x85CASE;",
                    "TRIGGER\x85alter\x85REPLACE function",
                ),
            )
        ],
    ),
    (
        "\n"
        "CASE\n"
        "GO\n"
        "\xa0DROP\n"
        "OR PROC\u2028"
        "DROP\x0b"
        " TRIGGER\n"
        "\n"
        "ALTER\xa0FUNCTION;\n"
        "OR;\n"
        "TRIGGER\n"
        "-- c\n"
        "CASE\n"
        "\n"
        "TABLE\n"
        "-- c\n"
        "DROP ",
        [
            ("CASE", 2, 1, True, ("CASE",)),
            (
                "DROP\n"
                "OR PROC\u2028"
                "DROP\x0b"
                " TRIGGER\n"
                "\n"
                "ALTER\xa0FUNCTION;\n"
                "OR;\n"
                "TRIGGER\n"
                "-- c\n"
                "CASE\n"
                "\n"
                "TABLE\n"
                "-- c\n"
                "DROP",
                4,
                1,
                False,
                (
                    "DROP\nOR PROC\u2028DROP\x0b TRIGGER",
                    "ALTER\xa0FUNCTION;",
                    "OR;",
                    "TRIGGER\n-- c\nCASE\n\nTABLE\n-- c",
                    "DROP",
                ),
            ),
        ],
    ),
    (
        "\n\xa0TRIGGER\x0b PROC\n\x1c DROP\n\nEND\n  REPLACE\x85DROP ",
        [
            (
                "TRIGGER\x0b PROC\n\x1c DROP\n\nEND\n  REPLACE\x85DROP",
                2,
                1,
                False,
                ("TRIGGER\x0b PROC\n\x1c", "DROP\n\nEND\n  REPLACE\x85DROP"),
            )
        ],
    ),
    (
        "\n-- c\nOR\x0b procedure\n-- c\nBEGIN\x0b TABLE\xa0ALTER\u2028CREATE ",
        [
            (
                "-- c\nOR\x0b procedure\n-- c\nBEGIN\x0b TABLE\xa0ALTER\u2028CREATE",
                2,
                1,
                False,
                ("-- c\nOR\x0b procedure\n-- c\nBEGIN\x0b TABLE\xa0ALTER\u2028CREATE",),
            )
        ],
    ),
    (
        "\n\xa0END\xa0OR /* c */ drop ; begin /* c */ TRUNCATE\n  PROC\nGO\nproc\nCASE\n",
        [
            (
                "END\xa0OR /* c */ drop ; begin /* c */ TRUNCATE\n  PROC",
                2,
                1,
                True,
                ("END\xa0OR /* c */ drop ;", "begin /* c */ TRUNCATE\n  PROC"),
            ),
            ("proc\nCASE", 5, 1, False, ("proc\nCASE",)),
        ],
    ),
    (
        "\n-- c\nTABLE ; TRUNCATE\u2028CREATE\nPROCEDURE\x0ccase\nGO\n\xa0FUNCTION DROP\x0b OR\nGO\n",
        [
            (
                "-- c\nTABLE ; TRUNCATE\u2028CREATE\nPROCEDURE\x0ccase",
                2,
                1,
                True,
                ("-- c\nTABLE ;", "TRUNCATE\u2028CREATE\nPROCEDURE\x0ccase"),
            ),
            ("FUNCTION DROP\x0b OR", 6, 1, True, ("FUNCTION DROP\x0b OR",)),
        ],
    ),
    (
        ";PROC\u2028"
        "PROCALTER\n"
        "\x1c"
        " PROCEDURE\n"
        "  TABLE proc\u2028"
        "CREATE\n"
        "GO\n"
        "\xa0TRUNCATE\n"
        "  ALTER\n"
        "\xa0TRUNCATE\n"
        "\xa0procedure\xa0",
        [
            (
                ";PROC\u2028PROCALTER\n\x1c PROCEDURE\n  TABLE proc\u2028CREATE",
                1,
                1,
                True,
                ("PROC\u2028PROCALTER\n\x1c PROCEDURE\n  TABLE proc\u2028CREATE",),
            ),
            (
                "TRUNCATE\n  ALTER\n\xa0TRUNCATE\n\xa0procedure",
                5,
                1,
                False,
                ("TRUNCATE", "ALTER", "TRUNCATE\n\xa0procedure"),
            ),
        ],
    ),
    (
        ";PROCEDURE; or\x0c"
        "ALTER\n"
        "\x1c"
        " drop\x0c"
        "ALTER\n"
        "GO\n"
        "\xa0begin /* c */ REPLACE;BEGIN;\n"
        "OR\x0c"
        "PROCEDURE;\n"
        "CASE; begin\n"
        "GO\n",
        [
            (
                ";PROCEDURE; or\x0cALTER\n\x1c drop\x0cALTER",
                1,
                1,
                True,
                ("PROCEDURE;", "or\x0cALTER\n\x1c", "drop\x0cALTER"),
            ),
            (
                "begin /* c */ REPLACE;BEGIN;\nOR\x0cPROCEDURE;\nCASE; begin",
                4,
                1,
                True,
                ("begin /* c */ REPLACE;BEGIN;\nOR\x0cPROCEDURE;\nCASE; begin",),
            ),
        ],
    ),
    (
        " /* c */ TRUNCATE; TRIGGER\n  PROCEDURE\n  replace\n  BEGIN\nCREATE; CREATE\n\xa0END\u2028",
        [
            (
                "/* c */ TRUNCATE; TRIGGER\n  PROCEDURE\n  replace\n  BEGIN\nCREATE; CREATE\n\xa0END",
                1,
                1,
                False,
                (
                    "/* c */ TRUNCATE;",
                    "TRIGGER\n  PROCEDURE\n  replace\n  BEGIN\nCREATE; CREATE\n\xa0END",
                ),
            )
        ],
    ),
    (
        " procedure\ntable; REPLACE;END\nGO\n\xa0TABLE;;",
        [
            ("procedure\ntable; REPLACE;END", 1, 1, True, ("procedure\ntable;", "REPLACE;", "END")),
            ("TABLE;;", 4, 1, False, ("TABLE;",)),
        ],
    ),
    (
        "BEGIN SELECT 1; 1END SELECT 2;",
        [("BEGIN SELECT 1; 1END SELECT 2;", 1, 1, False, ("BEGIN SELECT 1; 1END SELECT 2;",))],
    ),
    (
        "BEGIN SELECT 1; \xe9END SELECT 2;",
        [
            (
                "BEGIN SELECT 1; \xe9END SELECT 2;",
                1,
                1,
                False,
                ("BEGIN SELECT 1; \xe9END SELECT 2;",),
            )
        ],
    ),
]


@pytest.mark.parametrize(
    "script, expected", EQUIVALENCE_CASES, ids=[f"case-{i}" for i in range(len(EQUIVALENCE_CASES))]
)
def test_division_matches_the_values_recorded_from_the_previous_heuristic(script, expected):
    found = [
        (r.text, r.line, r.repeat, r.terminator == "GO", r.analysis_statements)
        for r in engine().split(script)
    ]
    assert found == expected


@pytest.mark.parametrize("tail", ["\xa0", "\x0c ", "​"])
def test_a_batch_whose_constituents_are_all_empty_is_no_statement(tail):
    engine = LexicalEngine(SQLSERVER_SPEC)
    assert engine.split(f";{tail}") == []
    kept = engine.split(f"SELECT 1\nGO\n;{tail}\nGO\nSELECT 2")
    assert [r.text for r in kept] == ["SELECT 1", "SELECT 2"]
