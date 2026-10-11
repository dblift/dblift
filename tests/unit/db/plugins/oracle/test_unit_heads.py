"""A PL/SQL unit is decided by its first tokens (docs/sql-parsing/oracle.md §5)."""

import pytest

from dblift.core.exceptions import UnsafeStatementSplitError
from dblift.core.migration.sql.sql_analyzer import SqlAnalyzer
from dblift.core.sql_parser.tokens import TokenType
from dblift.db.plugins.oracle.parser._unit_heads import head_decided
from dblift.db.plugins.oracle.parser.oracle_tokenizer import OracleTokenizer


def _head(sql):
    return [t for t in OracleTokenizer(sql).tokenize() if t.type != TokenType.EOF][:8]


UNIT_HEADS = [
    "DECLARE x NUMBER; BEGIN NULL; END;",
    "begin null; end;",
    "<<lbl>> BEGIN NULL; END;",
    "<<lbl>>\nDECLARE x NUMBER; BEGIN NULL; END;",
    "CREATE FUNCTION f RETURN NUMBER AS BEGIN RETURN 1; END;",
    "CREATE OR REPLACE PROCEDURE p AS BEGIN NULL; END;",
    "CREATE OR REPLACE EDITIONABLE PACKAGE pk AS END pk;",
    "CREATE OR REPLACE NONEDITIONABLE PACKAGE BODY pk AS END pk;",
    "CREATE TYPE t AS OBJECT (id NUMBER);",
    "CREATE OR REPLACE TYPE BODY t AS END;",
    "CREATE OR REPLACE TRIGGER tr BEFORE INSERT ON t BEGIN NULL; END;",
    "CREATE OR REPLACE LIBRARY lib AS 'x.so';",
    "CREATE OR REPLACE AND COMPILE JAVA SOURCE NAMED h AS class H {}",
    "CREATE OR REPLACE AND RESOLVE NOFORCE JAVA SOURCE NAMED h AS class H {}",
    "CREATE JAVA CLASS USING BFILE (d, 'f.class')",
    "CREATE OR REPLACE NOFORCE JAVA RESOURCE NAMED r USING BFILE (d, 'f')",
    "CREATE OR REPLACE IF NOT EXISTS MLE MODULE m LANGUAGE JAVASCRIPT AS x",
    "CREATE MLE MODULE m LANGUAGE JAVASCRIPT AS x",
]

NON_HEADS = [
    "CREATE TABLE t (type NUMBER)",
    "CREATE VIEW v AS SELECT begin FROM t",
    "SELECT begin FROM t",
    "SELECT declare FROM t",
    "ALTER PACKAGE p COMPILE",
    "CREATE INDEX i ON t (c)",
    "DROP PROCEDURE p",
    "CREATE OR REPLACE VIEW v AS SELECT 1 FROM dual",
    "INSERT INTO t (begin) VALUES (1)",
    "<<lbl>> SELECT 1 FROM dual",
    "GRANT EXECUTE ON p TO u",
]


@pytest.mark.parametrize("sql", UNIT_HEADS)
def test_unit_heads(sql):
    assert head_decided(_head(sql)) is True


@pytest.mark.parametrize("sql", NON_HEADS)
def test_non_heads(sql):
    assert head_decided(_head(sql)) is False


def test_head_decided_is_undecided_on_a_short_prefix():
    assert head_decided(_head("CREATE OR REPLACE")) is None
    assert head_decided(_head("CREATE OR REPLACE PACKAGE")) is True
    assert head_decided(_head("CREATE TABLE")) is False


def _split(script):
    return SqlAnalyzer("oracle").split_statements(script)


def test_open_for_inside_a_block_is_one_unit_then_sql():  # row 4
    script = (
        "BEGIN\n  OPEN c FOR SELECT 1 FROM dual;\n  NULL;\nEND;\n/\nCREATE TABLE t (id NUMBER);\n"
    )
    assert _split(script) == [
        "BEGIN\n  OPEN c FOR SELECT 1 FROM dual;\n  NULL;\nEND;",
        "CREATE TABLE t (id NUMBER);",
    ]


def test_keyword_named_columns_are_sql_statements():  # row 8
    script = "CREATE TABLE t (type NUMBER, begin NUMBER);\nSELECT begin FROM t;\n"
    assert _split(script) == [
        "CREATE TABLE t (type NUMBER, begin NUMBER);",
        "SELECT begin FROM t;",
    ]


def test_unit_without_slash_is_refused():  # row 20
    with pytest.raises(UnsafeStatementSplitError, match="starting at line 1") as exc:
        _split("BEGIN\n  NULL;\nEND;\nCREATE TABLE t (id NUMBER);\n")
    assert "not terminated by a '/' line" in str(exc.value)


def test_java_source_body_is_one_unit():  # row 24
    script = (
        'CREATE OR REPLACE AND COMPILE JAVA SOURCE NAMED "H" AS\n'
        "public class H { int f() { return 1; } }\n/\n"
    )
    assert _split(script) == [
        'CREATE OR REPLACE AND COMPILE JAVA SOURCE NAMED "H" AS\n'
        "public class H { int f() { return 1; } }"
    ]


def test_comment_inside_the_head_does_not_hide_it():
    assert _split("CREATE /* x */ OR REPLACE\n  PROCEDURE p AS BEGIN NULL; END;\n/\n") == [
        "CREATE /* x */ OR REPLACE\n  PROCEDURE p AS BEGIN NULL; END;"
    ]


def test_labelled_block_is_one_unit():
    assert _split("<<lbl>>\nBEGIN NULL; END;\n/\n") == ["<<lbl>>\nBEGIN NULL; END;"]


def test_package_body_with_nested_blocks_is_one_unit():
    script = (
        "CREATE OR REPLACE PACKAGE BODY pk AS\n"
        "  PROCEDURE a IS BEGIN NULL; END a;\n"
        "BEGIN\n  NULL;\nEND pk;\n/\nSELECT 1 FROM dual;\n"
    )
    out = _split(script)
    assert len(out) == 2
    assert out[0].startswith("CREATE OR REPLACE PACKAGE BODY pk") and out[0].endswith("END pk;")


def test_type_with_semicolon_inside_is_one_unit():  # row 6
    out = _split("CREATE TYPE t AS OBJECT (id NUMBER);\n/\n")
    assert out == ["CREATE TYPE t AS OBJECT (id NUMBER);"]
