"""SQL parser factory module."""

import logging
from typing import Any, Dict, List, Optional

from dblift.core.exceptions import ParserNotAvailableError, UnsupportedDialectError
from dblift.core.sql_model.base import ParseResult, SqlObject, SqlStatement
from dblift.core.sql_parser.parser_interface import SqlParserInterface

# Setup logger
logger = logging.getLogger(__name__)


class SqlParserFactory:
    """Factory for creating SQL parsers.

    This factory creates parsers for different SQL dialects, managing shared resources
    and caching parser instances.

    Parser Types:
    - 'regex': Pure regex-based parsing (default, handles all procedural languages)
    - 'hybrid': Combines regex (for splitting) + sqlglot (for pure SQL analysis)
    - 'sqlglot': Pure sqlglot parsing (fails on procedural languages, not recommended)
    """

    # Story 26-9 / 26-4: parser classes are owned by the plugin via
    # ``DialectQuirks.parser_class(parser_type)``. The three legacy
    # ``*_PARSER_MAP`` dicts are gone — adding a new dialect = drop a
    # plugin folder and override ``parser_class`` in its quirks.py.

    def __init__(self, dialect: str, parser_type: str = "hybrid"):
        """Initialize parser factory.

        Args:
            dialect: SQL dialect (oracle, mysql, postgresql, sqlserver, db2)
            parser_type: Parser type ('regex', 'hybrid', 'sqlglot')
        """
        self.dialect = dialect.lower()
        self.parser_type = parser_type.lower()
        self._current_parser: Optional[SqlParserInterface] = None

    @property
    def dialect_name(self) -> str:
        """Return the canonical (lower-cased) dialect name this factory targets."""
        return self.dialect

    def parse_sql(self, sql_content: str, default_schema: Optional[str] = None) -> ParseResult:
        """Parse SQL content into statements using the dialect parser."""
        if self._current_parser is None:
            self._current_parser = self._create_parser()
            if self._current_parser is None:
                return ParseResult(success=False, statements=[], errors=["No parser available"])
        return self._current_parser.parse_sql(sql_content, default_schema)

    def split_statements(self, sql_content: str, strict_tokenizer: bool = False) -> List[str]:
        """Split SQL content into individual statements using the dialect parser."""
        if self._current_parser is None:
            self._current_parser = self._create_parser()
            if self._current_parser is None:
                return []
        return self._current_parser.split_statements(sql_content)

    def validate_sql(self, sql_content: str) -> Dict[str, Any]:
        """Validate SQL syntax using the dialect parser."""
        if self._current_parser is None:
            self._current_parser = self._create_parser()
            if self._current_parser is None:
                return {"success": False, "errors": ["No parser available"]}
        return self._current_parser.validate_sql(sql_content)

    def extract_objects(
        self, sql_content: str, default_schema: Optional[str] = None
    ) -> List[SqlObject]:
        """Extract objects from SQL content using the dialect parser."""
        if self._current_parser is None:
            self._current_parser = self._create_parser()
            if self._current_parser is None:
                return []
        return self._current_parser.extract_objects(sql_content, default_schema)

    def parse(self, sql: str, default_schema: Optional[str] = None) -> SqlStatement:
        """Parse a SQL statement.

        Args:
            sql: SQL statement to parse

        Returns:
            Dictionary containing parse results
        """
        if self._current_parser is None:
            self._current_parser = self._create_parser()
            if self._current_parser is None:
                return SqlStatement(
                    sql_text=sql,
                    statement_type="UNKNOWN",
                    objects=[],
                    affected_objects=[],
                    dialect=None,
                    schema=None,
                )
        return self._current_parser.parse(sql, default_schema)

    def get_affected_objects(
        self, sql: str, default_schema: Optional[str] = None
    ) -> List[SqlObject]:
        """Get objects affected by a SQL statement.

        Args:
            sql: SQL statement to analyze

        Returns:
            List of dictionaries containing object information
        """
        if self._current_parser is None:
            self._current_parser = self._create_parser()
            if self._current_parser is None:
                return []
        return self._current_parser.get_affected_objects(sql, default_schema)

    def get_errors(self) -> List[str]:
        """Get any errors from the last parse operation.

        Returns:
            List of error messages
        """
        if not self._current_parser:
            return []
        if hasattr(self._current_parser, "get_errors"):
            errors = self._current_parser.get_errors()
            if isinstance(errors, list):
                return errors
            return []
        return []

    @property
    def is_valid(self) -> bool:
        """Check if the last parse operation was valid.

        Returns:
            True if valid, False otherwise
        """
        if not self._current_parser:
            return False
        if hasattr(self._current_parser, "is_valid"):
            return bool(self._current_parser.is_valid)
        return False

    @property
    def is_dml(self) -> bool:
        """Check if the last parsed statement is DML.

        Returns:
            True if DML, False otherwise
        """
        if not self._current_parser:
            return False
        if hasattr(self._current_parser, "is_dml"):
            return bool(self._current_parser.is_dml)
        return False

    @property
    def is_query(self) -> bool:
        """Check if the last parsed statement is a query.

        Returns:
            True if query, False otherwise
        """
        if not self._current_parser:
            return False
        if hasattr(self._current_parser, "is_query"):
            return bool(self._current_parser.is_query)
        return False

    @property
    def is_ddl(self) -> bool:
        """Check if the last parsed statement is DDL (delegates to parser if available)."""
        if not self._current_parser:
            return False
        if hasattr(self._current_parser, "is_ddl"):
            return bool(self._current_parser.is_ddl)
        return False

    @staticmethod
    def _resolve_parser(dialect: str, parser_type: str) -> SqlParserInterface:
        """Resolve and instantiate a parser via the plugin's quirks.

        Story 26-9 / 26-4: replaces the three static ``PARSER_MAP`` /
        ``REGEX_PARSER_MAP`` / ``SQLGLOT_PARSER_MAP`` dicts. Adding a
        dialect = override ``parser_class`` in its plugin quirks.py.
        """
        from dblift.db.provider_registry import ProviderRegistry

        quirks = ProviderRegistry.get_quirks((dialect or "").lower())
        try:
            cls = quirks.parser_class(parser_type)
        except Exception as exc:
            logger.error(f"Failed to load {parser_type} parser for {dialect}: {exc}")
            raise ParserNotAvailableError(
                f"No {parser_type} parser available for dialect {dialect}"
            ) from exc
        if cls is None:
            raise UnsupportedDialectError(f"Unsupported dialect: {dialect}")
        # ``HybridParser`` and ``SqlGlotParser`` require a dialect arg;
        # other parsers (regex parsers) take no args.
        if cls.__name__ in ("SqlGlotParser", "HybridParser"):
            return cls(dialect=(dialect or "").lower())  # type: ignore[no-any-return]
        return cls()  # type: ignore[no-any-return]

    def _create_parser(self) -> SqlParserInterface:
        return self._resolve_parser(self.dialect, self.parser_type)

    def get_parser(self, dialect: Optional[str] = None) -> SqlParserInterface:
        """Return a parser instance for the given dialect (or self.dialect if not provided)."""
        target = dialect if dialect is not None else self.dialect
        return self._resolve_parser(target, self.parser_type)
