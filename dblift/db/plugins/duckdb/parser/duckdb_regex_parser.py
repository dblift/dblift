"""DuckDB-specific regex-based SQL parser.

DuckDB has a non-procedural DDL surface (no stored procedures/PL blocks),
so statement splitting only needs to respect string literals and comments
around the ``;`` separator.
"""

from typing import List, Optional, Type

from dblift.core.sql_parser.base_tokenizer import BaseTokenizer
from dblift.core.sql_parser.enhanced_regex_parser import EnhancedRegexParser
from dblift.db.plugins.duckdb.parser.duckdb_tokenizer import DuckDBTokenizer
from dblift.db.plugins.duckdb.parser.parser_config import DuckDBParserConfig


class DuckDBRegexParser(EnhancedRegexParser):
    """DuckDB-specific regex-based SQL parser."""

    #: DuckDB's block-comment nesting rule, read by both ``split_statements``
    #: below and the inherited ``extract_objects``'s comment stripper, so
    #: the two cannot disagree about whether ``/* ... */`` nests.
    tokenizer_class: Type[BaseTokenizer] = DuckDBTokenizer

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
        block_comment_depth = 0
        nested_block_comments = self.tokenizer_class.NESTED_BLOCK_COMMENTS
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
                and block_comment_depth == 0
                and char == "/"
                and nxt == "*"
            ):
                block_comment_depth = 1
                current.append(char)
                current.append(nxt)
                i += 2
                continue
            if block_comment_depth > 0:
                if nested_block_comments and char == "/" and nxt == "*":
                    block_comment_depth += 1
                    current.append(char)
                    current.append(nxt)
                    i += 2
                    continue
                current.append(char)
                if char == "*" and nxt == "/":
                    current.append(nxt)
                    block_comment_depth -= 1
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
