"""DuckDB statement facts projected through the shared lexical engine."""

from dblift.core.sql_parser.lexical_engine import LexicalEngine
from dblift.core.sql_parser.statement_facts import SqlglotStatementFactsReader, StatementFacts
from dblift.core.sql_parser.statement_facts_parser import StatementFactsParser
from dblift.db.plugins.duckdb.parser.lexical_spec import DUCKDB_SPEC


class DuckDBStatementFactsReader(SqlglotStatementFactsReader):
    """Keep DuckDB comment semantics authoritative before reading the AST."""

    def read(self, sql: str) -> StatementFacts:
        """Read engine-selected SQL with nested comments removed."""
        text = LexicalEngine(DUCKDB_SPEC).blank_comments(sql)
        return super().read(text) if text.strip() else StatementFacts("UNKNOWN", "UNKNOWN")


class DuckDBFactsParser(StatementFactsParser):
    """The generic statement-facts parser, bound to the DuckDB plugin."""

    def __init__(self) -> None:
        """Bind the DuckDB plugin's spec and facts reader."""
        from dblift.db.provider_registry import ProviderRegistry

        super().__init__(ProviderRegistry.get_quirks("duckdb"))
