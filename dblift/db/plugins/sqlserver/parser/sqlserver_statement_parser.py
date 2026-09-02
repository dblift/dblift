"""SQL Server-specific statement parser.

This module provides SQL Server-specific statement parsing including
BEGIN TRAN disambiguation and transaction detection.
"""

import re
from typing import List

from dblift.core.sql_parser.base_statement_parser import BaseStatementParser
from dblift.core.sql_parser.tokens import Token, TokenType
from dblift.db.plugins.sqlserver.parser.tsql_batch_separator import is_tsql_batch_separator


class SQLServerStatementParser(BaseStatementParser):
    """SQL Server-specific statement parser.

    Handles SQL Server-specific features:
    - BEGIN TRANSACTION vs BEGIN block
    - BEGIN CONVERSATION, BEGIN DIALOG
    - System stored procedures that can't run in transactions
    - GO batch delimiter
    """

    def split_statements(self) -> List[str]:
        """Split batches; never return a standalone ``GO`` (not executable by the native driver)."""
        statements = super().split_statements()
        return [s for s in statements if not is_tsql_batch_separator(s)]

    # System stored procedures that cannot run in transactions
    NO_TRANSACTION_SPROCS = [
        "SP_ADDSUBSCRIPTION",
        "SP_DROPSUBSCRIPTION",
        "SP_ADDDISTRIBUTOR",
        "SP_DROPDISTRIBUTOR",
        "SP_ADDDISTPUBLISHER",
        "SP_DROPDISTPUBLISHER",
        "SP_ADDLINKEDSERVER",
        "SP_DROPLINKEDSERVER",
        "SP_ADDLINKEDSRVLOGIN",
        "SP_DROPLINKEDSRVLOGIN",
        "SP_SERVEROPTION",
        "SP_REPLICATIONDBOPTION",
        "SP_FULLTEXT_DATABASE",
    ]

    def _adjust_block_depth(self, token: Token) -> None:
        """Adjust block depth for SQL Server.

        Handles:
        - BEGIN blocks
        - BEGIN TRANSACTION (not a block)
        - BEGIN CONVERSATION / DIALOG
        - END blocks

        Args:
            token: Keyword token
        """
        keyword = token.text.upper()

        # Handle BEGIN
        if keyword == "BEGIN":
            # Check if this is a block BEGIN or transaction BEGIN
            next_token = self._peek_next_token()
            if next_token and next_token.type == TokenType.KEYWORD:
                next_keyword = next_token.text.upper()
                # BEGIN TRANSACTION, BEGIN CONVERSATION, BEGIN DIALOG are not blocks
                if self._is_single_statement_begin(next_keyword):
                    # Not a block - don't increase depth
                    pass
                else:
                    # Regular block BEGIN
                    self.context.increase_block_depth(keyword)
            else:
                # BEGIN without following keyword - it's a block
                self.context.increase_block_depth(keyword)

        # Handle END
        elif keyword == "END":
            if self.context.block_depth > 0:
                self.context.decrease_block_depth()

        # Handle keywords after BEGIN
        elif self._last_token_is("BEGIN"):
            if self._is_single_statement_begin(keyword):
                # This was a single-statement BEGIN - decrease depth
                if self.context.block_depth > 0:
                    self.context.decrease_block_depth()

    def _is_single_statement_begin(self, keyword: str) -> bool:
        """Check if keyword indicates single-statement BEGIN.

        Single-statement BEGINs:
        - BEGIN TRANSACTION / BEGIN TRAN
        - BEGIN CONVERSATION
        - BEGIN DIALOG
        - BEGIN DISTRIBUTED TRANSACTION

        Args:
            keyword: Keyword after BEGIN

        Returns:
            True if single-statement BEGIN
        """
        # BEGIN TRANSACTION or BEGIN TRAN
        if keyword in ("TRANSACTION", "TRAN"):
            return True

        # BEGIN CONVERSATION
        if keyword == "CONVERSATION":
            return True

        # BEGIN DIALOG
        if keyword == "DIALOG":
            return True

        # BEGIN DISTRIBUTED TRANSACTION
        if keyword == "DISTRIBUTED":
            # Check if followed by TRANSACTION
            next_token = self._peek_next_token()
            if next_token and next_token.text.upper() in ("TRANSACTION", "TRAN"):
                return True

        return False

    def _is_statement_end(self, token: Token) -> bool:
        """Check if token marks statement end.

        Args:
            token: Token to check

        Returns:
            True if statement end detected
        """
        if token.type == TokenType.DELIMITER:
            # Semicolon or GO at block depth 0 ends statement
            if self.context.block_depth == 0:
                return True

            # GO always ends statements (even inside blocks)
            if token.text.upper() == "GO":
                return True

        return False

    def can_execute_in_transaction(self) -> bool:
        """Check if current statement can execute in a transaction.

        Returns:
            True if statement can run in transaction
        """
        # Reconstruct statement text from tokens
        stmt_text = self._tokens_to_string(self.context.tokens).upper()

        # Check for BACKUP/RESTORE/RECONFIGURE
        if any(keyword in stmt_text for keyword in ["BACKUP", "RESTORE", "RECONFIGURE"]):
            return False

        # Check for system sprocs
        if "EXEC" in stmt_text or "EXECUTE" in stmt_text:
            for sproc in self.NO_TRANSACTION_SPROCS:
                if sproc in stmt_text:
                    return False

        # Check for CREATE/ALTER/DROP DATABASE
        if re.search(r"(CREATE|ALTER|DROP)\s+DATABASE", stmt_text):
            return False

        # Check for CREATE/DROP FULLTEXT
        if "FULLTEXT" in stmt_text:
            return False

        return True
