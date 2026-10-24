"""Redshift lexical overrides of the PostgreSQL spec, as measured on Redshift Serverless
1.0.485645 (docs/sql-parsing/redshift.md).

Block comments nest, a backslash escapes the next character in every ``'...'`` literal, ``E'...'``
is a type name before such a literal (no escape prefix), ``COPY ... FROM STDIN`` and a
``BEGIN ATOMIC`` function body are syntax errors (no data block, no atomic body), and the form feed
is a blank.
"""

from dataclasses import replace

from dblift.db.plugins.postgresql.parser.lexical_spec import POSTGRESQL_SPEC

REDSHIFT_SPEC = replace(
    POSTGRESQL_SPEC,
    name="redshift",
    text_blanks=" \t\n\r\f",
    plain_string_escapes=True,
    escape_prefixes=(),
    copy_from_stdin=False,
    block_opener=("", ""),
)
