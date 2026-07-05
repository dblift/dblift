"""DuckDB-specific regex-based SQL parser.

DuckDB has a non-procedural DDL surface (no stored procedures/PL blocks),
so statement splitting only needs to respect string literals and comments
around the ``;`` separator.
"""

from typing import Any, Dict, List, Optional

from core.sql_model.base import SqlObject, SqlObjectType
from core.sql_parser.enhanced_regex_parser import EnhancedRegexParser
from db.plugins.duckdb.parser.parser_config import DuckDBParserConfig


class DuckDBRegexParser(EnhancedRegexParser):
    """DuckDB-specific regex-based SQL parser."""

    def __init__(self, config: Optional[DuckDBParserConfig] = None):
        """Initialize the DuckDB regex parser."""
        duckdb_config = config or DuckDBParserConfig()
        self.config = duckdb_config  # type: ignore[assignment]
        super().__init__(self.config)

    def split_statements(self, sql_content: str, strict_tokenizer: bool = False) -> List[str]:
        """Split SQL into statements, honouring string literals and comments."""
        if not sql_content or not sql_content.strip():
            return []

        statements: List[str] = []
        current: List[str] = []
        in_string = False
        in_ident = False  # inside a "double-quoted" identifier
        in_block_comment = False
        in_line_comment = False

        i = 0
        content = sql_content
        length = len(content)
        while i < length:
            char = content[i]
            nxt = content[i + 1] if i + 1 < length else ""

            if (
                not in_string
                and not in_ident
                and not in_line_comment
                and char == "/"
                and nxt == "*"
            ):
                in_block_comment = True
                current.append(char)
                current.append(nxt)
                i += 2
                continue
            if in_block_comment:
                current.append(char)
                if char == "*" and nxt == "/":
                    current.append(nxt)
                    in_block_comment = False
                    i += 2
                    continue
                i += 1
                continue

            if not in_string and not in_ident and char == "-" and nxt == "-":
                in_line_comment = True
                current.append(char)
                i += 1
                continue
            if in_line_comment:
                current.append(char)
                if char in "\r\n":
                    in_line_comment = False
                i += 1
                continue

            # Double-quoted identifiers may contain ; and comment markers.
            if char == '"' and not in_string and not in_ident:
                in_ident = True
                current.append(char)
                i += 1
                continue
            if in_ident:
                current.append(char)
                if char == '"':
                    if nxt == '"':  # escaped quote inside identifier
                        current.append(nxt)
                        i += 2
                        continue
                    in_ident = False
                i += 1
                continue

            if char == "'" and not in_string:
                in_string = True
                current.append(char)
                i += 1
                continue
            if in_string:
                current.append(char)
                if char == "'":
                    if nxt == "'":  # escaped quote
                        current.append(nxt)
                        i += 2
                        continue
                    in_string = False
                i += 1
                continue

            if char == ";":
                current.append(char)
                stmt = "".join(current).strip()
                if stmt:
                    statements.append(stmt)
                current = []
                i += 1
                continue

            current.append(char)
            i += 1

        final = "".join(current).strip()
        if final:
            statements.append(final)
        return statements

    def classify_statement(self, statement: str) -> str:
        """Classify a SQL statement as DDL / DML / QUERY / TCL / UNKNOWN."""
        if not statement:
            return "UNKNOWN"
        statement = statement.strip()
        cfg = self.config
        if cfg.is_ddl_statement(statement):  # type: ignore[attr-defined]
            return "DDL"
        if cfg.is_dml_statement(statement):  # type: ignore[attr-defined]
            return "DML"
        if cfg.is_query_statement(statement):  # type: ignore[attr-defined]
            return "QUERY"
        if statement.upper().startswith(("BEGIN", "COMMIT", "ROLLBACK", "ABORT", "START")):
            return "TCL"
        return "UNKNOWN"

    def extract_objects(
        self, sql_content: str, default_schema: Optional[str] = None
    ) -> List[SqlObject]:
        """Extract database objects from a statement via config object patterns."""
        if not sql_content:
            return []
        objects: List[SqlObject] = []
        statement = sql_content.strip()
        for pattern_name, pattern in self.config.object_patterns.items():
            match = pattern.search(statement)
            if not match:
                continue
            non_none = [g for g in match.groups() if g is not None]
            if not non_none:
                continue
            name = non_none[-1].strip('"')
            schema = non_none[-2].strip('"') if len(non_none) >= 2 else None
            objects.append(
                SqlObject(
                    name=name,
                    object_type=self._object_type(pattern_name),
                    schema=schema or default_schema,
                )
            )
            break
        return objects

    @staticmethod
    def _object_type(pattern_name: str) -> SqlObjectType:
        mapping: Dict[str, SqlObjectType] = {
            "create_table": SqlObjectType.TABLE,
            "create_view": SqlObjectType.VIEW,
            "create_index": SqlObjectType.INDEX,
            "create_sequence": SqlObjectType.SEQUENCE,
            "alter_table": SqlObjectType.TABLE,
            "drop_table": SqlObjectType.TABLE,
        }
        return mapping.get(pattern_name, SqlObjectType.UNKNOWN)
