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
