"""SQL Server lexical facts from docs/sql-parsing/sqlserver.md."""

from dblift.core.sql_parser.lexical_spec import LexicalSpec

SQLSERVER_SPEC = LexicalSpec(
    name="sqlserver",
    client_name="sqlcmd",
    nested_comments=False,
    quoted_identifier='"',
    bracket_identifier=("[", "]"),
    leading_bom_is_blank=True,
    silent_unclaimed=True,
    placeholder_open=None,
)
