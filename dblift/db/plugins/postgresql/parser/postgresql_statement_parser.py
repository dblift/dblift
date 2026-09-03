"""PostgreSQL-specific statement parser.

This module provides PostgreSQL-specific statement parsing including
BEGIN ATOMIC handling and transaction detection.
"""

from typing import List, Optional

from dblift.core.sql_parser.base_statement_parser import BaseStatementParser
from dblift.core.sql_parser.parser_context import ParserContext
from dblift.core.sql_parser.tokens import Token, TokenType


class PostgreSQLStatementParser(BaseStatementParser):
    """PostgreSQL-specific statement parser.

    Handles PostgreSQL-specific features:
    - BEGIN ATOMIC blocks
    - CASE expressions within ATOMIC blocks
    - Transaction compatibility detection
    """

    # Statements that cannot run in transactions
    NO_TRANSACTION_PATTERNS = [
        "CREATE DATABASE",
        "DROP DATABASE",
        "CREATE TABLESPACE",
        "DROP TABLESPACE",
        "CREATE SUBSCRIPTION",
        "DROP SUBSCRIPTION",
        "ALTER SYSTEM",
        "CREATE INDEX CONCURRENTLY",
        "DROP INDEX CONCURRENTLY",
        "CREATE UNIQUE INDEX CONCURRENTLY",
        "REINDEX SCHEMA",
        "REINDEX DATABASE",
        "REINDEX SYSTEM",
        "VACUUM",
        "DISCARD ALL",
        "ALTER TYPE",
        "ADD VALUE",  # Version dependent
    ]

    def __init__(self, tokens: List[Token], context: Optional[ParserContext] = None):
        """Initialize PostgreSQL statement parser.

        Args:
            tokens: List of tokens to parse
            context: Parser context
        """
        super().__init__(tokens, context)
        self.in_atomic_block = False

    def _adjust_block_depth(self, token: Token) -> None:
        """Adjust block depth for PostgreSQL.

        Handles:
        - BEGIN ATOMIC blocks
        - CASE expressions within ATOMIC blocks

        Args:
            token: Keyword token
        """
        keyword = token.text.upper()

        # Handle BEGIN
        if keyword == "BEGIN":
            # Check if next token is ATOMIC
            next_token = self._peek_next_token()
            if next_token and next_token.text.upper() == "ATOMIC":
                # BEGIN ATOMIC - will be increased when we see ATOMIC
                pass
            else:
                # Regular BEGIN (transaction start, not a block)
                pass

        # Handle ATOMIC after BEGIN
        elif keyword == "ATOMIC":
            # Check if preceded by BEGIN (exclude current token from search)
            # Current token (ATOMIC) is already in context.tokens, so look at tokens before it
            for token in reversed(self.context.tokens[:-1]):  # Exclude current token
                if token.type == TokenType.COMMENT:
                    continue
                if token.type == TokenType.KEYWORD and token.text.upper() == "BEGIN":
                    self.context.increase_block_depth("ATOMIC")
                    self.in_atomic_block = True
                break  # Stop at first non-comment token

        # Handle CASE within ATOMIC blocks
        elif keyword == "CASE" and self.in_atomic_block:
            self.context.increase_block_depth("CASE")

        # Handle END
        elif keyword == "END":
            if self.context.block_depth > 0:
                initiator = self.context.get_block_initiator()
                if initiator in ("ATOMIC", "CASE"):
                    self.context.decrease_block_depth()

                    # Check if we're exiting ATOMIC block
                    if initiator == "ATOMIC":
                        self.in_atomic_block = False

    def can_execute_in_transaction(self) -> bool:
        """Check if current statement can execute in a transaction.

        Returns:
            True if statement can run in transaction
        """
        # Reconstruct statement text from tokens
        stmt_text = self._tokens_to_string(self.context.tokens).upper()

        # Check against no-transaction patterns
        for pattern in self.NO_TRANSACTION_PATTERNS:
            if pattern in stmt_text:
                return False

        return True
