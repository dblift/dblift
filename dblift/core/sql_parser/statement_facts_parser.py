"""Parser projection of a plugin's statement facts reader."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, List, Optional

from dblift.core.exceptions import (
    ParserNotAvailableError,
    UnsafeStatementSplitError,
    UnsupportedMetaCommandError,
)
from dblift.core.sql_model.base import ParseResult, SqlObject, SqlStatement
from dblift.core.sql_parser.lexical_engine import LexicalEngine
from dblift.core.sql_parser.parser_interface import SqlParserInterface
from dblift.core.sql_parser.statement import Statement

if TYPE_CHECKING:
    from dblift.db.base_quirks import BaseQuirks


class StatementFactsParser(SqlParserInterface):
    """Split with the plugin's lexical spec and read each statement with its facts reader.

    Used for a plugin that declares ``statement_facts_class`` without a parser
    class of its own.
    """

    def __init__(self, quirks: "BaseQuirks"):
        """Bind the plugin's spec and reader; a spec is needed to split scripts."""
        spec = quirks.lexical_spec()
        if spec is None:
            raise ParserNotAvailableError(
                f"{quirks.dialect_name}: a statement facts reader needs lexical_spec() "
                "to split scripts"
            )
        self._dialect = quirks.dialect_name
        self._engine = LexicalEngine(spec)
        self._reader = quirks.statement_facts_reader()

    @property
    def dialect_name(self) -> str:
        """Return the plugin dialect name."""
        return self._dialect

    def split(self, sql_content: str) -> List[Statement]:
        """Return source-positioned lexical statement records."""
        return self._engine.split(sql_content)

    def split_statements(self, sql_content: str, strict_tokenizer: bool = False) -> List[str]:
        """Return execution text from the shared lexical engine."""
        return self._engine.split_statements(sql_content)

    def split_for_analysis(self, sql_content: str, strict_tokenizer: bool = False) -> List[str]:
        """Return the analysis text of each statement the scanner finds."""
        return self._engine.split_for_analysis(sql_content)

    def split_for_extraction(self, sql_content: str, strict_tokenizer: bool = False) -> List[str]:
        """Return the same scanner-selected constituents as analysis."""
        return self.split_for_analysis(sql_content, strict_tokenizer)

    def parse_sql(self, sql_content: str, default_schema: Optional[str] = None) -> ParseResult:
        """Project facts into statements, refusing an unsafe script as a whole."""
        if not isinstance(sql_content, str):
            raise TypeError(f"sql_content must be a string, got {type(sql_content).__name__}")
        try:
            fragments = self.split_for_analysis(sql_content)
        except (UnsafeStatementSplitError, UnsupportedMetaCommandError) as exc:
            return ParseResult(False, [], [f"Error splitting SQL: {exc}"])
        statements: List[SqlStatement] = []
        errors: List[str] = []
        for sql in fragments:
            facts = self._reader.read(sql)
            objects = [
                obj.as_sql_object(default_schema, self._dialect) for obj in facts.affected_objects
            ]
            statements.append(
                SqlStatement(sql, facts.kind, objects, objects, self._dialect, default_schema)
            )
            if facts.error:
                errors.append(facts.error)
        return ParseResult(not errors, statements, errors)

    def extract_objects(
        self, sql_content: str, default_schema: Optional[str] = None
    ) -> List[SqlObject]:
        """Return identities of changed objects from statement facts."""
        return [
            obj.as_sql_object(default_schema, self._dialect)
            for sql in self.split_for_analysis(sql_content)
            for obj in self._reader.read(sql).affected_objects
        ]

    def validate_sql(self, sql_content: str) -> Dict[str, Any]:
        """Report whether every selected statement has readable facts."""
        result = self.parse_sql(sql_content)
        return {
            "valid": result.success,
            "statements_found": len(result.statements or []),
            "errors": result.errors,
        }
