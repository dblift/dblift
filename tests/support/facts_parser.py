"""The parser every SQL dialect is served: its lexical spec splits, its statement facts read."""

from dblift.core.sql_parser.statement_facts_parser import StatementFactsParser
from dblift.db.provider_registry import ProviderRegistry


def facts_parser(dialect: str) -> StatementFactsParser:
    """A statement-facts parser bound to *dialect*'s plugin."""
    return StatementFactsParser(ProviderRegistry.get_quirks(dialect))


def facts_factory(dialect: str):
    """A zero-argument callable building a facts parser for *dialect* (stands in for a class)."""
    return lambda: facts_parser(dialect)
