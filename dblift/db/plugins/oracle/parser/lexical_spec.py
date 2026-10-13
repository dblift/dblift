"""Oracle lexical facts from docs/sql-parsing/oracle.md."""

from dblift.core.sql_parser.lexical_spec import LexicalSpec

ORACLE_SPEC = LexicalSpec(
    name="oracle",
    client_name="SQL*Plus",
    terminator_respects_parens=True,
    alternative_quotes=("q'", "nq'"),
    alternative_quote_pairs=(("[", "]"), ("{", "}"), ("<", ">"), ("(", ")")),
    quoted_identifier_escape=False,
    parameter_prefix="",
    placeholder_open=None,
)
