"""The Oracle splitter returns Statement records; the string form stays what execution got."""

from dblift.core.sql_parser.parser_context import ParserContext
from dblift.core.sql_parser.statement import Statement
from dblift.db.plugins.oracle.parser.oracle_statement_parser import OracleStatementParser
from dblift.db.plugins.oracle.parser.oracle_tokenizer import OracleTokenizer

UNIT_THEN_TABLE = (
    "CREATE OR REPLACE PROCEDURE p AS BEGIN NULL; END;\n/\nCREATE TABLE t (id NUMBER);\n"
)


def _parser(script):
    tokens = OracleTokenizer(script).tokenize()
    return OracleStatementParser(tokens, ParserContext(), source=script)


def _split(script):
    return _parser(script).split()


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
    assert _parser(UNIT_THEN_TABLE).split_statements() == [
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
    assert _parser(s).split_statements() == ["SELECT 1 FROM dual"]
