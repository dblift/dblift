"""Base statement parser for SQL splitting.

This module provides token-based statement parsing that splits SQL
into individual statements based on delimiters and block depth.
"""

from typing import List, Optional

from core.sql_parser.parser_context import ParserContext
from core.sql_parser.tokens import Token, TokenType


class BaseStatementParser:
    """Base statement parser using token-based splitting.

    This parser processes a stream of tokens and splits them into statements
    based on delimiters, block depth, and dialect-specific rules.

    Subclasses should override methods for dialect-specific behavior:
    - _adjust_block_depth: Handle dialect-specific block keywords
    - _adjust_delimiter: Handle dynamic delimiters (MySQL DELIMITER, Oracle /)
    - _is_statement_end: Custom logic for statement boundaries
    """

    def __init__(self, tokens: List[Token], context: Optional[ParserContext] = None):
        """Initialize the statement parser.

        Args:
            tokens: List of tokens to parse
            context: Parser context (created if not provided)
        """
        self.tokens = tokens
        self.context = context or ParserContext()
        self.current_idx = 0

    def split_statements(self) -> List[str]:
        """Split tokens into statements based on delimiters and block depth.

        Returns:
            List of SQL statement strings
        """
        statements = []
        current_statement_tokens: List[Token] = []

        for idx, token in enumerate(self.tokens):
            self.current_idx = idx

            # Skip EOF tokens
            if token.type == TokenType.EOF:
                continue

            # Adjust context based on token
            self._adjust_context(token)

            # Add token to current statement
            current_statement_tokens.append(token)

            # Check if this marks end of statement
            if self._is_statement_end(token):
                # SQL Server "GO" is a batch separator for tools (SSMS); it is not executable
                # via the native driver and must not be emitted as its own statement.
                stmt_tokens = current_statement_tokens
                if (
                    token.type == TokenType.DELIMITER
                    and token.text.upper() == "GO"
                    and len(stmt_tokens) >= 1
                    and stmt_tokens[-1].type == TokenType.DELIMITER
                    and stmt_tokens[-1].text.upper() == "GO"
                ):
                    stmt_tokens = stmt_tokens[:-1]
                stmt_text = self._tokens_to_string(stmt_tokens)
                if stmt_text.strip():
                    statements.append(stmt_text)
                current_statement_tokens = []

        # Handle any remaining tokens
        if current_statement_tokens:
            stmt_text = self._tokens_to_string(current_statement_tokens)
            if stmt_text.strip():
                statements.append(stmt_text)

        return statements

    def _is_statement_end(self, token: Token) -> bool:
        """Check if token marks the end of a statement.

        Args:
            token: Token to check

        Returns:
            True if token marks statement boundary
        """
        # Delimiter at block depth 0 ends a statement
        if token.type == TokenType.DELIMITER and self.context.block_depth == 0:
            return True

        return False

    def _adjust_context(self, token: Token) -> None:
        """Update parser context based on token.

        This method updates block depth, delimiter, and other context
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
            self._adjust_delimiter(token)
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

    def _adjust_delimiter(self, token: Token) -> None:
        """Adjust current delimiter based on token.

        Override in subclasses for dialect-specific delimiter handling
        (e.g., MySQL DELIMITER statement, Oracle / for PL/SQL).

        Args:
            token: Token that may change delimiter
        """
        pass  # Override in subclasses

    def _adjust_parens_depth(self, token: Token) -> None:
        """Adjust parentheses depth tracking.

        Args:
            token: Symbol token
        """
        if token.text == "(":
            self.context.parens_depth += 1
        elif token.text == ")":
            self.context.parens_depth = max(0, self.context.parens_depth - 1)

    def _tokens_to_string(self, tokens: List[Token]) -> str:
        """Convert tokens back to SQL string.

        This reconstructs the original SQL from tokens, preserving
        whitespace and formatting.

        Args:
            tokens: Tokens to convert

        Returns:
            SQL string
        """
        if not tokens:
            return ""

        result_parts = []
        prev_non_comment_token = None

        for token in tokens:
            # Skip comments (they're not part of executable SQL)
            if token.type == TokenType.COMMENT:
                continue

            # Add spacing between tokens (use last non-comment token)
            if prev_non_comment_token and self._needs_space_between(prev_non_comment_token, token):
                result_parts.append(" ")

            result_parts.append(token.text)
            prev_non_comment_token = token

        return "".join(result_parts)

    def _needs_space_between(self, prev_token: Token, current_token: Token) -> bool:
        """Check if space is needed between tokens.

        Args:
            prev_token: Previous token
            current_token: Current token

        Returns:
            True if space should be inserted
        """
        # Special cases where no space is needed

        # Space before opening parenthesis after certain keywords (WHEN, IF, WHILE, etc.)
        # No space for function/procedure calls
        if current_token.text == "(":
            if prev_token.type == TokenType.KEYWORD:
                # Add space after control flow keywords
                if prev_token.text.upper() in ("WHEN", "IF", "WHILE", "FOR", "WITH"):
                    return True
                # No space for other keywords (function names treated as identifiers)
                return False
            elif prev_token.type == TokenType.IDENTIFIER:
                # No space for function calls
                return False

        # No space after opening parenthesis
        if prev_token.text == "(":
            return False

        # No space before closing parenthesis, comma, semicolon
        if current_token.text in (")", ",", ";"):
            return False

        # After ')', require a space before the next token unless it is another
        # closer/delimiter or a dot (e.g. VARCHAR2(100) PRIMARY, foo(x) TABLESPACE).
        # PRIMARY/TABLESPACE are often IDENTIFIER tokens, not KEYWORD, so the
        # keyword/identifier pairing rules alone do not insert a space.
        if prev_token.text == ")" and current_token.text not in (")", ",", ";", "."):
            return True

        # Space after comma
        if prev_token.text == ",":
            return True

        # No space before or after period (for schema.table)
        if prev_token.text == "." or current_token.text == ".":
            return False

        # No space before or after slash delimiters or path separators, but
        # preserve original whitespace before ordinary slash symbols such as
        # SQL*Plus paths: SPOOL /tmp/out.log.
        if prev_token.text == "/" or current_token.text == "/":
            if (prev_token.type == TokenType.DELIMITER and prev_token.text == "/") or (
                current_token.type == TokenType.DELIMITER and current_token.text == "/"
            ):
                return False
            if current_token.text == "/":
                return current_token.pos > prev_token.pos + len(prev_token.text)
            return False

        # No space around equals (for ENGINE=InnoDB, CHARSET=utf8, etc.)
        if current_token.text == "=" or prev_token.text == "=":
            return False

        # String-literal prefixes must stay adjacent to the opening quote:
        # T-SQL / standard N'str', PostgreSQL E'escape', etc. (not N 'str').
        if current_token.type == TokenType.STRING and prev_token.text.upper() in (
            "N",
            "E",
            "X",
            "B",
        ):
            return False

        # Whenever a symbol is involved, reproduce the author's spacing exactly.
        #
        # Engines lex operators greedily out of runs of operator characters, so
        # both directions change meaning. Dropping a space merges two operators
        # into one: ``a - -b`` rendered as ``a --b`` makes the rest of the line
        # a comment. Adding one splits a single operator in two: ``j @> x``
        # rendered as ``j @ > x`` is a different expression. Neither is a syntax
        # error the database will reject on the user's behalf.
        if TokenType.SYMBOL in (prev_token.type, current_token.type):
            return current_token.pos > prev_token.pos + len(prev_token.text)

        # Need space between keywords/identifiers
        if prev_token.type in (TokenType.KEYWORD, TokenType.IDENTIFIER):
            if current_token.type in (TokenType.KEYWORD, TokenType.IDENTIFIER):
                return True

        # Need space between keyword and string
        if prev_token.type == TokenType.KEYWORD and current_token.type == TokenType.STRING:
            return True

        # Need space between identifier and string
        if prev_token.type == TokenType.IDENTIFIER and current_token.type == TokenType.STRING:
            return True

        # Need space between string and keyword
        if prev_token.type == TokenType.STRING and current_token.type == TokenType.KEYWORD:
            return True

        # Need space between string and identifier
        if prev_token.type == TokenType.STRING and current_token.type == TokenType.IDENTIFIER:
            return True

        # Need space between numbers/symbols and keywords
        if current_token.type == TokenType.KEYWORD:
            return True

        # Default: add space if prev was keyword or identifier
        if prev_token.type in (TokenType.KEYWORD, TokenType.IDENTIFIER):
            return True

        return False

    def _last_token_is(self, keyword: str, parens_depth: Optional[int] = None) -> bool:
        """Check if the last token matches the given keyword.

        Args:
            keyword: Keyword to check
            parens_depth: If provided, only check tokens at this parens depth

        Returns:
            True if last token matches
        """
        for token in reversed(self.context.tokens):
            # Skip comments
            if token.type == TokenType.COMMENT:
                continue

            # Check parens depth if specified
            if parens_depth is not None and token.parens_depth != parens_depth:
                continue

            # Check if it's a keyword token with matching text
            if token.type == TokenType.KEYWORD:
                return token.text.upper() == keyword.upper()

            # Stop at first non-comment token
            break

        return False

    def _peek_next_token(self, skip_comments: bool = True) -> Optional[Token]:
        """Peek at the next token without consuming it.

        Args:
            skip_comments: If True, skip comment tokens

        Returns:
            Next token or None if no more tokens
        """
        idx = self.current_idx + 1
        while idx < len(self.tokens):
            token = self.tokens[idx]
            if not skip_comments or token.type != TokenType.COMMENT:
                return token
            idx += 1

        return None

    def _get_previous_tokens(self, count: int = 1) -> List[Token]:
        """Get previous n non-comment tokens.

        Args:
            count: Number of tokens to retrieve

        Returns:
            List of previous tokens (most recent last)
        """
        result: List[Token] = []
        for token in reversed(self.context.tokens):
            if token.type != TokenType.COMMENT:
                result.insert(0, token)
                if len(result) >= count:
                    break

        return result
