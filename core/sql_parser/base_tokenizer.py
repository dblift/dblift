"""Base tokenizer for SQL parsing.

This module provides a streaming character-by-character tokenizer
that can be extended for dialect-specific behavior.
"""

import warnings
from typing import List, Optional

from core.sql_parser.tokens import Token, TokenType


class TokenizerWarning(UserWarning):
    """Emitted when ``_handle_unknown_char`` meets a character no rule claims.

    The character itself is preserved verbatim (see ``_handle_unknown_char``);
    the warning exists so the *gap in the dialect's rules* stays visible and
    gets closed, rather than being discovered later as odd tokenization. Tests
    can promote this warning to an error, and the structural test
    ``tests/unit/test_tokenizer_alphabet_coverage.py`` does exactly that.
    """


class TokenizerError(ValueError):
    """Raised when strict tokenization encounters an unknown character."""


class BaseTokenizer:
    """Base tokenizer using streaming character-by-character parsing.

    This tokenizer reads SQL content character by character, building tokens
    and tracking position, line numbers, and parentheses depth.

    Subclasses should override specific handler methods for dialect-specific
    behavior (e.g., Q-quotes for Oracle, dollar quotes for PostgreSQL).
    """

    # SQL keywords that should be recognized
    SQL_KEYWORDS = {
        "SELECT",
        "FROM",
        "WHERE",
        "INSERT",
        "UPDATE",
        "DELETE",
        "CREATE",
        "DROP",
        "ALTER",
        "TABLE",
        "INDEX",
        "VIEW",
        "PROCEDURE",
        "FUNCTION",
        "TRIGGER",
        "PACKAGE",
        "BEGIN",
        "END",
        "IF",
        "THEN",
        "ELSE",
        "LOOP",
        "WHILE",
        "FOR",
        "CASE",
        "WHEN",
        "DECLARE",
        "AS",
        "IS",
        "OR",
        "AND",
        "NOT",
        "NULL",
        "REPLACE",
        "BODY",
        "WRAPPED",
        "GO",
        "DELIMITER",
        "DEFINER",
        "EVENT",
        "RETURNS",
        "LANGUAGE",
        "ATOMIC",
        "COPY",
        "STDIN",
        "TRANSACTION",
        "TRAN",
        "CONVERSATION",
        "DIALOG",
        "DISTRIBUTED",
        "COMPOUND",
        "EDITIONABLE",
        "NONEDITIONABLE",
        "JAVA",
        "SOURCE",
        "EACH",
        "STATEMENT",
        "TYPE",
    }

    #: Characters emitted as standalone SYMBOL tokens.
    #:
    #: Punctuation (``().,[]{}:``) plus the operator characters SQL engines
    #: build their operator names from. PostgreSQL composes multi-character
    #: operators out of ``+-*/<>=~!@#%^&|?`` — ``@>``, ``#>>``, ``?|``, ``&&``
    #: and the rest of the jsonb/hstore/array family are ordinary SQL, and
    #: ``%``, ``&``, ``^``, ``#`` are modulo and bitwise operators in most
    #: engines. A character missing from this set is not rejected, but it does
    #: reach ``_handle_unknown_char`` and warn, so keep the set complete.
    #:
    #: Backtick is deliberately absent: it delimits identifiers in MySQL, which
    #: claims it before the symbol check. Subclasses narrow this set when a
    #: character is punctuation for them rather than an operator.
    SYMBOL_CHARS = "().,+-*/<>=!?[]{}:|~%&^#@"

    #: Identifies the dialect for diagnostic messages emitted by
    #: ``_handle_unknown_char``. Subclasses set this to a short label
    #: (``"mysql"``, ``"oracle"``, ...) so warnings/errors are searchable.
    dialect_name: str = "sql"

    def __init__(self, sql: str, strict_unknown_chars: bool = False):
        """Initialize the tokenizer.

        Args:
            sql: SQL content to tokenize
            strict_unknown_chars: If True, unknown characters raise
                TokenizerError instead of being warned and skipped.
        """
        self.sql = sql
        self.strict_unknown_chars = strict_unknown_chars
        self.pos = 0
        self.line = 1
        self.col = 1
        self.parens_depth = 0

    def tokenize(self) -> List[Token]:
        """Main tokenization loop.

        Returns:
            List of tokens extracted from the SQL content
        """
        tokens = []
        while self.pos < len(self.sql):
            token = self._next_token()
            if token:
                tokens.append(token)
        return tokens

    def _next_token(self) -> Optional[Token]:
        """Get the next token from the input.

        Returns:
            Next token or None if no more tokens
        """
        self._skip_whitespace()

        if self.pos >= len(self.sql):
            return Token(TokenType.EOF, "", self.pos, self.line, self.col, self.parens_depth)

        char = self.peek()

        # Check for various token types
        if self._is_comment_start():
            return self._handle_comment()
        elif self._is_string_start():
            return self._handle_string()
        elif self._is_delimiter_start():
            return self._handle_delimiter()
        elif self._is_symbol(char):
            return self._handle_symbol()
        elif self._is_keyword_start():
            return self._handle_keyword()
        elif char.isdigit() or (char == "." and self.peek(2)[1:2].isdigit()):
            return self._handle_number()
        else:
            return self._handle_unknown_char(char)

    def _handle_unknown_char(self, char: str) -> Optional[Token]:
        """Handle a character that no dialect rule claimed — by preserving it.

        The token stream produced here is reserialized by
        ``BaseStatementParser._tokens_to_string`` into the text that is
        actually sent to the database. Discarding a character therefore
        rewrites the user's SQL, and a rewritten statement is frequently
        still *valid* — ``SELECT a % b`` without the ``%`` reads as
        ``SELECT a AS b`` — so the migration succeeds and writes wrong data
        with nothing to catch it.

        A tokenizer that does not understand a character has no business
        deleting it. Emitting it verbatim keeps the database the authority on
        what is valid SQL: the next gap in the rules surfaces as a database
        error or as a statement that simply works, never as silent corruption.

        The ``TokenizerWarning`` is still raised — the character is safe, but
        the gap in the dialect's rules is a defect worth fixing — and
        ``strict_unknown_chars`` still escalates it, which is how
        ``core/sql_validator`` reports such gaps as findings.

        Returns:
            A SYMBOL token holding the character unchanged.
        """
        message = (
            f"Tokenizer ({self.dialect_name}) found unclaimed character "
            f"{char!r} at line {self.line}, col {self.col}; "
            f"passing it through verbatim"
        )
        if self.strict_unknown_chars:
            raise TokenizerError(message)
        warnings.warn(message, TokenizerWarning, stacklevel=2)

        start_pos = self.pos
        start_line = self.line
        start_col = self.col
        text = self.read()
        return Token(TokenType.SYMBOL, text, start_pos, start_line, start_col, self.parens_depth)

    def peek(self, n: int = 1) -> str:
        """Look ahead n characters without consuming them.

        Args:
            n: Number of characters to peek

        Returns:
            The next n characters or empty string if at end
        """
        return self.sql[self.pos : self.pos + n]

    def read(self, n: int = 1) -> str:
        """Read and consume n characters.

        Args:
            n: Number of characters to read

        Returns:
            The consumed characters
        """
        result = self.sql[self.pos : self.pos + n]
        for char in result:
            if char == "\n":
                self.line += 1
                self.col = 1
            else:
                self.col += 1
            self.pos += 1
        return result

    def _skip_whitespace(self) -> None:
        """Skip whitespace characters."""
        while self.pos < len(self.sql) and self.sql[self.pos].isspace():
            self.read()

    def _is_comment_start(self) -> bool:
        """Check if current position starts a comment.

        Returns:
            True if comment start is detected
        """
        peek2 = self.peek(2)
        return peek2 == "--" or peek2 == "/*"

    def _is_string_start(self) -> bool:
        """Check if current position starts a string literal.

        Returns:
            True if string start is detected
        """
        char = self.peek()
        return char == "'" or self._is_alternative_string_start()

    def _is_alternative_string_start(self) -> bool:
        """Check for dialect-specific string literals (override in subclasses).

        Returns:
            True if alternative string literal is detected
        """
        return False

    def _is_delimiter_start(self) -> bool:
        """Check if current position is a statement delimiter.

        Returns:
            True if delimiter is detected
        """
        char = self.peek()
        return char == ";"

    def _is_symbol(self, char: str) -> bool:
        """Check if character is a symbol (parentheses, operators, etc.).

        Args:
            char: Character to check

        Returns:
            True if character is a symbol
        """
        return char in self.SYMBOL_CHARS

    def _is_keyword_start(self) -> bool:
        """Check if current position starts a keyword or identifier.

        Returns:
            True if keyword/identifier start is detected
        """
        char = self.peek()
        return char.isalpha() or char == "_"

    def _handle_number(self) -> Token:
        """Handle numeric literals.

        Returns:
            Identifier token containing the number
        """
        start_pos = self.pos
        start_line = self.line
        start_col = self.col

        number_text = ""

        # Read digits and decimal points
        while self.pos < len(self.sql):
            char = self.peek()
            if char.isdigit() or char == ".":
                number_text += self.read()
            elif char.upper() == "E":  # Scientific notation
                number_text += self.read()
                # Handle optional +/- after E
                if self.peek() in ["+", "-"]:
                    number_text += self.read()
            else:
                break

        return Token(
            TokenType.IDENTIFIER,  # Treat numbers as identifiers for simplicity
            number_text,
            start_pos,
            start_line,
            start_col,
            self.parens_depth,
        )

    def _handle_comment(self) -> Token:
        """Handle comment tokens.

        Returns:
            Comment token
        """
        start_pos = self.pos
        start_line = self.line
        start_col = self.col

        peek2 = self.peek(2)
        if peek2 == "--":
            # Single-line comment
            self.read(2)
            while self.pos < len(self.sql) and self.peek() != "\n":
                self.read()
            return Token(
                TokenType.COMMENT,
                "",
                start_pos,
                start_line,
                start_col,
                self.parens_depth,
            )
        elif peek2 == "/*":
            # Multi-line comment
            self.read(2)
            while self.pos < len(self.sql):
                if self.peek(2) == "*/":
                    self.read(2)
                    break
                self.read()
            return Token(
                TokenType.COMMENT,
                "",
                start_pos,
                start_line,
                start_col,
                self.parens_depth,
            )

        return Token(TokenType.COMMENT, "", start_pos, start_line, start_col, self.parens_depth)

    def _handle_string(self) -> Token:
        """Handle string literal tokens.

        Returns:
            String token
        """
        start_pos = self.pos
        start_line = self.line
        start_col = self.col

        # Capture the entire string including quotes
        string_text = ""
        quote_char = self.read()  # ' or "
        string_text += quote_char

        # Read until closing quote
        while self.pos < len(self.sql):
            char = self.peek()
            if char == quote_char:
                # Check for doubled quote (escape in SQL: 'O''Reilly')
                if self.peek(2) == quote_char + quote_char:
                    string_text += self.read(2)  # Skip both quotes
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

    def _handle_delimiter(self) -> Token:
        """Handle delimiter tokens (semicolon, slash, GO).

        Returns:
            Delimiter token
        """
        start_pos = self.pos
        start_line = self.line
        start_col = self.col

        delimiter_text = self.read()  # Read semicolon

        return Token(
            TokenType.DELIMITER,
            delimiter_text,
            start_pos,
            start_line,
            start_col,
            self.parens_depth,
        )

    def _handle_symbol(self) -> Token:
        """Handle symbol tokens (operators, parentheses, etc.).

        Returns:
            Symbol token
        """
        start_pos = self.pos
        start_line = self.line
        start_col = self.col

        char = self.read()

        # Track parentheses depth
        if char == "(":
            self.parens_depth += 1
        elif char == ")":
            self.parens_depth = max(0, self.parens_depth - 1)

        return Token(TokenType.SYMBOL, char, start_pos, start_line, start_col, self.parens_depth)

    def _handle_keyword(self) -> Token:
        """Handle keyword/identifier tokens.

        Returns:
            Keyword or identifier token
        """
        start_pos = self.pos
        start_line = self.line
        start_col = self.col

        # Read the keyword/identifier
        text = ""
        while self.pos < len(self.sql):
            char = self.peek()
            if char.isalnum() or char in ("_", "$", "#"):
                text += self.read()
            else:
                break

        # Check if it's a known keyword
        token_type = (
            TokenType.KEYWORD if text.upper() in self.SQL_KEYWORDS else TokenType.IDENTIFIER
        )

        return Token(token_type, text, start_pos, start_line, start_col, self.parens_depth)

    def _read_until(self, target: str) -> str:
        """Read characters until a target string is found.

        Args:
            target: String to read until

        Returns:
            Characters read (not including target)
        """
        result = ""
        while self.pos < len(self.sql):
            if self.peek(len(target)) == target:
                break
            result += self.read()
        return result
