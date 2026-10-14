"""DuckDB statement facts projected through the engine script scanner."""

from typing import Any, Dict, List, Optional

from dblift.core.exceptions import UnsafeStatementSplitError, UnsupportedMetaCommandError
from dblift.core.sql_model.base import ParseResult, SqlObject, SqlStatement
from dblift.core.sql_parser.statement_facts import SqlglotStatementFactsReader, StatementFacts
from dblift.db.plugins.duckdb.parser._script import blank_comments
from dblift.db.plugins.duckdb.parser.duckdb_regex_parser import DuckDBRegexParser


class DuckDBStatementFactsReader(SqlglotStatementFactsReader):
    """Keep DuckDB comment semantics authoritative before reading the AST."""

    def read(self, sql: str) -> StatementFacts:
        """Read scanner-selected SQL with nested comments removed."""
        text = blank_comments(sql)
        return super().read(text) if text.strip() else StatementFacts("UNKNOWN", "UNKNOWN")


_FACTS = DuckDBStatementFactsReader("duckdb")


class DuckDBFactsParser(DuckDBRegexParser):
    """Preserve scanner boundaries and project facts into the public parser result."""

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
        """Report whether every scanner-selected statement has readable facts."""
        result = self.parse_sql(sql_content)
        return {
            "valid": result.success,
            "statements_found": len(result.statements or []),
            "errors": result.errors,
        }
