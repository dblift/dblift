"""Snowflake lexical safety cases from the completed native probe."""

from __future__ import annotations

import pytest

from dblift.core.exceptions import UnsafeStatementSplitError, UnsupportedMetaCommandError
from dblift.core.migration.sql.statement_splitter import StatementSplitter
from dblift.core.sql_parser.lexical_engine import LexicalEngine
from dblift.core.sql_parser.statement import execution_strings
from dblift.db.plugins.snowflake.lexical_spec import SNOWFLAKE_SPEC
from dblift.db.plugins.snowflake.statement_parser import SnowflakeStatementParser
from tests.support.splitting_cost import CountingText, Meter


@pytest.mark.parametrize(
    "opener,line_end",
    [
        ("--", "\n"),
        ("--", "\r"),
        ("//", "\n"),
        ("//", "\r"),
        ("//", "\r\n"),
    ],
)
def test_line_comment_ends_before_following_code(opener: str, line_end: str) -> None:
    first = f"SELECT 1 {opener} comment{line_end} + 2"
    records = StatementSplitter("snowflake").split(f"{first}; SELECT 3;")

    assert execution_strings(records) == [first, "SELECT 3"]


@pytest.mark.parametrize("opener", ["--", "//"])
@pytest.mark.parametrize("line_end", ["\r", "\r\n"])
def test_semicolon_after_cr_ends_comment_then_cuts_two_records(opener: str, line_end: str) -> None:
    first = f"SELECT 1 {opener} comment ;{line_end} + 2"
    records = StatementSplitter("snowflake").split(f"{first}; SELECT 3;")

    assert execution_strings(records) == [first, "SELECT 3"]


@pytest.mark.parametrize("body", ["$$BEGIN RETURN 1; END;$$", "'BEGIN RETURN 1; END;'"])
def test_quoted_anonymous_procedure_body_stays_one_unit(body: str) -> None:
    first = f"WITH p AS PROCEDURE () RETURNS INT LANGUAGE SQL AS {body} CALL p()"
    records = StatementSplitter("snowflake").split(f"{first}; SELECT 2;")

    assert execution_strings(records) == [first, "SELECT 2"]


def test_unquoted_anonymous_procedure_refuses_entire_script() -> None:
    script = (
        "SELECT 0; WITH p AS PROCEDURE () RETURNS INT LANGUAGE SQL AS "
        "BEGIN RETURN 1; END; CALL p();"
    )

    with pytest.raises(UnsafeStatementSplitError):
        StatementSplitter("snowflake").split(script)


def test_unquoted_anonymous_declare_refuses_entire_script() -> None:
    script = (
        "SELECT 0; WITH p AS PROCEDURE () RETURNS INT LANGUAGE SQL AS "
        "DECLARE x INTEGER; CALL p(); SELECT 2;"
    )

    with pytest.raises(UnsafeStatementSplitError):
        StatementSplitter("snowflake").split(script)


@pytest.mark.parametrize("kind", ["PROCEDURE", "FUNCTION"])
@pytest.mark.parametrize("replace", ["", "OR REPLACE "])
def test_unquoted_create_routine_body_refuses_entire_script(kind: str, replace: str) -> None:
    script = (
        f"SELECT 0; CREATE {replace}{kind} p() RETURNS INT LANGUAGE SQL AS "
        "BEGIN RETURN 1; END; SELECT 2;"
    )

    with pytest.raises(UnsafeStatementSplitError):
        StatementSplitter("snowflake").split(script)


@pytest.mark.parametrize("modifier", ["SECURE ", "TEMP ", "TEMPORARY "])
@pytest.mark.parametrize("body_head", ["BEGIN RETURN 1", "DECLARE x INTEGER"])
def test_modified_create_routine_body_refuses_entire_script(modifier: str, body_head: str) -> None:
    script = (
        f"SELECT 0; CREATE OR REPLACE {modifier}PROCEDURE p() RETURNS INT "
        f"LANGUAGE SQL AS {body_head}; END; SELECT 2;"
    )

    with pytest.raises(UnsafeStatementSplitError):
        StatementSplitter("snowflake").split(script)


def test_unmodified_create_function_as_declare_refuses_entire_script() -> None:
    script = (
        "SELECT 0; CREATE FUNCTION f() RETURNS INT LANGUAGE SQL AS "
        "DECLARE x INTEGER; BEGIN RETURN 1; END; SELECT 2;"
    )

    with pytest.raises(UnsafeStatementSplitError):
        StatementSplitter("snowflake").split(script)


def test_as_declare_without_later_begin_still_refuses_entire_script() -> None:
    script = (
        "SELECT 0; CREATE FUNCTION f() RETURNS INT LANGUAGE SQL AS DECLARE x INTEGER; SELECT 2;"
    )

    with pytest.raises(UnsafeStatementSplitError):
        StatementSplitter("snowflake").split(script)


@pytest.mark.parametrize("body", ["$$BEGIN RETURN 1; END;$$", "'BEGIN RETURN 1; END;'"])
def test_quoted_create_routine_body_remains_one_unit(body: str) -> None:
    first = f"CREATE PROCEDURE p() RETURNS INT LANGUAGE SQL AS {body}"
    assert execution_strings(StatementSplitter("snowflake").split(f"{first}; SELECT 2;")) == [
        first,
        "SELECT 2",
    ]


