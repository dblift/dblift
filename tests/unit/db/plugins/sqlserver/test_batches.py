"""A T-SQL script is cut into batches at ``GO`` lines and nowhere else (docs/sql-parsing/sqlserver.md)."""

from collections import namedtuple

import pytest

from dblift.core.exceptions import UnsafeStatementSplitError
from dblift.core.migration.sql.sql_analyzer import SqlAnalyzer
from dblift.core.sql_parser.lexical_engine import LexicalEngine
from dblift.core.sql_parser.statement import Statement
from dblift.db.plugins.sqlserver.parser.lexical_spec import SQLSERVER_SPEC
from dblift.db.plugins.sqlserver.parser.sqlserver_regex_parser import SqlServerRegexParser

Batch = namedtuple("Batch", "text line repeat terminated")


def batches_of(script, spec=SQLSERVER_SPEC):
    """The batch records of the shared engine, in the shape these tests read."""
    return [
        Batch(r.text, r.line, r.repeat, r.terminator == "GO")
        for r in LexicalEngine(spec).split(script)
    ]


def _texts(script):
    return [batch.text for batch in batches_of(script)]


def test_a_semicolon_never_ends_a_batch():
    script = "DECLARE @x INT = 1;\nSELECT @x;\nGO"
    assert _texts(script) == ["DECLARE @x INT = 1;\nSELECT @x;"]


def test_go_ends_a_batch_and_is_not_part_of_it():
    assert batches_of("SELECT 1\nGO\nSELECT 2\nGO\n") == [
        Batch("SELECT 1", 1, 1, True),
        Batch("SELECT 2", 3, 1, True),
    ]


def test_the_last_batch_runs_without_a_go():
    assert batches_of("SELECT 1\nGO\nSELECT 2;") == [
        Batch("SELECT 1", 1, 1, True),
        Batch("SELECT 2;", 3, 1, False),
    ]


@pytest.mark.parametrize(
    "script",
    ["", "   \n\n", "GO\nGO\n", "-- only a comment\nGO\n", "/* a */\nGO", ";\nGO\n", ";;\n;\n"],
)
def test_a_batch_of_blanks_comments_and_semicolons_is_not_a_statement(script):
    assert batches_of(script) == []


def test_batch_text_is_verbatim_between_the_go_lines_without_surrounding_blanks():
    script = "\n  SELECT 1  /* c */\n\n  -- note\nGO\n"
    assert batches_of(script) == [Batch("SELECT 1  /* c */\n\n  -- note", 2, 1, True)]


def test_the_line_of_a_batch_is_the_line_of_its_first_character():
    script = "SELECT 1\nGO\n\n\n-- header\nSELECT 2\nGO\n"
    assert [(b.line, b.text) for b in batches_of(script)] == [
        (1, "SELECT 1"),
        (5, "-- header\nSELECT 2"),
    ]


@pytest.mark.parametrize(
    "script",
    [
        "SELECT 'a\nGO\nb' AS s",
        "SELECT N'a\nGO\nb' AS s",
        "SELECT 1 AS [a\nGO\nb]",
        'SELECT 1 AS "a\nGO\nb"',
        "SELECT 1 /* a\nGO\nb */",
        "SELECT 'it''s\nGO\nstill'",
        "SELECT [a]]b\nGO\nc]",
    ],
)
def test_go_alone_on_a_line_inside_a_lexeme_is_text(script):
    assert _texts(script + "\nGO\n") == [script]


@pytest.mark.parametrize(
    "script",
    [
        "SELECT 1 -- it's\nGO\nSELECT 2",
        "/* it's */ SELECT 1\nGO\nSELECT 2",
        "SELECT '--' AS a\nGO\nSELECT 2",
        "SELECT '/*' AS a\nGO\nSELECT 2",
        "SELECT 1 -- /*\nGO\nSELECT 2",
        "/* -- */ SELECT 1\nGO\nSELECT 2",
        "SELECT 1 AS [it's]\nGO\nSELECT 2",
        'SELECT 1 AS "it\'s"\nGO\nSELECT 2',
    ],
)
def test_comment_and_literal_markers_inside_each_other_do_not_swallow_the_go(script):
    assert len(batches_of(script)) == 2


def test_a_block_comment_ends_at_its_first_close_row_6c():
    script = "SELECT 1 /* a\nGO\n/* b */\nGO\n*/"
    assert _texts(script) == ["SELECT 1 /* a\nGO\n/* b */", "*/"]


def test_the_server_nests_so_the_splitter_passes_a_nested_comment_through_verbatim():
    script = "SELECT /* a /* b */ */ 1"
    assert _texts(script) == [script]


@pytest.mark.parametrize(
    "script, what, line, column",
    [
        ("SELECT 'abc\nGO\n", "string", 1, 8),
        ("SELECT 1 AS [abc\nGO\n", "bracketed identifier", 1, 13),
        ('SELECT 1 AS "abc\nGO\n', "quoted identifier", 1, 13),
        ("SELECT 1\n/* x\nGO\nSELECT 2", "block comment", 2, 1),
    ],
)
def test_an_unterminated_lexeme_is_refused_with_its_position(script, what, line, column):
    with pytest.raises(UnsafeStatementSplitError) as excinfo:
        batches_of(script)
    assert f"unterminated {what} opened at line {line}, column {column}" in str(excinfo.value)


def test_a_utf8_byte_order_mark_is_not_part_of_the_first_batch():
    assert _texts("\ufeffSELECT 1\nGO\nSELECT 2") == ["SELECT 1", "SELECT 2"]


def test_crlf_line_ends_keep_the_text_verbatim_and_still_separate():
    script = "SELECT 1\r\nGO\r\nSELECT 2\r\n/* a\r\nGO\r\n*/\r\nGO\r\n"
    assert _texts(script) == ["SELECT 1", "SELECT 2\r\n/* a\r\nGO\r\n*/"]


def test_a_command_looking_word_in_the_middle_of_a_line_is_text():
    script = "SELECT 1 AS go;\nSELECT go INT FROM t;\nSELECT 1 GO\nINTO t\nGOTO label\nGO"
    assert _texts(script) == [script.rsplit("\nGO", 1)[0]]


def test_split_returns_statement_records_with_the_terminator_that_ended_them():
    records = SqlServerRegexParser().split("SELECT 1\nGO\nSELECT 2")
    assert records == [
        Statement(text="SELECT 1", line=1, terminator="GO"),
        Statement(text="SELECT 2", line=3, terminator=None),
    ]


def test_split_statements_is_the_projection_execution_receives():
    parser = SqlServerRegexParser()
    assert parser.split_statements(
        "CREATE TABLE a (x INT);\nINSERT INTO a VALUES (1);\nGO\nSELECT 1;"
    ) == [
        "CREATE TABLE a (x INT);\nINSERT INTO a VALUES (1);",
        "SELECT 1;",
    ]


def test_the_execution_entry_point_splits_by_batch():
    statements = SqlAnalyzer("sqlserver").split_statements(
        "DECLARE @x INT = 1;\nSELECT @x;\nGO\nSELECT 2;"
    )
    assert statements == ["DECLARE @x INT = 1;\nSELECT @x;", "SELECT 2;"]


def test_a_splitter_failure_is_a_refusal_and_never_a_guess(monkeypatch):
    def broken(self, script):
        raise ValueError("boom")

    monkeypatch.setattr(LexicalEngine, "split_statements", broken)
    with pytest.raises(UnsafeStatementSplitError, match="sqlserver statement splitter failed"):
        SqlAnalyzer("sqlserver").split_statements("SELECT 1;\nSELECT 2;")
