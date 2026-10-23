"""Snowflake statement facts projected through the shared lexical engine."""

from dblift.core.sql_parser.statement_facts_parser import StatementFactsParser


class SnowflakeLexicalParser(StatementFactsParser):
    """The generic statement-facts parser, bound to the Snowflake plugin."""

    def __init__(self) -> None:
        """Bind the Snowflake plugin's spec and facts reader."""
        from dblift.db.provider_registry import ProviderRegistry

        super().__init__(ProviderRegistry.get_quirks("snowflake"))
