"""Compatibility parser projections of SQLite lexical statements and facts."""

from __future__ import annotations

from typing import Any, Dict

from dblift.core.exceptions import UnsafeStatementSplitError, UnsupportedMetaCommandError
from dblift.core.sql_parser.statement_facts_parser import StatementFactsParser


class SQLiteFactsParser(StatementFactsParser):
    """The generic statement-facts parser, bound to the SQLite plugin."""

    def __init__(self) -> None:
        """Bind the SQLite plugin's spec and facts reader."""
        from dblift.db.provider_registry import ProviderRegistry

        super().__init__(ProviderRegistry.get_quirks("sqlite"))

    def validate_sql(self, sql_content: str) -> Dict[str, Any]:
        """Report whether every selected statement has readable facts."""
        try:
            self.split_for_analysis(sql_content)
        except (UnsafeStatementSplitError, UnsupportedMetaCommandError) as exc:
            return {"valid": False, "statements_found": 0, "errors": [str(exc)]}
        return super().validate_sql(sql_content)
