"""MySQL-specific tokenizer.

This module provides MySQL-specific tokenization including DELIMITER statements,
backtick identifiers, backslash escapes, and comment directives.
"""

from typing import Optional

from dblift.core.sql_parser.base_tokenizer import BaseTokenizer
from dblift.core.sql_parser.tokens import Token, TokenType


class MySQLTokenizer(BaseTokenizer):
    """MySQL-specific tokenizer.

    Handles MySQL-specific features:
    - DELIMITER statement
    - Backtick identifiers
    - Backslash escapes in strings
    - Comment directives (/*!50001 ... */)
    - Hash (#) comments
    - Double-quoted strings (if ANSI_QUOTES not set)
    """

    dialect_name = "mysql"  # lint: allow-dialect-string: dialect dispatch

    def __init__(self, sql: str, strict_unknown_chars: bool = False):
        """Initialize MySQL tokenizer.

        Args:
            sql: SQL content to tokenize
            strict_unknown_chars: If True, unknown characters fail tokenization.
        """
        super().__init__(sql, strict_unknown_chars=strict_unknown_chars)
        self.current_delimiter = ";"

    def _next_token(self) -> Optional[Token]:
        """Override to capture MySQL user/system variables (``@x``, ``@@var``).

        BaseTokenizer falls through to the unknown-character branch on ``@``,
        silently dropping it. The remainder (e.g. ``stmt_count``) is then
        emitted as a bare identifier, which corrupts statements like
        ``SET @stmt_count = 0`` or ``SELECT @@global.read_only``.

        We intercept ``@`` here and emit a single IDENTIFIER token covering
        the leading ``@`` (or ``@@``) plus any following identifier characters
        and dot-qualified scope (``@@global.read_only``).
        """
        self._skip_whitespace()
        if self.pos < len(self.sql) and self.peek() == "@":
            return self._handle_user_variable()
        return super()._next_token()

    def _handle_user_variable(self) -> Token:
        """Read ``@var``, ``@@var``, ``@@scope.var`` as a single IDENTIFIER."""
        start_pos = self.pos
        start_line = self.line
        start_col = self.col

        text = self.read()  # leading '@'
        if self.pos < len(self.sql) and self.peek() == "@":
            text += self.read()  # second '@' for @@global etc.

        while self.pos < len(self.sql):
            char = self.peek()
            if char.isalnum() or char in ("_", "$", ".", "#"):
                text += self.read()
            else:
                break

        return Token(
            TokenType.IDENTIFIER,
            text,
            start_pos,
            start_line,
            start_col,
            self.parens_depth,
        )

    def _is_comment_start(self) -> bool:
        """Check for MySQL comment starts including hash.

        Returns:
            True if comment start detected
        """
        char = self.peek()

        # Check for -- comment
        if self.peek(2) == "--":
            return True

        # Check for /* comment or /*!version directive
        if self.peek(2) == "/*":
            return True

        # Check for # comment
        if char == "#":
            return True

        return False

    def _handle_comment(self) -> Token:
        """Handle MySQL comments including comment directives.

        Returns:
            Comment or comment directive token
        """
        start_pos = self.pos
        start_line = self.line
        start_col = self.col

        # Check for comment directive /*!version ... */
        if self.peek(3) == "/*!":
            return self._handle_comment_directive()

        # Check for # comment
        if self.peek() == "#":
            self.read()  # #
            while self.pos < len(self.sql) and self.peek() not in ("\n", "\r"):
                self.read()
            return Token(
                TokenType.COMMENT,
                "",
                start_pos,
                start_line,
                start_col,
                self.parens_depth,
            )

        # Regular comments
        return super()._handle_comment()

    def _handle_comment_directive(self) -> Token:
        """Handle MySQL comment directives: /*!50001 ... */.

        Comment directives are conditional code that executes
        if MySQL version >= specified version.

        Returns:
            Comment directive token
        """
        start_pos = self.pos
        start_line = self.line
        start_col = self.col

        # Accumulate the full directive text
        directive_text = ""
        directive_text += self.read(3)  # /*!

        # Check for version number (5 digits)
        if self.peek().isdigit():
            # Read version number
            version = ""
            for _ in range(5):
                if self.pos < len(self.sql) and self.peek().isdigit():
                    char = self.read()
                    version += char
                    directive_text += char
                else:
                    break

            # Read until */
            while self.pos < len(self.sql):
                if self.peek(2) == "*/":
                    directive_text += self.read(2)
                    break
                directive_text += self.read()

            # Comment directives are treated as executable code
            return Token(
                TokenType.COMMENT_DIRECTIVE,
                directive_text,
                start_pos,
                start_line,
                start_col,
                self.parens_depth,
            )

        # No version - still a comment directive (executable code)
        # MySQL executes /*!  */ directives even without version numbers
        while self.pos < len(self.sql):
            if self.peek(2) == "*/":
                directive_text += self.read(2)
                break
            directive_text += self.read()

        # Non-versioned comment directives are also executable code
        return Token(
            TokenType.COMMENT_DIRECTIVE,
            directive_text,
            start_pos,
            start_line,
            start_col,
            self.parens_depth,
        )

    def _is_alternative_string_start(self) -> bool:
        """Check for double-quoted strings and backtick identifiers (MySQL specific).

        In MySQL, double quotes can be strings unless ANSI_QUOTES is set.
        Backticks are always identifiers.

        Returns:
            True if double-quote string or backtick identifier detected
        """
        char = self.peek()
        return char == '"' or char == "`"

    def _handle_string(self) -> Token:
        """Handle MySQL string literals with backslash escapes.

        Returns:
            String token
        """
        # Check for backtick identifier (not a string)
        if self.peek() == "`":
            return self._handle_backtick_identifier()

        # Check for double-quoted string
        if self.peek() == '"':
            return self._handle_double_quoted_string()

        # Handle single-quoted string with backslash escapes
        return self._handle_single_quoted_string()

    def _handle_single_quoted_string(self) -> Token:
        """Handle single-quoted string with backslash escapes.

        Returns:
            String token
        """
        start_pos = self.pos
        start_line = self.line
        start_col = self.col

        # Capture entire string including quotes
        string_text = ""
        quote_char = self.read()  # '
        string_text += quote_char

        while self.pos < len(self.sql):
            char = self.peek()

            # Handle backslash escape
            if char == "\\" and self.pos + 1 < len(self.sql):
                string_text += self.read(2)  # Capture backslash and next character
                continue

            # Handle closing quote
            if char == quote_char:
                # Check for doubled quote (SQL escape: 'O''Reilly')
                if self.peek(2) == quote_char + quote_char:
                    string_text += self.read(2)
                else:
                    string_text += self.read()  # Closing quote
                    break
            else:
                string_text += self.read()

        return Token(
            TokenType.STRING,
            string_text,
            start_pos,
            start_line,
            start_col,
            self.parens_depth,
        )

    def _handle_double_quoted_string(self) -> Token:
        """Handle double-quoted string with backslash escapes.

        Returns:
            String token
        """
        start_pos = self.pos
        start_line = self.line
        start_col = self.col

        # Capture entire string including quotes
        string_text = ""
        quote_char = self.read()  # "
        string_text += quote_char

        while self.pos < len(self.sql):
            char = self.peek()

            # Handle backslash escape
            if char == "\\" and self.pos + 1 < len(self.sql):
                string_text += self.read(2)
                continue

            # Handle closing quote
            if char == quote_char:
                if self.peek(2) == quote_char + quote_char:
                    string_text += self.read(2)
                else:
                    string_text += self.read()
                    break
            else:
                string_text += self.read()

        return Token(
            TokenType.STRING,
            string_text,
            start_pos,
            start_line,
            start_col,
            self.parens_depth,
        )

    def _handle_backtick_identifier(self) -> Token:
        """Handle backtick-quoted identifiers.

        Returns:
            Identifier token
        """
        start_pos = self.pos
        start_line = self.line
        start_col = self.col

        # Preserve the full identifier including backticks
        identifier_text = ""
        identifier_text += self.read()  # Opening backtick

        while self.pos < len(self.sql):
            char = self.peek()
            if char == "`":
                # Check for doubled backtick (escape)
                if self.peek(2) == "``":
                    identifier_text += self.read(2)
                else:
                    identifier_text += self.read()  # Closing backtick
                    break
            else:
                identifier_text += self.read()

        return Token(
            TokenType.IDENTIFIER,
            identifier_text,
            start_pos,
            start_line,
            start_col,
            self.parens_depth,
        )

    def _is_symbol(self, char: str) -> bool:
        """Treat ';' as in-body punctuation when a custom DELIMITER is active.

        BaseTokenizer skips unknown characters. With ``DELIMITER $$`` (or ``//``),
        semicolons inside procedures/triggers must remain as tokens; only the
        active client delimiter may end a statement.
        """
        if char == ";":
            return not self._is_delimiter_start()
        return super()._is_symbol(char)

    def _handle_keyword(self) -> Token:
        """Handle keywords including DELIMITER statement.

        Returns:
            Keyword or NEW_DELIMITER token
        """
        # Save position
        saved_pos = self.pos
        saved_line = self.line
        saved_col = self.col

        # Read keyword/identifier without swallowing a trailing custom delimiter
        # (e.g. ``END$$`` must become KEYWORD END + DELIMITER ``$$``, not IDENTIFIER END$$).
        text = ""
        while self.pos < len(self.sql):
            char = self.peek()
            if char.isalnum() or char in ("_", "#"):
                text += self.read()
            elif char == "$":
                dl = self.current_delimiter
                if dl and dl.startswith("$") and self.peek(len(dl)) == dl:
                    break
                text += self.read()
            else:
                break

        token_type = (
            TokenType.KEYWORD if text.upper() in self.SQL_KEYWORDS else TokenType.IDENTIFIER
        )
        token = Token(
            token_type,
            text,
            saved_pos,
            saved_line,
            saved_col,
            self.parens_depth,
        )

        # Check for DELIMITER statement
        if token.text.upper() == "DELIMITER":
            # Skip only horizontal whitespace (spaces/tabs) after DELIMITER keyword
            while self.pos < len(self.sql) and self.peek() in (" ", "\t"):
                self.read()

            # Read only the next contiguous non-whitespace token as the delimiter
            # Stop on ANY whitespace (space, tab, newline, carriage return)
            new_delimiter = ""
            while self.pos < len(self.sql):
                char = self.peek()
                if char in (" ", "\t", "\n", "\r"):
                    break
                new_delimiter += self.read()

            # Validate delimiter is not empty (prevents infinite loop)
            if not new_delimiter:
                # Keep current delimiter if no valid delimiter provided
                new_delimiter = self.current_delimiter

            # Update current delimiter
            self.current_delimiter = new_delimiter

            # Return NEW_DELIMITER token
            return Token(
                TokenType.NEW_DELIMITER,
                new_delimiter,
                saved_pos,
                saved_line,
                saved_col,
                self.parens_depth,
            )

        return token

    def _is_delimiter_start(self) -> bool:
        """Check if current position is the current delimiter.

        Returns:
            True if delimiter detected
        """
        # Check for current delimiter
        peek_len = len(self.current_delimiter)
        return self.peek(peek_len) == self.current_delimiter

    def _handle_delimiter(self) -> Token:
        """Handle delimiter token (respects DELIMITER statement).

        Returns:
            Delimiter token
        """
        start_pos = self.pos
        start_line = self.line
        start_col = self.col

        # Read the current delimiter
        delimiter_text = self.read(len(self.current_delimiter))

        return Token(
            TokenType.DELIMITER,
            delimiter_text,
            start_pos,
            start_line,
            start_col,
            self.parens_depth,
        )
