"""SQL parser factory module."""

from typing import Any, Dict, List, Optional

from dblift.core.exceptions import UnsupportedDialectError
from dblift.core.sql_model.base import ParseResult, SqlObject, SqlStatement
from dblift.core.sql_parser._deprecation import internal_parser_construction, warn_direct_parser
from dblift.core.sql_parser.parser_interface import SqlParserInterface
from dblift.core.sql_parser.statement_facts_parser import StatementFactsParser


class SqlParserFactory:
    """Factory for creating SQL parsers.

    This factory creates parsers for different SQL dialects, managing shared resources
    and caching parser instances.

    Every SQL dialect is served the same parser: its lexical spec splits, its statement facts
    read. ``parser_type`` is accepted and ignored.
    """

    def __init__(self, dialect: str, parser_type: Optional[str] = None):
        """Initialize parser factory.

        Args:
            dialect: SQL dialect (oracle, mysql, postgresql, sqlserver, db2)
            parser_type: Deprecated and ignored
        """
        warn_direct_parser("parser_type" if parser_type is not None else "SqlParserFactory")
        self.dialect = dialect.lower()
        self.parser_type = (parser_type or "hybrid").lower()
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

    def split_statements(self, sql_content: str) -> List[str]:
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
                return {"valid": False, "errors": ["No parser available"]}
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
    @internal_parser_construction()
    def _resolve_parser(dialect: str, parser_type: str) -> SqlParserInterface:
        """The facts parser of *dialect*; ``parser_type`` no longer selects anything.

        A plugin may name a facts-parser subclass through ``quirks.parser_class``; otherwise the
        parser is built from its facts reader and lexical spec. A dialect that reads no statement
        facts has no parser.
        """
        from dblift.db.provider_registry import ProviderRegistry

        quirks = ProviderRegistry.get_quirks((dialect or "").lower())
        if not quirks.supports_statement_facts:
            raise UnsupportedDialectError(f"Unsupported dialect: {dialect}")
        cls = quirks.parser_class(parser_type)
        if cls is not None and issubclass(cls, StatementFactsParser):
            return cls()  # type: ignore[call-arg, no-any-return]
        return StatementFactsParser(quirks)

    def _create_parser(self) -> SqlParserInterface:
        return self._resolve_parser(self.dialect, self.parser_type)

    def get_parser(self, dialect: Optional[str] = None) -> SqlParserInterface:
        """Return a parser instance for the given dialect (or self.dialect if not provided)."""
        target = dialect if dialect is not None else self.dialect
        return self._resolve_parser(target, self.parser_type)
