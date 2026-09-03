"""Oracle-specific statement parser.

This module provides Oracle-specific statement parsing including
slash delimiter handling, package bodies, and PL/SQL block detection.
"""

from typing import List, Optional

from dblift.core.sql_parser.base_statement_parser import BaseStatementParser
from dblift.core.sql_parser.parser_context import ParserContext
from dblift.core.sql_parser.tokens import Token, TokenType
from dblift.db.plugins.oracle.parser._sqlplus import (
    is_sqlplus_command as _shared_is_sqlplus_command,
)


class OracleStatementParser(BaseStatementParser):
    """Oracle-specific statement parser.

    Handles Oracle-specific features:
    - Dynamic delimiter switching (semicolon vs slash)
    - Package body handling with nested procedures/functions
    - PL/SQL block detection
    - Control flow vs block-terminating END
    - Wrapped PL/SQL blocks
    """

    # Maximum number of keywords to look back when checking for FOR/WHILE
    _MAX_KEYWORD_LOOKBACK = 15

    def __init__(self, tokens: List[Token], context: Optional[ParserContext] = None):
        """Initialize Oracle statement parser.

        Args:
            tokens: List of tokens to parse
            context: Parser context
        """
        super().__init__(tokens, context)
        self.in_plsql_block = False
        self.package_name: Optional[str] = None
        self.in_package = False  # Tracks package bodies, specs, and compound triggers
        self.package_body_depth = 0
        self.in_declaration_section = False  # Between AS/IS and BEGIN
        self._seen_create = False  # Cached flag: True once CREATE is seen in current statement

    def split_statements(self) -> List[str]:
        """Split tokens into statements with Oracle-specific handling.

        Overrides base implementation to:
        1. Reset parser state after each statement
        2. Filter standalone slash delimiters and empty statements

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
                stmt_text = self._tokens_to_string(current_statement_tokens)
                stmt_stripped = stmt_text.strip()

                # Strip leading/trailing slash (SQL*Plus delimiter, not valid Oracle SQL)
                # This handles cases where / is tokenized as SYMBOL instead of DELIMITER
                if stmt_stripped.startswith("/"):
                    stmt_stripped = stmt_stripped[1:].strip()
                if stmt_stripped.endswith("/"):
                    stmt_stripped = stmt_stripped[:-1].strip()

                # Filter out standalone slashes, semicolons, and SQL*Plus commands
                # SQL*Plus commands are not valid Oracle SQL for native execution
                if stmt_stripped and stmt_stripped not in ("/", ";"):
                    if not self._is_sqlplus_command(stmt_stripped):
                        statements.append(stmt_stripped)

                # Reset for next statement
                current_statement_tokens = []
                # Reset parser context
                self.context.reset_for_new_statement()
                # Oracle always resets delimiter to semicolon (unlike MySQL)
                self.context.delimiter = ";"
                # Reset Oracle-specific parser flags
                self.in_plsql_block = False
                self.in_declaration_section = False
                self.in_package = False
                self.package_body_depth = 0
                self.package_name = None
                self._seen_create = False

        # Handle any remaining tokens
        if current_statement_tokens:
            stmt_text = self._tokens_to_string(current_statement_tokens)
            stmt_stripped = stmt_text.strip()

            # Strip leading/trailing slash (SQL*Plus delimiter, not valid Oracle SQL)
            if stmt_stripped.startswith("/"):
                stmt_stripped = stmt_stripped[1:].strip()
            if stmt_stripped.endswith("/"):
                stmt_stripped = stmt_stripped[:-1].strip()

            # Filter out SQL*Plus commands
            if stmt_stripped and stmt_stripped not in ("/", ";"):
                if not self._is_sqlplus_command(stmt_stripped):
                    statements.append(stmt_stripped)

        return statements

    def _is_statement_end(self, token: Token) -> bool:
        """Check if token marks statement end in Oracle.

        In Oracle:
        - For PL/SQL blocks: only slash (/) ends the statement
        - For regular SQL: semicolon (;) ends the statement
        - Semicolons in declaration sections don't end statements

        Args:
            token: Token to check

        Returns:
            True if token marks statement end
        """
        if token.type != TokenType.DELIMITER:
            return False

        # GAP 2 fix: package body (and compound trigger) initialization section support.
        # Flyway: "Package bodies can have an unbalanced BEGIN without END in the
        # initialisation section." When inside a package/compound trigger and the
        # slash delimiter arrives with residual block depth, force-terminate.
        if token.text == "/" and self.in_package and self.context.block_depth > 0:
            while self.context.block_depth > 0:
                self.context.decrease_block_depth()
            return True

        # Only check for statement end at block depth 0
        if self.context.block_depth != 0:
            return False

        # Semicolons in declaration section don't end the statement
        if token.text == ";" and self.in_declaration_section:
            return False

        # Check if this delimiter matches the expected delimiter
        # For PL/SQL blocks, context.delimiter is "/", for regular SQL it's ";"
        if token.text == self.context.delimiter:
            return True

        # No delimiter match - not a statement end
        return False

    def _is_sqlplus_command(self, stmt: str) -> bool:
        """Check if statement is a SQL*Plus command (not valid Oracle SQL for native execution).

        SQL*Plus commands are client-side commands that are interpreted
        by SQL*Plus but are not valid SQL statements that can be
        executed by the native driver. Delegates to
        :func:`dblift.db.plugins.oracle.parser._sqlplus.is_sqlplus_command` —
        PR-E (ADR-0012 §Follow-ups) unified the two corpora so both
        the regex and tokenizer statement paths share a single
        authoritative list. See the ``_sqlplus`` module docstring for
        the full set of recognised directives and the behaviour changes
        this delegation introduces on the tokenizer path.
        """
        return _shared_is_sqlplus_command(stmt)

    def _adjust_delimiter(self, token: Token) -> None:
        """Adjust delimiter based on statement type.

        Oracle uses:
        - Semicolon (;) for regular SQL
        - Slash (/) for PL/SQL blocks

        Args:
            token: Current keyword token
        """
        # GAP 6 fix: skip delimiter adjustment when inside parentheses.
        # Prevents PROCEDURE/FUNCTION in ACCESSIBLE BY (...) from triggering PL/SQL detection.
        if self.context.parens_depth > 0:
            return

        keyword = token.text.upper()

        # Check if we're starting a PL/SQL block
        if self._is_plsql_block_start(keyword):
            self.context.delimiter = "/"
            self.in_plsql_block = True

    def _is_plsql_block_start(self, keyword: str) -> bool:
        """Check if keyword starts a PL/SQL block.

        Args:
            keyword: Keyword to check

        Returns:
            True if keyword starts PL/SQL block
        """
        if keyword in ("DECLARE", "BEGIN"):
            return True

        if keyword in ("PROCEDURE", "FUNCTION", "TRIGGER", "TYPE", "PACKAGE"):
            # Use the cached flag set when CREATE was first encountered in this statement.
            # Handles complex headers (ACCESSIBLE BY clauses) without O(n) rescanning.
            return self._seen_create

        return False

    def _adjust_block_depth(self, token: Token) -> None:
        """Adjust block depth for Oracle PL/SQL.

        Handles:
        - BEGIN/END pairs
        - Control flow keywords (IF, LOOP, CASE)
        - Package bodies with nested procedures/functions
        - Compound triggers (COMPOUND TRIGGER ... END name;)
        - END/END IF/END LOOP/END CASE decrease block depth (keywords after END
          are treated as closers for readability, not as new block starters)

        Args:
            token: Keyword token
        """
        # GAP 6 fix: skip block depth adjustments when inside parentheses.
        # Prevents PROCEDURE/FUNCTION in ACCESSIBLE BY (...) from triggering PL/SQL detection.
        if self.context.parens_depth > 0:
            return

        keyword = token.text.upper()

        # Cache the CREATE keyword so _is_plsql_block_start() can check O(1) instead of O(n).
        if keyword == "CREATE":
            self._seen_create = True
            return

        # GAP 7 fix: COMPOUND TRIGGER – the second TRIGGER keyword (in "COMPOUND TRIGGER")
        # marks the start of the compound trigger body, analogous to PACKAGE BODY ... AS.
        if keyword == "TRIGGER" and self._preceded_by_compound():
            if not self.in_package:
                self.context.increase_block_depth("COMPOUND_TRIGGER")
                self.in_package = True
                self.in_compound_trigger = True
            return

        # Handle control flow keywords
        if keyword in ("IF", "CASE"):
            # Only increase if not preceded by END
            if not self._preceded_by_end():
                self.context.increase_block_depth(keyword)

        # Handle FOR and WHILE loops
        elif keyword in ("FOR", "WHILE"):
            # FOR/WHILE start loop constructs only inside an active BEGIN...END block.
            # Before any BEGIN (e.g. in trigger header "FOR EACH ROW", "FOR INSERT ON"),
            # or in ACCESSIBLE BY clauses, these are not loop starters.
            if self.context.block_depth == 0:
                return

            # Check if FOR is followed by EACH (trigger syntax: "FOR EACH ROW")
            if keyword == "FOR":
                next_token = self._peek_next_token()
                if next_token and next_token.text.upper() == "EACH":
                    return
            self.context.increase_block_depth(keyword)

        # Handle LOOP specially - don't increase depth if preceded by FOR or WHILE
        elif keyword == "LOOP":
            if not self._preceded_by_end() and not self._preceded_by_for_or_while():
                self.context.increase_block_depth(keyword)

        # Handle BEGIN
        elif keyword == "BEGIN":
            # BEGIN marks end of declaration section
            self.in_declaration_section = False
            self.context.increase_block_depth(keyword)
            if self.in_package:
                self.package_body_depth += 1

        # Handle END
        elif keyword == "END":
            # All END keywords decrease block depth (END, END IF, END LOOP, END CASE, etc.)
            if self.context.block_depth > 0:
                self.context.decrease_block_depth()
                if self.in_package:
                    if self.package_body_depth > 0:
                        self.package_body_depth -= 1
                    # Don't clear in_package here: let the slash delimiter handle termination
                    # (supports initialization sections and compound trigger sections).

        # Handle AS/IS for procedures/functions/packages
        elif keyword in ("AS", "IS"):
            # These mark the start of PL/SQL body for CREATE statements, or
            # section bodies inside COMPOUND TRIGGER.
            if self._seen_create:
                # Search all statement tokens for context keywords (not a fixed window —
                # ACCESSIBLE BY clauses can push CREATE many tokens back).
                keywords = [
                    t.text.upper() for t in self.context.tokens if t.type == TokenType.KEYWORD
                ]

                # PACKAGE BODY: increase block depth once to keep entire body together
                if "PACKAGE" in keywords and "BODY" in keywords and not self.in_package:
                    self.context.increase_block_depth("PACKAGE_BODY")
                    self.in_package = True
                # PACKAGE spec
                elif "PACKAGE" in keywords and "BODY" not in keywords and not self.in_package:
                    self.context.increase_block_depth("PACKAGE_SPEC")
                    self.in_package = True
                # Standalone PROCEDURE/FUNCTION/TRIGGER or compound trigger sections
                elif any(kw in keywords for kw in ("PROCEDURE", "FUNCTION", "TRIGGER")):
                    self.in_plsql_block = True
                    self.in_declaration_section = True

    def _preceded_by_compound(self) -> bool:
        """Check if the current TRIGGER token is preceded by the COMPOUND keyword.

        Used to detect the COMPOUND TRIGGER body start pattern.
        Skips IDENTIFIER tokens to handle `CREATE ... COMPOUND TRIGGER my_name`
        where the trigger name sits between COMPOUND and TRIGGER.

        Returns:
            True if the immediately preceding keyword is COMPOUND
        """
        skip_first = True
        for token in reversed(self.context.tokens):
            if token.type in (TokenType.COMMENT, TokenType.IDENTIFIER):
                continue
            if skip_first and token.type == TokenType.KEYWORD:
                skip_first = False
                continue
            if token.type == TokenType.KEYWORD:
                return token.text.upper() == "COMPOUND"
            break
        return False

    def _preceded_by_end(self) -> bool:
        """Check if current token is preceded by END keyword.

        Note: This is called from _adjust_block_depth, which is called
        AFTER the current token is added to context.tokens. So we need
        to look at the second-to-last keyword, not the last one.

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

    def _preceded_by_for_or_while(self) -> bool:
        """Check if current token is preceded by FOR or WHILE keyword.

        This is used to detect FOR...LOOP and WHILE...LOOP constructs.

        Note: This is called AFTER the current token is added to context.tokens,
        so we need to skip the current token when looking back.

        Returns:
            True if preceded by FOR or WHILE
        """
        # Look back through tokens, skipping the current token
        skip_first = True
        keywords_checked = 0  # Track how many keywords we've examined
        for token in reversed(self.context.tokens):
            # Skip comments
            if token.type == TokenType.COMMENT:
                continue

            # Skip the first keyword (current token)
            if skip_first and token.type == TokenType.KEYWORD:
                skip_first = False
                continue

            if token.type == TokenType.KEYWORD:
                keyword = token.text.upper()
                keywords_checked += 1  # Increment counter for each keyword checked

                if keyword in ("FOR", "WHILE"):
                    return True
                # Stop if we hit END, BEGIN, or another major keyword
                # END is important to stop at because LOOP after END is part of "END LOOP"
                if keyword in ("END", "BEGIN", "THEN", "ELSE"):
                    return False

                # Stop if we've looked back far enough
                # (to avoid looking back through the entire statement)
                if keywords_checked > self._MAX_KEYWORD_LOOKBACK:
                    break

        return False

    def _is_control_flow_end(self) -> bool:
        """Check if END is followed by control flow keyword.

        Control flow END patterns:
        - END IF
        - END LOOP
        - END CASE

        Returns:
            True if this is a control flow END
        """
        next_token = self._peek_next_token()
        if next_token and next_token.type == TokenType.KEYWORD:
            keyword = next_token.text.upper()
            if keyword in ("IF", "LOOP", "CASE"):
                return True

        return False
