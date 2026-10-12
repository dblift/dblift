"""SQL Server parser backed by the sqlcmd batch scanner."""

import logging
from typing import Any, Dict, List, Optional, Type

from dblift.core.sql_model.base import (
    ParseResult,
)
from dblift.core.sql_parser.base_tokenizer import BaseTokenizer
from dblift.core.sql_parser.enhanced_regex_parser import EnhancedRegexParser
from dblift.core.sql_parser.statement import Statement, analysis_sql
from dblift.db.plugins.sqlserver.parser._batches import scan_batches
from dblift.db.plugins.sqlserver.parser.parser_config import SqlServerConfig
from dblift.db.plugins.sqlserver.parser.sqlserver_tokenizer import SQLServerTokenizer

logger = logging.getLogger(__name__)


class SqlServerRegexParser(EnhancedRegexParser):
    """Execute sqlcmd batches and analyse their scanner-derived constituents."""

    # Redaction and object comment stripping still use this lexical classifier.
    # Script boundaries come only from _batches.scan_batches.
    tokenizer_class: Type[BaseTokenizer] = SQLServerTokenizer

    SPLITS_WITHOUT_FALLBACK = True

    def __init__(self) -> None:
        """Initialize SQL Server regex parser."""
        super().__init__(SqlServerConfig())  # type: ignore[no-untyped-call,arg-type]
        logger.debug("SQL Server regex parser initialized")

    @property
    def dialect_name(self) -> str:
        """Return the dialect name."""
        return "sqlserver"  # lint: allow-dialect-string: dialect dispatch

    def split(self, sql_content: str) -> List[Statement]:
        """The batches of a script, as ``sqlcmd`` sends them (docs/sql-parsing/sqlserver.md)."""
        return [
            Statement(
                text=batch.text,
                line=batch.line,
                terminator="GO" if batch.terminated else None,
                repeat=batch.repeat,
                analysis_statements=batch.analysis_statements,
            )
            for batch in scan_batches(sql_content)
        ]

    def split_statements(self, sql_content: str, strict_tokenizer: bool = False) -> List[str]:
        """Batches as execution receives them; ``GO n`` returns its batch n times.

        The scanner has no unknown characters, so ``strict_tokenizer`` changes nothing.
        """
        statements: List[str] = []
        for record in self.split(sql_content):
            if record.repeat == 0:
                logger.info(
                    "GO 0 follows the batch starting on line %d: it is not run", record.line
                )
            statements.extend([record.text] * record.repeat)
        return statements

    def split_for_analysis(self, sql_content: str, strict_tokenizer: bool = False) -> List[str]:
        """The executed constituents of each batch, once regardless of GO count."""
        return analysis_sql(self.split(sql_content))

    def split_for_extraction(self, sql_content: str, strict_tokenizer: bool = False) -> List[str]:
        """Object extraction reads the same constituent view as analysis."""
        return self.split_for_analysis(sql_content, strict_tokenizer=strict_tokenizer)

    def parse_sql(self, sql_content: str, default_schema: Optional[str] = None) -> ParseResult:
        """Parse SQL content using SQL Server regex-based approach.

        This method combines the enhanced regex parsing with SQL Server-specific
        intelligent splitting logic.
        """
        logger.debug("[ENTRY] SQL Server parse_sql called")

        # Use SQL Server default schema if none provided
        if default_schema is None:
            default_schema = "dbo"

        # Use the enhanced regex parser's parse_sql method
        return super().parse_sql(sql_content, default_schema)

    def validate_sql(self, sql_content: str) -> Dict[str, Any]:
        """Validate SQL content using SQL Server regex-based validation.

        Args:
            sql_content: SQL content to validate

        Returns:
            Dict with 'valid' (bool), 'statements_found' (int), and 'errors' (list)
        """
        try:
            statements = self.split_for_analysis(sql_content)
            return {"valid": True, "statements_found": len(statements), "errors": []}
        except Exception as e:
            return {"valid": False, "statements_found": 0, "errors": [str(e)]}
