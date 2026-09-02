"""Parser context for managing parsing state.

This module provides centralized state management for SQL parsing,
tracking block depth, delimiters, and statement types.
"""

from dataclasses import dataclass, field
from typing import List, Optional

from dblift.core.sql_parser.tokens import Token


@dataclass
class ParserContext:
    """Centralized state management for SQL parsing.

    This class tracks the parsing state as we process tokens,
    including block nesting depth, current delimiter, and statement type.

    Attributes:
        block_depth: Current nesting level of blocks (BEGIN/END, etc.)
        block_initiator: The keyword that started the current block
        last_closed_block: The keyword from the most recently closed block
        delimiter: Current statement delimiter (; or / for Oracle, GO for SQL Server)
        statement_type: Type of the current statement (DDL, DML, PLSQL, etc.)
        parens_depth: Current nesting level of parentheses
        tokens: List of tokens processed so far (for lookahead/lookbehind)
    """

    block_depth: int = 0
    block_initiator: Optional[str] = None
    last_closed_block: Optional[str] = None
    delimiter: str = ";"
    statement_type: Optional[str] = None
    parens_depth: int = 0
    tokens: List[Token] = field(default_factory=list)

    def increase_block_depth(self, initiator: str) -> None:
        """Increase block depth and record the initiating keyword.

        Args:
            initiator: The keyword that started this block (BEGIN, IF, LOOP, etc.)
        """
        self.last_closed_block = None
        self.block_initiator = initiator
        self.block_depth += 1

    def decrease_block_depth(self) -> None:
        """Decrease block depth and record the closed block."""
        if self.block_depth > 0:
            self.last_closed_block = self.block_initiator
            self.block_depth -= 1

    def get_block_initiator(self) -> Optional[str]:
        """Get the keyword that initiated the current block.

        Returns:
            The initiating keyword or None if at top level
        """
        return self.block_initiator

    def get_last_closed_block_initiator(self) -> Optional[str]:
        """Get the keyword from the most recently closed block.

        Returns:
            The last closed block's initiating keyword or None
        """
        return self.last_closed_block

    def reset_for_new_statement(self) -> None:
        """Reset context for a new statement while preserving delimiter."""
        delimiter_backup = self.delimiter
        # Reset to defaults
        self.block_depth = 0
        self.block_initiator = None
        self.last_closed_block = None
        self.statement_type = None
        self.parens_depth = 0
        self.tokens = []
        self.delimiter = delimiter_backup  # MySQL DELIMITER survives across statements

    def __repr__(self) -> str:
        """String representation for debugging."""
        return (
            f"ParserContext(depth={self.block_depth}, "
            f"initiator={self.block_initiator}, "
            f"delimiter={self.delimiter!r}, "
            f"type={self.statement_type})"
        )
