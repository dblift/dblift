"""Preserved Redshift lexical overrides; live conformance remains unverified."""

from dataclasses import replace

from dblift.db.plugins.postgresql.parser.lexical_spec import POSTGRESQL_SPEC

REDSHIFT_SPEC = replace(
    POSTGRESQL_SPEC, name="redshift", nested_comments=False, plain_string_escapes=True
)
