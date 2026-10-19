"""PostgreSQL lexical facts from docs/sql-parsing/postgresql.md."""

from dblift.core.sql_parser.lexical_spec import LexicalSpec

POSTGRESQL_SPEC = LexicalSpec(
    name="postgresql",
    text_blanks=" \t\n\r\f",
    unread_blanks_are_code=True,
    client_name="psql",
    nested_comments=True,
    escape_prefixes=("E'", "e'"),
    dollar_quotes=True,
    meta_prefix="\\",
    safe_meta_commands=frozenset({"\\restrict", "\\unrestrict"}),
    combine_terminator="\\;",
    copy_from_stdin=True,
    terminator_respects_parens=True,
    routine_heads=(
        ("CREATE", "FUNCTION"),
        ("CREATE", "PROCEDURE"),
        ("CREATE", "OR", "REPLACE", "FUNCTION"),
        ("CREATE", "OR", "REPLACE", "PROCEDURE"),
    ),
    block_opener=("BEGIN", "ATOMIC"),
    nested_block_keywords=frozenset({"CASE"}),
    block_closer="END",
)
