"""How a SQL Server batch is divided into the statements analysis reads.

Expected values were recorded from the heuristic this engine replaces (the analysis
statements of every batch record, or the refusal).
"""

import random
from dataclasses import replace

import pytest

from dblift.core.sql_parser.lexical_engine import LexicalEngine
from dblift.db.plugins.sqlserver.parser._batches import scan_batches
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
    ("case 96", "\xa0", ("ok", [("",)])),
    ("case 97", "\x0c", ("ok", [("",)])),
    ("case 98", "\x0b", ("ok", [("",)])),
    ("case 99", "  ;  ", ("ok", [])),
    ("case 100", "\x0c;", ("ok", [(";",)])),
    ("case 101", "SELECT 1\nGO\n\x0c\nGO\nSELECT 2", ("ok", [("SELECT 1",), ("",), ("SELECT 2",)])),
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


@pytest.mark.parametrize("word", ["1END", "\u00e9END"])
def test_division_words_keep_the_old_reading_of_numbers_and_letters(word):
    # recorded from the previous heuristic: the word starts inside a number or after a non-ASCII letter
    script = f"BEGIN SELECT 1; {word} SELECT 2;"
    assert parts(script) == [x for b in scan_batches(script) for x in b.analysis_statements]


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


WORDS = (
    "CREATE ALTER DROP TRUNCATE OR REPLACE PROC PROCEDURE TRIGGER FUNCTION TABLE BEGIN END CASE"
).split()
GLUE = [
    "",
    " ",
    " ",
    "\n",
    "\n",
    ";",
    "; ",
    ";\n",
    " /* c */ ",
    "\n-- c\n",
    "\n\n",
    "\n  ",
    "\nGO\n",
    " ; ",
]


def _layout(rng, words):
    out = []
    for word in words:
        out.append(rng.choice(GLUE))
        out.append(word if rng.random() < 0.8 else word.lower())
    out.append(rng.choice(GLUE + ["\nGO 2\n", ";;"]))
    return "".join(out)


def _same_as_before(script):
    old = [
        (b.text, b.line, b.repeat, b.terminated, b.analysis_statements)
        for b in scan_batches(script)
    ]
    new = [
        (r.text, r.line, r.repeat, r.terminator == "GO", r.analysis_statements)
        for r in engine().split(script)
    ]
    return old == new


def _short_sequences():
    for length in range(1, 5):
        yield from _product(length)


def _product(length):
    if length == 0:
        yield []
        return
    for rest in _product(length - 1):
        for word in WORDS:
            yield [*rest, word]


SHORT = list(_short_sequences())
CHUNKS = 8


@pytest.mark.parametrize("chunk", range(CHUNKS))
def test_division_rules_match_the_previous_heuristic_on_short_sequences(chunk):
    rng = random.Random(chunk)
    for words in SHORT[chunk::CHUNKS]:
        script = _layout(rng, words)
        assert _same_as_before(script), script


@pytest.mark.parametrize("chunk", range(CHUNKS))
def test_division_rules_match_the_previous_heuristic_on_long_sequences(chunk):
    rng = random.Random(1000 + chunk)
    for _ in range(19000):
        words = [rng.choice(WORDS) for _ in range(rng.randrange(5, 14))]
        script = _layout(rng, words)
        assert _same_as_before(script), script
