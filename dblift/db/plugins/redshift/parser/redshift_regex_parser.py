"""Redshift regex parser with dialect-specific literal boundaries."""

from dblift.db.plugins.postgresql.parser.postgresql_regex_parser import (
    NonNestingPostgreSqlRegexParser,
)
from dblift.db.plugins.redshift.parser.redshift_tokenizer import RedshiftTokenizer


class RedshiftRegexParser(NonNestingPostgreSqlRegexParser):
    """Use Redshift's backslash-escaping rule when splitting statements."""

    tokenizer_class = RedshiftTokenizer
