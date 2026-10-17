"""DuckDB statement facts projected through the shared lexical engine."""

from typing import Any, Dict, List, Optional

from dblift.core.exceptions import UnsafeStatementSplitError, UnsupportedMetaCommandError
from dblift.core.sql_model.base import ParseResult, SqlObject, SqlStatement
from dblift.core.sql_parser.lexical_engine import LexicalEngine
from dblift.core.sql_parser.parser_interface import SqlParserInterface
from dblift.core.sql_parser.statement import Statement
from dblift.core.sql_parser.statement_facts import SqlglotStatementFactsReader, StatementFacts
from dblift.db.plugins.duckdb.parser.lexical_spec import DUCKDB_SPEC


class DuckDBStatementFactsReader(SqlglotStatementFactsReader):
    """Keep DuckDB comment semantics authoritative before reading the AST."""

    def read(self, sql: str) -> StatementFacts:
        """Read engine-selected SQL with nested comments removed."""
        text = LexicalEngine(DUCKDB_SPEC).blank_comments(sql)
        return super().read(text) if text.strip() else StatementFacts("UNKNOWN", "UNKNOWN")


_FACTS = DuckDBStatementFactsReader("duckdb")


class DuckDBFactsParser(SqlParserInterface):
    """Preserve engine boundaries and project facts into the public parser result."""

    @property
    def dialect_name(self) -> str:
        """Return the plugin dialect name."""
        return "duckdb"

    def split(self, sql_content: str) -> List[Statement]:
        """Return source-positioned statements from the shared lexical engine."""
        return LexicalEngine(DUCKDB_SPEC).split(sql_content)

    def split_statements(self, sql_content: str, strict_tokenizer: bool = False) -> List[str]:
        """Return execution text from the shared lexical engine."""
        return LexicalEngine(DUCKDB_SPEC).split_statements(sql_content)

    def split_for_analysis(self, sql_content: str, strict_tokenizer: bool = False) -> List[str]:
        """Include comment-only segments in the engine's analysis text."""
        return LexicalEngine(DUCKDB_SPEC).split_for_analysis(sql_content)

    def split_for_extraction(self, sql_content: str, strict_tokenizer: bool = False) -> List[str]:
        """Return the same engine-selected constituents as analysis."""
        return self.split_for_analysis(sql_content, strict_tokenizer)

    def parse_sql(self, sql_content: str, default_schema: Optional[str] = None) -> ParseResult:
        """Read facts for every constituent, with atomic refusal of unsafe scripts."""
        if not isinstance(sql_content, str):
            raise TypeError(f"sql_content must be a string, got {type(sql_content).__name__}")
        try:
            fragments = self.split_for_analysis(sql_content)
        except (UnsafeStatementSplitError, UnsupportedMetaCommandError) as exc:
            return ParseResult(False, [], [f"Error splitting SQL: {exc}"])
        statements: List[SqlStatement] = []
        errors: List[str] = []
        for sql in fragments:
            facts = _FACTS.read(sql)
            objects = [
                obj.as_sql_object(default_schema, "duckdb") for obj in facts.affected_objects
            ]
            statements.append(
                SqlStatement(sql, facts.kind, objects, objects, "duckdb", default_schema)
            )
            if facts.error:
                errors.append(facts.error)
        return ParseResult(not errors, statements, errors)

    def extract_objects(
        self, sql_content: str, default_schema: Optional[str] = None
    ) -> List[SqlObject]:
        """Return identities of changed objects from statement facts."""
        return [
            obj.as_sql_object(default_schema, "duckdb")
            for sql in self.split_for_analysis(sql_content)
            for obj in _FACTS.read(sql).affected_objects
        ]

    def validate_sql(self, sql_content: str) -> Dict[str, Any]:
        """Report whether every engine-selected statement has readable facts."""
        result = self.parse_sql(sql_content)
        return {
            "valid": result.success,
            "statements_found": len(result.statements or []),
            "errors": result.errors,
        }
