"""PostgreSQL lexical facts from docs/sql-parsing/postgresql.md."""

from dblift.core.sql_parser.lexical_spec import LexicalSpec

POSTGRESQL_SPEC = LexicalSpec(
    name="postgresql",
    text_blanks=" \t\n\r\f",
    unread_blanks_are_code=True,
    non_ascii_names=True,
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
    # The client sends a query to the server as a C string (libpq), so a NUL cuts it there and the rest is dropped
    # without an error. psql, psycopg 3 and the CockroachDB, YugabyteDB and Redshift servers behave alike
    # (docs/sql-parsing/postgresql.md, rows 31 to 31e). Every other family member reaches its server through libpq.
    refused_character="\x00",
    refused_character_name="NUL",
    refused_reason="the client sends the query as a C string, so the server never sees the rest",
)
