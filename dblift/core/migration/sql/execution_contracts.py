"""Minimal parsing operations required by SQL execution."""

from typing import List, Protocol


class ExecutionSqlParser(Protocol):
    """Classify and split migration SQL without requiring schema extraction."""

    def get_statement_type(self, sql: str) -> str:
        """Return the statement category used by execution."""
        ...

    def split_statements(self, sql: str, strict_tokenizer: bool = False) -> List[str]:
        """Return the dialect-aware execution statements."""
        ...

    def split_statements_for_analysis(self, sql: str, strict_tokenizer: bool = False) -> List[str]:
        """Return the statements of a script for callers that read it statement by statement."""
        ...
