"""MariaDB statement facts projected through the shared lexical engine."""

from dblift.core.sql_parser.statement_facts_parser import StatementFactsParser


class MariaDbFactsParser(StatementFactsParser):
    """The generic statement-facts parser, bound to the MariaDB plugin."""

    def __init__(self) -> None:
        """Bind the MariaDB plugin's spec and facts reader."""
        from dblift.db.provider_registry import ProviderRegistry

        super().__init__(ProviderRegistry.get_quirks("mariadb"))
