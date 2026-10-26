"""PostgreSQL statement facts with foreign-table grammar support."""

from __future__ import annotations

from typing import TYPE_CHECKING

from dblift.core.sql_parser.statement_facts import SqlglotStatementFactsReader

if TYPE_CHECKING:
    from sqlglot.dialects import Dialect


class PostgresqlStatementFactsReader(SqlglotStatementFactsReader):
    """Read PostgreSQL facts with its plugin-owned foreign-table grammar."""

    def read_dialect(self) -> type[Dialect]:
        """Load the optional grammar only when statement facts are read."""
        from dblift.db.plugins.postgresql.foreign_table_dialect import PostgresForeignTable

        return PostgresForeignTable
