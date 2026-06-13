"""
SQLite-specific regex-based SQL parser.

This module provides SQLite-specific parsing logic using regex patterns
for statement splitting, type classification, and object extraction.

SQLite has simpler SQL syntax compared to enterprise databases:
- No stored procedures or functions (user-defined functions are in app code)
- No schemas (database file IS the schema)
- Limited ALTER TABLE (ADD COLUMN and RENAME only)
- Simple trigger syntax with BEGIN/END blocks
"""

import re
from typing import Any, Dict, List, Optional, Set

from core.sql_model.base import SqlObject, SqlObjectType
from core.sql_parser.enhanced_regex_parser import EnhancedRegexParser
from db.plugins.sqlite.parser.parser_config import SQLiteConfig


class SQLiteRegexParser(EnhancedRegexParser):
    """SQLite-specific regex-based SQL parser."""

    def __init__(self, config: Optional[SQLiteConfig] = None):
        """Initialize the SQLite regex parser.

        Args:
            config: Optional SQLite dialect configuration
        """
        sqlite_config = config or SQLiteConfig()
        self.config = sqlite_config  # type: ignore[assignment]
        super().__init__(self.config)

        # Compile SQLite-specific patterns
        self._trigger_block_pattern = re.compile(
            r"\s*CREATE\s+(?:TEMP(?:ORARY)?\s+)?TRIGGER\s+.*?\s+BEGIN\s+.*?\s+END\s*;?",
            re.IGNORECASE | re.DOTALL,
        )

    def split_statements(self, sql_content: str, strict_tokenizer: bool = False) -> List[str]:
        """Split SQL content into individual statements.

        Handles:
        - Simple semicolon-separated statements
        - Trigger blocks with BEGIN/END
        - Comments (both line and block)

        Args:
            sql_content: SQL content to split

        Returns:
            List of individual SQL statements
        """
        if not sql_content or not sql_content.strip():
            return []

        statements = []
        current_statement = []
        in_string = False
        string_char = None
        in_block_comment = False
        in_line_comment = False
        in_trigger = False
        begin_count = 0
        case_depth = 0

        i = 0
        content = sql_content
        length = len(content)

        while i < length:
            char = content[i]
            next_char = content[i + 1] if i + 1 < length else ""

            # Handle block comments
            if not in_string and not in_line_comment:
                if char == "/" and next_char == "*":
                    in_block_comment = True
                    current_statement.append(char)
                    current_statement.append(next_char)
                    i += 2
                    continue
                elif char == "*" and next_char == "/":
                    in_block_comment = False
                    current_statement.append(char)
                    current_statement.append(next_char)
                    i += 2
                    continue

            if in_block_comment:
                current_statement.append(char)
                i += 1
                continue

            # Handle line comments
            if not in_string and char == "-" and next_char == "-":
                in_line_comment = True
                current_statement.append(char)
                i += 1
                continue

            if in_line_comment:
                current_statement.append(char)
                if char in "\r\n":
                    in_line_comment = False
                i += 1
                continue

            # Handle strings
            if char in "'" and not in_string:
                in_string = True
                string_char = char
                current_statement.append(char)
                i += 1
                continue

            if in_string:
                current_statement.append(char)
                if char == string_char:
                    # Check for escaped quote
                    if next_char == string_char:
                        current_statement.append(next_char)
                        i += 2
                        continue
                    else:
                        in_string = False
                        string_char = None
                i += 1
                continue

            # Track BEGIN/END for triggers, with CASE...END awareness
            upper_content = content[i:].upper()

            # Track CASE depth so CASE...END doesn't close trigger BEGIN...END
            if upper_content.startswith("CASE") and (i == 0 or not content[i - 1].isalnum()):
                if i + 4 >= length or not content[i + 4].isalnum():
                    if in_trigger:
                        case_depth += 1

            if upper_content.startswith("BEGIN") and (i == 0 or not content[i - 1].isalnum()):
                if i + 5 >= length or not content[i + 5].isalnum():
                    begin_count += 1
                    in_trigger = True

            if upper_content.startswith("END") and (i == 0 or not content[i - 1].isalnum()):
                if i + 3 >= length or not content[i + 3].isalnum():
                    if case_depth > 0:
                        # This END closes a CASE expression, not the trigger block
                        case_depth -= 1
                    else:
                        begin_count -= 1
                        if begin_count <= 0:
                            begin_count = 0
                            in_trigger = False

            # Handle statement separator
            if char == ";" and not in_trigger:
                current_statement.append(char)
                stmt = "".join(current_statement).strip()
                if stmt:
                    statements.append(stmt)
                current_statement = []
                i += 1
                continue

            current_statement.append(char)
            i += 1

        # Add final statement if any
        final_stmt = "".join(current_statement).strip()
        if final_stmt:
            statements.append(final_stmt)

        return statements

    def classify_statement(self, statement: str) -> str:
        """Classify a SQL statement type.

        Args:
            statement: SQL statement to classify

        Returns:
            Classification: 'DDL', 'DML', 'QUERY', or 'UNKNOWN'
        """
        if not statement:
            return "UNKNOWN"

        statement = statement.strip()

        # SQLiteConfig has these methods, but mypy sees DialectConfig type
        sqlite_config = self.config
        if sqlite_config.is_ddl_statement(statement):  # type: ignore[attr-defined]
            return "DDL"
        elif sqlite_config.is_dml_statement(statement):  # type: ignore[attr-defined]
            return "DML"
        elif sqlite_config.is_query_statement(statement):  # type: ignore[attr-defined]
            return "QUERY"

        # Check for transaction control
        upper_stmt = statement.upper()
        if upper_stmt.startswith(("BEGIN", "COMMIT", "ROLLBACK", "SAVEPOINT", "RELEASE")):
            return "TCL"  # Transaction Control Language

        return "UNKNOWN"

    def extract_objects(
        self, sql_content: str, default_schema: Optional[str] = None
    ) -> List[SqlObject]:
        """Extract database objects from a statement.

        Args:
            sql_content: SQL statement to analyze
            default_schema: Default schema name (optional)

        Returns:
            List of SqlObject instances
        """
        if not sql_content:
            return []

        objects: List[SqlObject] = []
        statement = sql_content.strip()

        # Try each object pattern
        for pattern_name, pattern in self.config.object_patterns.items():
            match = pattern.search(statement)
            if match:
                groups = match.groups()

                # Extract schema and name from groups
                # Patterns typically have: (quoted_schema, unquoted_schema, bracket_schema, quoted_name, unquoted_name, bracket_name)
                schema = None
                name = None

                # Filter out None values and find the actual values
                non_none = [g for g in groups if g is not None]
                if len(non_none) >= 1:
                    name = non_none[-1]  # Last non-None is the object name
                if len(non_none) >= 2:
                    schema = non_none[-2]  # Second to last is schema (if present)

                if name:
                    obj_type = self._get_object_type_from_pattern(pattern_name)
                    obj = SqlObject(
                        name=name,
                        object_type=obj_type,
                        schema=schema or default_schema,
                    )
                    objects.append(obj)
                    break

        return objects

    def _get_object_type_from_pattern(self, pattern_name: str) -> SqlObjectType:
        """Convert pattern name to SqlObjectType."""
        type_mapping: Dict[str, SqlObjectType] = {
            "create_table": SqlObjectType.TABLE,
            "create_view": SqlObjectType.VIEW,
            "create_index": SqlObjectType.INDEX,
            "create_trigger": SqlObjectType.TRIGGER,
            "create_virtual_table": SqlObjectType.VIRTUAL_TABLE,
            "alter_table": SqlObjectType.TABLE,
            "drop_table": SqlObjectType.TABLE,
            "drop_view": SqlObjectType.VIEW,
            "drop_index": SqlObjectType.INDEX,
            "drop_trigger": SqlObjectType.TRIGGER,
        }
        return type_mapping.get(pattern_name, SqlObjectType.UNKNOWN)

    def validate_syntax(self, statement: str) -> Dict[str, Any]:
        """Perform basic syntax validation.

        Args:
            statement: SQL statement to validate

        Returns:
            Validation result with 'valid' flag and optional 'errors'
        """
        if not statement:
            return {"valid": False, "errors": ["Empty statement"]}

        statement = statement.strip()
        errors = []

        # Check for unclosed strings
        single_quote_count = 0
        i = 0
        while i < len(statement):
            if statement[i] == "'":
                if i + 1 < len(statement) and statement[i + 1] == "'":
                    i += 2  # Skip escaped quote
                    continue
                single_quote_count += 1
            i += 1

        if single_quote_count % 2 != 0:
            errors.append("Unclosed string literal")

        # Check for unclosed parentheses
        paren_count = 0
        for char in statement:
            if char == "(":
                paren_count += 1
            elif char == ")":
                paren_count -= 1
            if paren_count < 0:
                errors.append("Unmatched closing parenthesis")
                break

        if paren_count > 0:
            errors.append("Unclosed parenthesis")

        # Check for unclosed block comments
        if "/*" in statement and "*/" not in statement:
            errors.append("Unclosed block comment")

        return {"valid": len(errors) == 0, "errors": errors if errors else None}

    def get_supported_features(self) -> Set[str]:
        """Get set of SQLite features supported by this parser.

        Returns:
            Set of supported feature names
        """
        return {
            "tables",
            "views",
            "indexes",
            "triggers",
            "virtual_tables",
            "cte",
            "cte_recursive",
            "on_conflict",
            "returning",  # SQLite 3.35+
            "fts",  # Full-text search
            "json",  # JSON functions
        }
