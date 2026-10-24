"""The Oracle splitter returns Statement records; the string form stays what execution got."""

from dblift.core.sql_parser.lexical_engine import LexicalEngine
from dblift.core.sql_parser.statement import Statement
from dblift.db.plugins.oracle.parser.lexical_spec import ORACLE_SPEC

UNIT_THEN_TABLE = (
    "CREATE OR REPLACE PROCEDURE p AS BEGIN NULL; END;\n/\nCREATE TABLE t (id NUMBER);\n"
)


def _split(script):
    return LexicalEngine(ORACLE_SPEC).split(script)


def _strings(script):
    return LexicalEngine(ORACLE_SPEC).split_statements(script)


def test_sql_statement_record():
    assert _split("CREATE TABLE a (x NUMBER);\n") == [
        Statement(text="CREATE TABLE a (x NUMBER)", line=1, terminator=";")
    ]


def test_unit_record_ends_at_slash_and_keeps_its_semicolons():
    assert _split(UNIT_THEN_TABLE) == [
        Statement(text="CREATE OR REPLACE PROCEDURE p AS BEGIN NULL; END;", line=1, terminator="/"),
        Statement(text="CREATE TABLE t (id NUMBER)", line=3, terminator=";"),
    ]


def test_projection_is_what_execution_received_before():
    assert _strings(UNIT_THEN_TABLE) == [
        "CREATE OR REPLACE PROCEDURE p AS BEGIN NULL; END;",
        "CREATE TABLE t (id NUMBER);",
    ]


def test_eof_ended_sql_statement_has_no_terminator():
    assert _split("SELECT 1 FROM dual") == [
        Statement(text="SELECT 1 FROM dual", line=1, terminator=None)
    ]


def test_sql_statement_ended_by_slash_alone():
    s = "SELECT 1 FROM dual\n/\n"
    assert _split(s) == [Statement(text="SELECT 1 FROM dual", line=1, terminator="/")]
    assert _strings(s) == ["SELECT 1 FROM dual"]


def test_source_offsets_cover_slash_line_and_substituted_execution_text():
    script = (
        "DEFINE table_name = widgets\n"
        "CREATE OR REPLACE PROCEDURE p AS BEGIN NULL; END;\n/\n"
        "CREATE TABLE &table_name (id NUMBER);\n"
    )
    records = _split(script)

    assert [script[r.source_start : r.source_end] for r in records] == [
        "DEFINE table_name = widgets\n",
        "CREATE OR REPLACE PROCEDURE p AS BEGIN NULL; END;\n/\n",
        "CREATE TABLE &table_name (id NUMBER);",
    ]
    assert records[2].text == "CREATE TABLE widgets (id NUMBER)"


def test_source_offsets_use_original_crlf_positions():
    script = "CREATE PROCEDURE p AS BEGIN NULL; END;\r\n/\r\nSELECT 1 FROM dual;"
    records = _split(script)

    assert [script[r.source_start : r.source_end] for r in records] == [
        "CREATE PROCEDURE p AS BEGIN NULL; END;\r\n/\r\n",
        "SELECT 1 FROM dual;",
    ]
