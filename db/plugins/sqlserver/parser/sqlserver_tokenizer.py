"""SQL Server-specific tokenizer.

This module provides SQL Server-specific tokenization including
GO delimiter and bracket identifiers.
"""

from core.sql_parser.base_tokenizer import BaseTokenizer
from core.sql_parser.tokens import Token, TokenType


class SQLServerTokenizer(BaseTokenizer):
    """SQL Server-specific tokenizer.

    Handles SQL Server-specific features:
    - GO batch delimiter
    - Bracket [identifiers]
    - Double-quoted identifiers (if QUOTED_IDENTIFIER is ON)
    - Parameters and variables: @name, @@ROWCOUNT
    """

    dialect_name = "sqlserver"  # lint: allow-dialect-string: dialect dispatch

    #: ``[``/``]`` delimit identifiers and ``@`` introduces parameters and
    #: system functions; all three are claimed by ``_is_keyword_start`` /
    #: ``_handle_keyword``, which run after the symbol check, so they must not
    #: be symbols here. Everything else in the base set is T-SQL: ``%``, ``&``,
    #: ``^``, ``|``, ``~`` are modulo and the bitwise operators, and ``#``
    #: prefixes temporary table names.
    SYMBOL_CHARS = "".join(c for c in BaseTokenizer.SYMBOL_CHARS if c not in "[]@")

    def _is_keyword_start(self) -> bool:
        """Override to include bracket and double-quote as identifier starts.

        Returns:
            True if keyword/identifier start is detected
        """
        char = self.peek()
        # Include [ for bracketed identifiers, " for quoted identifiers, @ for T-SQL vars
        return char.isalpha() or char == "_" or char == "[" or char == '"' or char == "@"

    def _is_delimiter_start(self) -> bool:
        """Check for SQL Server delimiters (semicolon or GO).

        Returns:
            True if delimiter detected
        """
        char = self.peek()

        # Check for semicolon
        if char == ";":
            return True

        # Check for GO (batch separator). Allowed after GO: whitespace, EOF, or "--" line comment.
        if self.peek(2).upper() == "GO":
            rest = self.sql[self.pos + 2 :]
            if not rest or rest[0].isspace() or rest.startswith("--") or rest[0] == ";":
                return True

        return False

    def _handle_delimiter(self) -> Token:
        """Handle SQL Server delimiters.

        Returns:
            Delimiter token
        """
        start_pos = self.pos
        start_line = self.line
        start_col = self.col

        # Check for GO (must match _is_delimiter_start)
        if self.peek(2).upper() == "GO":
            rest = self.sql[self.pos + 2 :]
            if not rest or rest[0].isspace() or rest.startswith("--") or rest[0] == ";":
                delimiter_text = self.read(2)  # Read GO
                # Optional spaces/tabs then ';' on the same separator line (not newline)
                while self.pos < len(self.sql) and self.sql[self.pos] in " \t":
                    self.read()
                if self.pos < len(self.sql) and self.peek() == ";":
                    self.read()
                return Token(
                    TokenType.DELIMITER,
                    delimiter_text,
                    start_pos,
                    start_line,
                    start_col,
                    self.parens_depth,
                )

        # Regular semicolon delimiter
        delimiter_text = self.read()
        return Token(
            TokenType.DELIMITER,
            delimiter_text,
            start_pos,
            start_line,
            start_col,
            self.parens_depth,
        )

    def _is_string_start(self) -> bool:
        """Check for string literal start.

        Returns:
            True if string start detected
        """
        char = self.peek()

        # Single-quoted strings are standard
        if char == "'":
            return True

        # Double-quoted strings (if QUOTED_IDENTIFIER is OFF)
        # We'll treat them as identifiers by default
        return False

    def _handle_keyword(self) -> Token:
        """Handle keywords and bracket identifiers.

        Returns:
            Keyword or identifier token
        """
        # T-SQL parameters / variables (@p, @@TRANCOUNT)
        if self.peek() == "@":
            return self._handle_tsql_parameter()

        # Check for bracket identifier first
        if self.peek() == "[":
            return self._handle_bracketed_identifier()

        # Check for double-quoted identifier
        if self.peek() == '"':
            return self._handle_quoted_identifier()

        # Regular keyword/identifier
        return super()._handle_keyword()

    def _handle_tsql_parameter(self) -> Token:
        """Handle @parameter and @@system_function names.

        Returns:
            Identifier token including the leading @ (or @@).
        """
        start_pos = self.pos
        start_line = self.line
        start_col = self.col

        text = self.read()  # leading @
        if self.peek() == "@":
            text += self.read()

        while self.pos < len(self.sql):
            char = self.peek()
            if char.isalnum() or char in ("_", "$", "#"):
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

    def _handle_bracketed_identifier(self) -> Token:
        """Handle [bracketed] identifiers.

        Returns:
            Identifier token
        """
        start_pos = self.pos
        start_line = self.line
        start_col = self.col

        identifier_text = self.read()  # Opening bracket [

        # Read until closing bracket
        while self.pos < len(self.sql):
            char = self.peek()
            if char == "]":
                # Check for doubled bracket (escape: [table]]name])
                if self.peek(2) == "]]":
                    identifier_text += self.read(2)
                else:
                    identifier_text += self.read()  # Closing bracket
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

    def _handle_quoted_identifier(self) -> Token:
        """Handle double-quoted identifiers.

        Returns:
            Identifier token
        """
        start_pos = self.pos
        start_line = self.line
        start_col = self.col

        identifier_text = self.read()  # Opening quote

        # Read until closing quote
        while self.pos < len(self.sql):
            char = self.peek()
            if char == '"':
                # Check for doubled quote (escape)
                if self.peek(2) == '""':
                    identifier_text += self.read(2)
                else:
                    identifier_text += self.read()  # Closing quote
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
