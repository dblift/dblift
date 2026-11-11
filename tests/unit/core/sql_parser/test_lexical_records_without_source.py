"""Records cut from a token stream whose source text was not given to the parser.

Without the source the parser rebuilds each statement from its tokens and has no
offsets to report for where a statement starts, where an unterminated one ends, or
which statements a psql ``\\;`` joins.
"""

from dataclasses import astuple
from typing import List

from dblift.core.sql_parser.lexical_spec import LexicalSpec
from dblift.core.sql_parser.lexical_statement_parser import LexicalStatementParser
from dblift.core.sql_parser.lexical_tokenizer import LexicalTokenizer
from dblift.core.sql_parser.parser_context import ParserContext
from dblift.core.sql_parser.statement import Statement
from dblift.db.plugins.postgresql.parser.lexical_spec import POSTGRESQL_SPEC
from dblift.db.plugins.snowflake.lexical_spec import SNOWFLAKE_SPEC


def _split_without_source(script: str, spec: LexicalSpec) -> List[Statement]:
    tokens = LexicalTokenizer(script, spec=spec).tokenize()
    return LexicalStatementParser(tokens, ParserContext(), spec=spec).split()


def test_copy_from_stdin_without_source_is_rebuilt_from_its_tokens() -> None:
    records = _split_without_source("COPY t (a) FROM STDIN;\n1\n2\n\\.\nSELECT 1;", POSTGRESQL_SPEC)

    # astuple compares every field, including those Statement equality ignores.
    assert astuple(records[0]) == astuple(
        Statement(
            text="COPY t(a) FROM STDIN;1\n2\n",
            line=1,
            terminator="\\.",
            kind="copy_stdin",
        )
    )


def test_unterminated_combined_statement_without_source_has_no_offsets_or_parts() -> None:
    records = _split_without_source("SELECT 1 \\; SELECT 2", POSTGRESQL_SPEC)

    assert [astuple(r) for r in records] == [
        ("SELECT 1 \\; SELECT 2", 1, None, "sql", True, 1, None, None, None, None)
    ]


def test_raw_segment_records_without_source_have_no_start_offset() -> None:
    records = _split_without_source("SELECT 1;\n-- c\nSELECT 2", SNOWFLAKE_SPEC)

    assert [astuple(r) for r in records] == [
        ("SELECT 1", 1, ";", "sql", False, 1, None, None, 9, None),
        ("SELECT 2", 2, None, "sql", False, 1, None, None, None, None),
    ]
