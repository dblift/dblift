"""Redshift parser retaining its declared literal and comment boundaries."""

from dblift.db.plugins.postgresql.parser.postgresql_regex_parser import PostgreSqlRegexParser
from dblift.db.plugins.redshift.parser.lexical_spec import REDSHIFT_SPEC


class RedshiftRegexParser(PostgreSqlRegexParser):
    """Inherit the shared scanner with the existing Redshift overrides."""

    lexical_spec = REDSHIFT_SPEC
