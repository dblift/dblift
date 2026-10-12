"""Compatibility parser projections of SQLite lexical statements and facts."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from dblift.core.exceptions import UnsafeStatementSplitError, UnsupportedMetaCommandError
from dblift.core.sql_model.base import ParseResult, SqlObject, SqlStatement
from dblift.core.sql_parser.lexical_engine import LexicalEngine
from dblift.core.sql_parser.parser_interface import SqlParserInterface
from dblift.core.sql_parser.statement import Statement
from dblift.core.sql_parser.statement_facts import SqlglotStatementFactsReader
from dblift.db.plugins.sqlite.parser.lexical_spec import SQLITE_SPEC

_FACTS = SqlglotStatementFactsReader("sqlite", SQLITE_SPEC)


class SQLiteFactsParser(SqlParserInterface):
    """Project statement facts into the existing parser result contract."""

    @property
    def dialect_name(self) -> str:
        """Return the plugin dialect name."""
        return "sqlite"

    def split(self, sql_content: str) -> List[Statement]:
        """Return source-positioned lexical statement records."""
        return LexicalEngine(SQLITE_SPEC).split(sql_content)

    def split_statements(self, sql_content: str, strict_tokenizer: bool = False) -> List[str]:
        """Return execution text from the shared lexical engine."""
        return LexicalEngine(SQLITE_SPEC).split_statements(sql_content)

    def split_for_analysis(self, sql_content: str, strict_tokenizer: bool = False) -> List[str]:
        """Include comment-only segments in analysis text."""
        return LexicalEngine(SQLITE_SPEC).split_for_analysis(sql_content)

    def split_for_extraction(self, sql_content: str, strict_tokenizer: bool = False) -> List[str]:
        """Return the same scanner-selected constituents as analysis."""
        return self.split_for_analysis(sql_content, strict_tokenizer)

    def parse_sql(self, sql_content: str, default_schema: Optional[str] = None) -> ParseResult:
        """Project facts into statements without constructing schema models."""
        if not isinstance(sql_content, str):
            raise TypeError(f"sql_content must be a string, got {type(sql_content).__name__}")
        statements: List[SqlStatement] = []
        errors: List[str] = []
        try:
            fragments = self.split_for_analysis(sql_content)
        except (UnsafeStatementSplitError, UnsupportedMetaCommandError) as exc:
            return ParseResult(False, [], [str(exc)])
        for sql in fragments:
            facts = _FACTS.read(sql)
            objects = [
                obj.as_sql_object(default_schema, "sqlite") for obj in facts.affected_objects
            ]
            statements.append(
                SqlStatement(sql, facts.kind, objects, objects, "sqlite", default_schema)
            )
            if facts.diagnostic:
                errors.append(facts.diagnostic)
        return ParseResult(not errors, statements, errors)

    def extract_objects(
        self, sql_content: str, default_schema: Optional[str] = None
    ) -> List[SqlObject]:
        """Return identities of changed objects from statement facts."""
        return [
            obj.as_sql_object(default_schema, "sqlite")
            for sql in self.split_for_analysis(sql_content)
            for obj in _FACTS.read(sql).affected_objects
        ]

    def validate_sql(self, sql_content: str) -> Dict[str, Any]:
        """Report whether every selected statement has readable facts."""
        result = self.parse_sql(sql_content)
        return {"valid": result.success, "errors": result.errors}
