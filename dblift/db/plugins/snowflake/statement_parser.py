"""Lossless statement splitting for Snowflake migration SQL."""

from __future__ import annotations

from typing import List

from dblift.core.exceptions import UnsafeStatementSplitError
from dblift.core.sql_parser.sqlglot_parser import SqlGlotParser


class SnowflakeStatementParser(SqlGlotParser):
    """Keep statement text intact while respecting Snowflake string delimiters."""

    def __init__(self) -> None:
        """Use Snowflake's AST grammar for non-splitting parser operations."""
        super().__init__("snowflake")

    def split_statements(self, sql_content: str, strict_tokenizer: bool = False) -> List[str]:
        """Split on unquoted semicolons and reject unquoted scripting blocks."""
        statements: List[str] = []
        start = 0
        index = 0
        state = "sql"
        block_depth = 0
        first_word = ""
        has_code = False

        while index < len(sql_content):
            char = sql_content[index]
            next_char = sql_content[index + 1] if index + 1 < len(sql_content) else ""

            if state == "line_comment":
                if char == "\n":
                    state = "sql"
                index += 1
                continue

            if state == "block_comment":
                if char == "/" and next_char == "*":
                    block_depth += 1
                    index += 2
                elif char == "*" and next_char == "/":
                    block_depth -= 1
                    index += 2
                    if block_depth == 0:
                        state = "sql"
                else:
                    index += 1
                continue

            if state == "single_quote":
                if char == "\\" and next_char:
                    index += 2
                elif char == "'" and next_char == "'":
                    index += 2
                elif char == "'":
                    state = "sql"
                    index += 1
                else:
                    index += 1
                continue

            if state == "double_quote":
                if char == '"' and next_char == '"':
                    index += 2
                elif char == '"':
                    state = "sql"
                    index += 1
                else:
                    index += 1
                continue

            if state == "dollar_quote":
                if char == "$" and next_char == "$":
                    state = "sql"
                    index += 2
                else:
                    index += 1
                continue

            if char == "-" and next_char == "-":
                state = "line_comment"
                index += 2
            elif char == "/" and next_char == "*":
                state = "block_comment"
                block_depth = 1
                index += 2
            elif char == "'":
                has_code = True
                state = "single_quote"
                index += 1
            elif char == '"':
                has_code = True
                state = "double_quote"
                index += 1
            elif char == "$" and next_char == "$":
                has_code = True
                state = "dollar_quote"
                index += 2
            elif char == ";":
                if has_code:
                    self._append_statement(statements, sql_content[start:index], first_word)
                start = index + 1
                first_word = ""
                has_code = False
                index += 1
            elif char.isalpha() or char == "_":
                word_end = index + 1
                while word_end < len(sql_content) and (
                    sql_content[word_end].isalnum() or sql_content[word_end] == "_"
                ):
                    word_end += 1
                if not first_word:
                    first_word = sql_content[index:word_end].upper()
                has_code = True
                index = word_end
            else:
                if not char.isspace():
                    has_code = True
                index += 1

        if state not in {"sql", "line_comment"}:
            raise UnsafeStatementSplitError("Unterminated Snowflake string or comment")
        if has_code:
            self._append_statement(statements, sql_content[start:], first_word)
        return statements

    @staticmethod
    def _append_statement(statements: List[str], sql: str, first_word: str) -> None:
        if first_word in {"BEGIN", "DECLARE"}:
            raise UnsafeStatementSplitError(
                "Unquoted Snowflake Scripting blocks are not qualified for SQL migrations"
            )
        statements.append(sql.strip())
