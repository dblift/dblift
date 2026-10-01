"""Redshift string literals use backslash escapes even without an E prefix."""

from dblift.core.sql_parser.tokens import Token
from dblift.db.plugins.postgresql.parser.postgresql_tokenizer import NonNestingPostgreSQLTokenizer


class RedshiftTokenizer(NonNestingPostgreSQLTokenizer):
    """Read Redshift strings while retaining its non-nesting comment rule."""

    def _handle_string(self) -> Token:
        """Use backslash escapes in every single-quoted string literal."""
        if self.peek() == "'":
            return self._handle_escape_string()
        return super()._handle_string()
