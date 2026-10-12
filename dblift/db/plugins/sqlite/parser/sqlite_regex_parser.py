"""
SQLite object parser backed by the shell-aware script scanner.

This module provides SQLite-specific type classification and object extraction.

SQLite has simpler SQL syntax compared to enterprise databases:
- No stored procedures or functions (user-defined functions are in app code)
- No schemas (database file IS the schema)
- Limited ALTER TABLE (ADD COLUMN and RENAME only)
- Simple trigger syntax with BEGIN/END blocks
"""

from typing import Dict, List, Optional

from dblift.core.sql_model.base import SqlObjectType
from dblift.core.sql_parser.enhanced_regex_parser import EnhancedRegexParser
from dblift.core.sql_parser.lexical_engine import LexicalEngine
from dblift.core.sql_parser.statement import Statement
from dblift.db.plugins.sqlite.parser.lexical_spec import SQLITE_SPEC
from dblift.db.plugins.sqlite.parser.parser_config import SQLiteConfig


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

    def split(self, sql_content: str) -> List[Statement]:
        """The statements of a script as the ``sqlite3`` shell sends them (see docs/sql-parsing)."""
        return LexicalEngine(SQLITE_SPEC).split(sql_content)

    def split_statements(self, sql_content: str, strict_tokenizer: bool = False) -> List[str]:
        """The statements execution sends: the text of each ``split()`` record.

        The scanner has no unknown characters, so ``strict_tokenizer`` changes nothing.
        """
        return LexicalEngine(SQLITE_SPEC).split_statements(sql_content)

    def split_for_analysis(self, sql_content: str, strict_tokenizer: bool = False) -> List[str]:
        """The statements of a script for callers that read it statement by statement.

        Execution drops a segment of comments only; the readers of a script (linting, analysis)
        still see it, as they did before the scanner.
        """
        return LexicalEngine(SQLITE_SPEC).split_for_analysis(sql_content)

    def split_for_extraction(self, sql_content: str, strict_tokenizer: bool = False) -> List[str]:
        """Project extraction text from the shell scanner, retaining comment-only segments."""
        return self.split_for_analysis(sql_content, strict_tokenizer)

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
