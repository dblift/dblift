"""Redshift lexical overrides of the PostgreSQL spec."""

from dataclasses import replace

from dblift.db.plugins.postgresql.parser.lexical_spec import POSTGRESQL_SPEC

REDSHIFT_SPEC = replace(
    POSTGRESQL_SPEC,
    name="redshift",
    text_blanks=" \t\n\r\f",
    nested_comments=False,
    plain_string_escapes=True,
)
