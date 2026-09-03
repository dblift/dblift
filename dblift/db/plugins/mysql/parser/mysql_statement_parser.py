"""MySQL-specific statement parser.

This module provides MySQL-specific statement parsing including
DELIMITER handling, CASE expression detection, and parens depth awareness.
"""

from typing import List, Optional

from dblift.core.sql_parser.base_statement_parser import BaseStatementParser
from dblift.core.sql_parser.parser_context import ParserContext
from dblift.core.sql_parser.tokens import Token, TokenType


class MySQLStatementParser(BaseStatementParser):
    """MySQL-specific statement parser.

    Handles MySQL-specific features:
    - DELIMITER statement (changes statement terminator)
    - CASE expression vs CASE statement disambiguation
    - Parens depth awareness (for CASE in SELECT)
    - Stored procedures, functions, events, triggers
    """

    def __init__(self, tokens: List[Token], context: Optional[ParserContext] = None):
        """Initialize MySQL statement parser.

        Args:
            tokens: List of tokens to parse
            context: Parser context
        """
        super().__init__(tokens, context)
        self.in_stored_program = False

    def _statement_sql_from_tokens(self, tokens: List[Token]) -> str:
        """Reconstruct SQL for execution: drop trailing statement terminator.

        Custom MySQL terminators (``$$``, ``//``, etc.) are for mysql-cli/IDEs;
        the driver ``execute`` expects the statement body without them. A trailing ``;``
        is also omitted; single-statement batches do not require it.
        """
        trimmed = list(tokens)
        while trimmed and trimmed[-1].type == TokenType.DELIMITER:
            trimmed.pop()
        return self._tokens_to_string(trimmed)

    def split_statements(self) -> List[str]:
        """Override to handle NEW_DELIMITER tokens.

        NEW_DELIMITER tokens change the delimiter but shouldn't be
        included in the output statements.

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

            # Handle NEW_DELIMITER specially - adjust context but don't add to statement
            if token.type == TokenType.NEW_DELIMITER:
                self._adjust_delimiter(token)
                # If we have accumulated tokens, emit them as a statement
                # (This handles "DELIMITER ;" acting as a statement boundary)
                if current_statement_tokens:
                    stmt_text = self._statement_sql_from_tokens(current_statement_tokens)
                    if stmt_text.strip():
                        statements.append(stmt_text)
                    current_statement_tokens = []
                continue

            # Adjust context based on token
            self._adjust_context(token)

            # Add token to current statement
            current_statement_tokens.append(token)

            # Check if this marks end of statement
            if self._is_statement_end(token):
                stmt_text = self._statement_sql_from_tokens(current_statement_tokens)
                if stmt_text.strip():
                    statements.append(stmt_text)
                # Reset for next statement
                current_statement_tokens = []
                # Reset parser context (but preserve delimiter - MySQL DELIMITER persists)
                self.context.reset_for_new_statement()
                # Reset MySQL-specific parser flags
                self.in_stored_program = False

        # Handle any remaining tokens
        if current_statement_tokens:
            stmt_text = self._statement_sql_from_tokens(current_statement_tokens)
            if stmt_text.strip():
                statements.append(stmt_text)

        return statements

    def _adjust_context(self, token: Token) -> None:
        """Override to handle token processing.

        Args:
            token: Current token being processed
        """
        super()._adjust_context(token)

    def _adjust_delimiter(self, token: Token) -> None:
        """Adjust delimiter based on DELIMITER statement.

        In MySQL, DELIMITER statement changes the terminator
        and persists across statements.

        Args:
            token: Token that may change delimiter
        """
        if token.type == TokenType.NEW_DELIMITER:
            # Update context delimiter
            self.context.delimiter = token.text

    def _is_statement_end(self, token: Token) -> bool:
        """Check if token marks statement end.

        Args:
            token: Token to check

        Returns:
            True if statement end detected
        """
        if token.type != TokenType.DELIMITER:
            return False

        # Check if delimiter matches current delimiter
        if token.text == self.context.delimiter:
            # At block depth 0, delimiter ends statement
            return self.context.block_depth == 0

        return False

    def _adjust_block_depth(self, token: Token) -> None:
        """Adjust block depth for MySQL.

        Handles:
        - BEGIN/END in stored programs
        - CASE expression vs statement
        - Parens depth awareness

        Args:
            token: Keyword token
        """
        keyword = token.text.upper()

        # Only adjust block depth at parens_depth == 0
        # This prevents CASE expressions in SELECT from affecting block depth
        if not self._should_adjust_block_depth(token):
            return

        # Handle stored program detection
        if self._is_stored_program_keyword(keyword):
            self.in_stored_program = True

        # Handle BEGIN in stored programs
        if keyword == "BEGIN" and self.in_stored_program:
            self.context.increase_block_depth(keyword)

        # Handle CASE
        elif keyword == "CASE":
            # CASE is tricky: can be expression or statement
            # Only increase block depth if not preceded by END (i.e., not END CASE)
            if not self._preceded_by_end():
                self.context.increase_block_depth(keyword)

        # Handle END
        elif keyword == "END":
            if self.context.block_depth > 0:
                # Check if followed by control flow keyword
                next_token = self._peek_next_token()
                if next_token and next_token.type == TokenType.KEYWORD:
                    next_keyword = next_token.text.upper()
                    # END IF, END LOOP, END REPEAT, END WHILE don't close blocks
                    if next_keyword not in ("IF", "LOOP", "REPEAT", "WHILE"):
                        self.context.decrease_block_depth()
                else:
                    # END without following keyword closes block
                    self.context.decrease_block_depth()

    def _should_adjust_block_depth(self, token: Token) -> bool:
        """Check if block depth should be adjusted for this token.

        In MySQL, we only adjust block depth at parens_depth == 0
        to avoid CASE expressions in SELECT affecting block structure.

        Args:
            token: Token to check

        Returns:
            True if block depth should be adjusted
        """
        return token.parens_depth == 0

    def _is_stored_program_keyword(self, keyword: str) -> bool:
        """Check if keyword indicates a stored program.

        Args:
            keyword: Keyword to check

        Returns:
            True if stored program keyword
        """
        # Look for CREATE PROCEDURE/FUNCTION/EVENT/TRIGGER pattern
        if keyword in ("PROCEDURE", "FUNCTION", "EVENT", "TRIGGER"):
            # Check if preceded by CREATE
            prev_tokens = self._get_previous_tokens(3)
            for token in prev_tokens:
                if token.type == TokenType.KEYWORD and token.text.upper() == "CREATE":
                    return True

        return False

    def _preceded_by_end(self) -> bool:
        """Check if current token is preceded by END keyword.

        Note: This is called from _adjust_block_depth, which is called
        AFTER the current token is added to context.tokens. So we need
        to look at the second-to-last keyword, not the last one.

        This is needed to correctly detect END CASE (where CASE should
        not increase block depth) vs standalone CASE (which should).

        Returns:
            True if preceded by END
        """
        # Look back through tokens, skipping the current token (last in list)
        token_count = 0
        for token in reversed(self.context.tokens):
            # Skip comments
            if token.type == TokenType.COMMENT:
                continue

            # Skip the first keyword (current token)
            if token.type == TokenType.KEYWORD:
                token_count += 1
                if token_count == 1:
                    continue  # Skip current token
                # Check the previous keyword
                return token.text.upper() == "END"

            # If we hit a non-keyword non-comment, stop
            if token.type not in (TokenType.COMMENT, TokenType.KEYWORD):
                break

        return False
