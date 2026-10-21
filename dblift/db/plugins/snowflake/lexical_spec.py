"""Snowflake migration-script rules for the shared lexical engine."""

from dblift.core.sql_parser.lexical_spec import LexicalSpec

SNOWFLAKE_SPEC = LexicalSpec(
    name="snowflake",
    text_blanks=" \t\n\r\u2002",
    unread_blanks_are_code=True,
    nested_comments=False,
    plain_string_escapes=True,
    dollar_quotes=True,
    dollar_quote_tags=False,
    slash_line_comments=True,
    line_comment_ends="\r\n",
    meta_prefix="!",
    meta_prefix_line_start=True,
    client_name="Snowflake",
    raw_segment_records=True,
    refuse_unquoted_scripting=True,
)
