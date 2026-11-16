"""Parser context for managing parsing state.

This module provides centralized state management for SQL parsing,
tracking block depth and parentheses depth.
"""

from dataclasses import dataclass, field
from typing import List, Optional

from dblift.core.sql_parser.tokens import Token


@dataclass
class ParserContext:
    """Centralized state management for SQL parsing.

    This class tracks the parsing state as we process tokens,
    including block nesting depth and parentheses depth.

    Attributes:
        block_depth: Current nesting level of blocks (BEGIN/END, etc.)
        block_initiators: Keywords of the open blocks, innermost last
        parens_depth: Current nesting level of parentheses
        tokens: List of tokens processed so far (for lookahead/lookbehind)
    """

    block_depth: int = 0
    block_initiators: List[str] = field(default_factory=list)
    parens_depth: int = 0
    tokens: List[Token] = field(default_factory=list)

    def increase_block_depth(self, initiator: str) -> None:
        """Increase block depth and record the initiating keyword.

        Args:
            initiator: The keyword that started this block (BEGIN, IF, LOOP, etc.)
        """
        self.block_initiators.append(initiator)
        self.block_depth += 1

    def decrease_block_depth(self) -> None:
        """Decrease block depth, dropping the closed block's initiator."""
        if self.block_depth > 0:
            if self.block_initiators:
                self.block_initiators.pop()
            self.block_depth -= 1

    def get_block_initiator(self) -> Optional[str]:
        """Get the keyword that initiated the current block.

        Returns:
            The initiating keyword or None if at top level
        """
        return self.block_initiators[-1] if self.block_initiators else None

    def reset_for_new_statement(self) -> None:
        """Reset context for a new statement."""
        self.block_depth = 0
        self.block_initiators = []
        self.parens_depth = 0
        self.tokens = []

    def __repr__(self) -> str:
        """String representation for debugging."""
        return (
            f"ParserContext(depth={self.block_depth}, " f"initiator={self.get_block_initiator()})"
        )
