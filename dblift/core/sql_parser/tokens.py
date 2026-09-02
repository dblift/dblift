"""Token model for SQL tokenization.

This module defines the token types and Token class used in the tokenization-based
parser architecture inspired by Flyway's approach.
"""

from dataclasses import dataclass
from enum import Enum


class TokenType(Enum):
    """Token types for SQL tokenization."""

    KEYWORD = "KEYWORD"
    STRING = "STRING"
    COMMENT = "COMMENT"
    DELIMITER = "DELIMITER"
    SYMBOL = "SYMBOL"
    IDENTIFIER = "IDENTIFIER"
    NEW_DELIMITER = "NEW_DELIMITER"  # MySQL DELIMITER statement
    COMMENT_DIRECTIVE = "COMMENT_DIRECTIVE"  # MySQL /*!50001 ... */
    EOF = "EOF"


@dataclass
class Token:
    """Represents a single token in SQL content.

    Attributes:
        type: The type of token (KEYWORD, STRING, etc.)
        text: The actual text content of the token
        pos: Starting position in the source SQL
        line: Line number where the token appears
        col: Column number where the token starts
        parens_depth: Nesting level of parentheses (for MySQL CASE expressions)
    """

    type: TokenType
    text: str
    pos: int
    line: int
    col: int
    parens_depth: int = 0

    def __repr__(self) -> str:
        """String representation for debugging."""
        text_preview = self.text[:20] if len(self.text) > 20 else self.text
        return f"Token({self.type.name}, '{text_preview}', line={self.line}, col={self.col})"
