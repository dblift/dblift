"""Measured Snowflake lexical boundaries before statement facts are enabled."""

from __future__ import annotations

import pytest

from dblift.core.exceptions import UnsafeStatementSplitError
from dblift.core.migration.sql.statement_splitter import StatementSplitter
from dblift.core.sql_parser.lexical_spec import LexicalSpec
from dblift.core.sql_parser.statement import analysis_sql, execution_strings
from dblift.db.provider_registry import ProviderRegistry


@pytest.mark.parametrize(
    "script,expected",
    [
        (
            "SELECT 1 // semicolon ; in comment\n + 2; SELECT 3;",
            ["SELECT 1 // semicolon ; in comment\n + 2", "SELECT 3"],
        ),
        ("// comment ; before code\nSELECT 1;", ["// comment ; before code\nSELECT 1"]),
        ("SELECT 8 / 2; SELECT 'a//b;c';", ["SELECT 8 / 2", "SELECT 'a//b;c'"]),
    ],
)
def test_slash_line_comment_preserves_division_and_quoted_slashes(
    script: str, expected: list[str]
) -> None:
    records = StatementSplitter("snowflake").split(script)

    assert execution_strings(records) == expected
    assert analysis_sql(records) == expected


def test_block_comment_closes_at_first_end_even_with_an_inner_opener() -> None:
    script = "SELECT 1 /* outer /* inner */ + 2; SELECT 3;"

    records = StatementSplitter("snowflake").split(script)

    assert execution_strings(records) == ["SELECT 1 /* outer /* inner */ + 2", "SELECT 3"]


def test_fixed_dollar_quote_and_dollar_within_an_identifier() -> None:
    script = "SELECT $$a;b$$; SELECT 1 AS a$$b;"

    records = StatementSplitter("snowflake").split(script)

    assert execution_strings(records) == ["SELECT $$a;b$$", "SELECT 1 AS a$$b"]


@pytest.mark.parametrize(
    "literal",
    [
        "'it''s;ok'",
        "'it\\'s;ok'",
        "'a\nb;c'",
        "'/*a*/;--b'",
        '"a""b;c"',
        '"a\nb;c"',
    ],
)
def test_quoted_semicolons_remain_in_one_statement(literal: str) -> None:
    script = f"SELECT {literal}; SELECT 2;"

    records = StatementSplitter("snowflake").split(script)

    assert execution_strings(records) == [f"SELECT {literal}", "SELECT 2"]


@pytest.mark.parametrize("head", ["BEGIN", "BEGIN WORK", "BEGIN TRANSACTION"])
def test_transaction_begin_is_a_separate_execution_unit(head: str) -> None:
    records = StatementSplitter("snowflake").split(f"{head}; SELECT 1;")

    assert execution_strings(records) == [head, "SELECT 1"]


@pytest.mark.parametrize(
    "script",
    [
        "BEGIN LET x INTEGER := 1; RETURN x; END;",
        "DECLARE x INTEGER; BEGIN RETURN x; END;",
        "SELECT 1; BEGIN LET x INTEGER := 1; RETURN x; END;",
    ],
)
def test_unquoted_scripting_refuses_the_whole_script(script: str) -> None:
    with pytest.raises(UnsafeStatementSplitError):
        StatementSplitter("snowflake").split(script)


def test_comment_and_empty_segments_preserve_raw_source_spans() -> None:
    script = "  ;-- only\n; \n-- lead\nSELECT 1; ; SELECT 2;"
    first_start = script.index("; \n-- lead") + 1
    first_end = script.index("SELECT 1;") + len("SELECT 1;")
    second_start = script.index("; SELECT 2", first_end) + 1

    records = StatementSplitter("snowflake").split(script)

    assert [record.text for record in records] == ["-- lead\nSELECT 1", "SELECT 2"]
    assert execution_strings(records) == ["-- lead\nSELECT 1", "SELECT 2"]
    assert analysis_sql(records) == execution_strings(records)
    assert [(record.source_start, record.source_end) for record in records] == [
        (first_start, first_end),
        (second_start, len(script)),
    ]
    assert [record.terminator for record in records] == [";", ";"]


@pytest.mark.parametrize("blank", [" ", "\t", "\n", "\r", "\u2002"])
def test_only_measured_text_blanks_are_trimmed(blank: str) -> None:
    records = StatementSplitter("snowflake").split(f"{blank}SELECT 1{blank};")

    assert execution_strings(records) == ["SELECT 1"]


@pytest.mark.parametrize("unread", ["\v", "\f", "\u00a0", "\u2000", "\u200b", "\u2028"])
def test_sampled_unsupported_edge_characters_remain_in_execution_text(unread: str) -> None:
    sql = f"{unread}SELECT 1{unread}"
    records = StatementSplitter("snowflake").split(f"{sql};")

    assert execution_strings(records) == [sql]


def test_snowflake_spec_uses_the_measured_blank_and_name_boundary() -> None:
    spec = ProviderRegistry.get_quirks("snowflake").lexical_spec()

    assert isinstance(spec, LexicalSpec)
    assert spec.text_blanks == " \t\n\r\u2002"
    assert spec.unread_blanks_are_code
    assert not spec.non_ascii_names