def test_ordinary_create_table_with_quoted_begin_is_not_refused() -> None:
    first = "CREATE TABLE t (id INT) COMMENT='BEGIN'"
    assert execution_strings(StatementSplitter("snowflake").split(f"{first}; SELECT 2;")) == [
        first,
        "SELECT 2",
    ]


def test_raw_record_line_projection_has_bounded_cost() -> None:
    counts = []
    for repetitions in (80, 320):
        script = "SELECT 1;\n" * repetitions
        meter = Meter()
        source = CountingText(script, meter)

        assert len(LexicalEngine(SNOWFLAKE_SPEC).split(source)) == repetitions
        counts.append(meter.count)
    assert counts[1] <= 4.5 * counts[0]


@pytest.mark.parametrize(
    "script,line,text",
    [
        (";\n/* lead */\n\u2002SELECT 1;", 2, "/* lead */\n\u2002SELECT 1"),
        (";\r\u2002SELECT 1;", 1, "SELECT 1"),
        (";\n\vSELECT 1;", 2, "\vSELECT 1"),
    ],
)
def test_raw_record_line_uses_first_retained_lexeme(script: str, line: int, text: str) -> None:
    records = StatementSplitter("snowflake").split(script)

    assert len(records) == 1
    assert records[0].line == line
    assert records[0].text == text


def test_tagged_dollar_looking_body_cannot_hide_a_semicolon() -> None:
    with pytest.raises(UnsafeStatementSplitError):
        StatementSplitter("snowflake").split("SELECT 0; SELECT $tag$a;b$tag$;")


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT $tag",
        "SELECT '$tag$;'",
        "SELECT 1 AS a$tag$",
    ],
)
def test_plain_parameter_and_quoted_or_identifier_dollars_are_preserved(sql: str) -> None:
    records = StatementSplitter("snowflake").split(f"{sql}; SELECT 2;")

    assert execution_strings(records) == [sql, "SELECT 2"]


@pytest.mark.parametrize("head", ["WORK", "TRANSACTION"])
def test_begin_with_intervening_comment_is_a_transaction_head(head: str) -> None:
    first = f"BEGIN/* gap */{head}"
    records = StatementSplitter("snowflake").split(f"{first}; SELECT 2;")

    assert execution_strings(records) == [first, "SELECT 2"]


def test_begin_with_intervening_comment_before_let_is_refused() -> None:
    with pytest.raises(UnsafeStatementSplitError):
        StatementSplitter("snowflake").split("BEGIN/* gap */LET x INTEGER := 1; END;")


def test_begin_transaction_with_extra_word_is_not_a_transaction_head() -> None:
    with pytest.raises(UnsafeStatementSplitError):
        StatementSplitter("snowflake").split("BEGIN TRANSACTION junk; SELECT 2;")


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT 'BEGIN LET x INTEGER := 1'",
        'SELECT 1 AS "BEGIN"',
        "SELECT 1 /* BEGIN LET x INTEGER := 1 */",
        "EXECUTE AS CALLER AS BEGIN",
        "BEGINTRANSACTIONjunk",
    ],
)
def test_begin_like_text_outside_the_head_is_not_reclassified(sql: str) -> None:
    records = StatementSplitter("snowflake").split(f"{sql}; SELECT 2;")

    assert execution_strings(records) == [sql, "SELECT 2"]


def test_empty_and_comment_only_segments_do_not_shift_the_next_source_span() -> None:
    script = ";;;--only;\n; SELECT 1;; SELECT 2"
    first_start = script.index("; SELECT 1") + 1
    first_end = script.index("SELECT 1;") + len("SELECT 1;")

    records = StatementSplitter("snowflake").split(script)

    assert execution_strings(records) == ["SELECT 1", "SELECT 2"]
    assert [(r.source_start, r.source_end, r.terminator) for r in records] == [
        (first_start, first_end, ";"),
        (first_end + 1, len(script), None),
    ]


@pytest.mark.parametrize("script", ["!source never-opened.sql", "SELECT 0;\n  !source x.sql"])
def test_line_leading_bang_command_refuses_entire_script(script: str) -> None:
    with pytest.raises(UnsupportedMetaCommandError):
        StatementSplitter("snowflake").split(script)


@pytest.mark.parametrize(
    "sql",
    ["SELECT 1 != 2", "SELECT 1\n != 2", "SELECT '!source'", "-- !source\nSELECT 1"],
)
def test_bang_within_sql_quote_or_comment_is_not_a_directive(sql: str) -> None:
    records = StatementSplitter("snowflake").split(f"{sql};")

    assert execution_strings(records) == [sql]


@pytest.mark.parametrize(
    "script",
    [
        "BEGIN LET x INTEGER := 1; RETURN x; END;",
        "BEGIN LET x INTEGER := 1; RETURN x; END; SELECT 2;",
        "BEGIN LET x INTEGER := 1; BEGIN LET y INTEGER := 2; END; END;",
        "DECLARE x INTEGER; BEGIN RETURN x; END;",
    ],
)
def test_retained_legacy_scanner_already_refuses_unquoted_scripting(script: str) -> None:
    with pytest.raises(UnsafeStatementSplitError):
        SnowflakeStatementParser().split(script)
