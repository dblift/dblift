"""Base statement parser for SQL splitting.

This module provides token-based statement parsing that splits SQL
into individual statements based on delimiters and block depth.
"""

from typing import Iterable, List, Optional

from dblift.core.sql_parser.parser_context import ParserContext
from dblift.core.sql_parser.tokens import Token, TokenType


class BaseStatementParser:
    """Base statement parser using token-based splitting.

    This parser processes a stream of tokens and splits them into statements
    based on delimiters, block depth, and dialect-specific rules.

    Subclasses should override methods for dialect-specific behavior:
    - _adjust_block_depth: Handle dialect-specific block keywords
    - _is_statement_end: Custom logic for statement boundaries
    """

    # a ';' inside parentheses ends a statement unless the dialect's client says otherwise
    # (PostgreSQL: psql tracks parentheses)
    TERMINATOR_RESPECTS_PARENS: bool = False

    #: What a statement's text may lose at its end; ``None`` strips every white space character.
    text_blanks: Optional[str] = None

    def __init__(
        self,
        tokens: Iterable[Token],
        context: Optional[ParserContext] = None,
        *,
        source: str,
    ):
        """Initialize the statement parser.

        Args:
            tokens: List of tokens to parse
            context: Parser context (created if not provided)
            source: The exact text the tokens were produced from. A statement
                is returned as a verbatim slice of this text (see
                ``_render_statement``), so whitespace, embedded comments and
                spacing reach the database unchanged.
        """
        self.tokens = tokens
        self.context = context or ParserContext()
        self.source = source

    def _render_statement(
        self,
        kept_tokens: List[Token],
        terminator: Optional[Token],
        dropped_terminator_pos: Optional[int],
    ) -> str:
        """Render one statement, verbatim from source.

        Leading plain comments (``TokenType.COMMENT``) are skipped when
        locating where the statement starts — like surrounding whitespace,
        they precede the statement rather than being it, and callers
        classify a statement by its real leading keyword. A segment that is
        only comments (no other token, not even the dropped terminator)
        stays dropped, matching historical behaviour. A MySQL/MariaDB
        comment directive (``TokenType.COMMENT_DIRECTIVE`` carries real
        text, unlike a plain comment) is not a plain comment and is kept,
        including as a statement's sole content.
        """
        first_content = next((t for t in kept_tokens if t.type != TokenType.COMMENT), None)
        if first_content is None:
            return ""
        start = first_content.pos
        if dropped_terminator_pos is not None:
            end = dropped_terminator_pos
        elif terminator is not None:
            end = terminator.pos + len(terminator.text)
        else:
            end = len(self.source)
        return self.source[start:end].rstrip(self.text_blanks)

    def _is_statement_end(self, token: Token) -> bool:
        """Check if token marks the end of a statement.

        Args:
            token: Token to check

        Returns:
            True if token marks statement boundary
        """
        # Delimiter at block depth 0 ends a statement
        if token.type == TokenType.DELIMITER and self.context.block_depth == 0:
            return not (self.TERMINATOR_RESPECTS_PARENS and token.parens_depth > 0)

        return False

    def _adjust_context(self, token: Token) -> None:
        """Update parser context based on token.

        This method updates block depth, parentheses depth, and other context
        based on the current token. Override in subclasses for
        dialect-specific behavior.

        Args:
            token: Current token being processed
        """
        # Track token in context
        self.context.tokens.append(token)

        # Adjust based on token type
        if token.type == TokenType.KEYWORD:
            self._adjust_block_depth(token)
        elif token.type == TokenType.SYMBOL:
            self._adjust_parens_depth(token)

    def _adjust_block_depth(self, token: Token) -> None:
        """Adjust block depth based on keyword.

        Override in subclasses for dialect-specific block handling.

        Args:
            token: Keyword token
        """
        keyword = token.text.upper()

        # Basic BEGIN/END handling (override in subclasses for more sophistication)
        if keyword == "BEGIN":
            self.context.increase_block_depth(keyword)
        elif keyword == "END":
            self.context.decrease_block_depth()

    def _adjust_parens_depth(self, token: Token) -> None:
        """Adjust parentheses depth tracking.

        Args:
            token: Symbol token
        """
        if token.text == "(":
            self.context.parens_depth += 1
        elif token.text == ")":
            self.context.parens_depth = max(0, self.context.parens_depth - 1)
