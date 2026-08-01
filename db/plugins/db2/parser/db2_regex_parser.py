"""DB2 regex-based SQL parser implementation.

This module provides a DB2-specific regex parser that handles DB2's unique
features including SQL/PL syntax, triggers, stored procedures, and utility statements.
"""

import logging
import re
from typing import Any, Dict, List, Optional

from core.sql_model.base import ParseResult, SqlStatement, SqlStatementType
from core.sql_parser.enhanced_regex_parser import EnhancedRegexParser
from db.plugins.db2.parser.parser_config import DB2Config

logger = logging.getLogger(__name__)

# Trailing trivia (whitespace, line comments, block comments) that may follow
# a block's undelimited closing END before the true end of the script. The
# gates below already treat a missing @/; terminator as fine when END is the
# last thing in the input; a comment after that END is not whitespace, so
# without this alternative the $ anchor never matched and the gate missed a
# block the matching extractor would otherwise find without any trouble.
_TRAILING_TRIVIA = r"(?:\s|--[^\n]*|/\*.*?\*/)*"


class DB2RegexParser(EnhancedRegexParser):
    """DB2-specific regex parser with enhanced DB2 feature support."""

    dialect_name = "db2"  # lint: allow-dialect-string: dialect dispatch

    def __init__(self) -> None:
        """Initialize DB2 regex parser."""
        config = DB2Config()
        super().__init__(config)  # type: ignore[arg-type]
        self.config: DB2Config = config  # type: ignore[assignment]

    def split_statements(self, sql_content: str, strict_tokenizer: bool = False) -> List[str]:
        """Split SQL content with DB2-specific handling.

        Handles SQL/PL blocks, EXEC SQL statements, and DB2 utility commands.

        Args:
            sql_content: SQL content to split

        Returns:
            List of SQL statement strings
        """
        if not sql_content.strip():
            return []

        # Handle EXEC SQL blocks first
        if self._has_exec_sql_blocks(sql_content):
            return self._split_with_exec_sql_awareness(sql_content)

        # Handle package blocks (CREATE PACKAGE)
        if self._has_package_blocks(sql_content):
            return self._split_with_package_awareness(sql_content)

        # Handle module blocks (CREATE MODULE) - DB2 LUW feature
        if self._has_module_blocks(sql_content):
            return self._split_with_module_awareness(sql_content)

        # Handle SQL/PL blocks (procedures and functions)
        if self._has_sqlpl_blocks(sql_content):
            return self._split_with_sqlpl_awareness(sql_content)

        # Handle trigger blocks BEFORE compound statements
        # Triggers contain BEGIN ATOMIC, so they must be checked before generic compound statements
        if self._has_trigger_blocks(sql_content):
            return self._split_with_trigger_awareness(sql_content)

        # Handle compound statements
        if self._has_compound_statements(sql_content):
            return self._split_with_compound_awareness(sql_content)

        # Handle SPUFI terminator customization
        if self._has_spufi_terminators(sql_content):
            return self._split_with_spufi_terminators(sql_content)

        # Use enhanced semicolon splitting with DB2 identifier awareness
        return self._split_by_semicolon_db2(sql_content)

    def _has_exec_sql_blocks(self, sql: str) -> bool:
        """Check if SQL contains EXEC SQL blocks."""
        return bool(re.search(r"\bEXEC\s+SQL\b", sql, re.IGNORECASE))

    def _has_package_blocks(self, sql: str) -> bool:
        """Check if SQL contains package blocks."""
        # Check for CREATE/ALTER PACKAGE with AS...END
        return bool(
            re.search(
                r"\b(?:CREATE|ALTER)\s+(?:OR\s+REPLACE\s+)?PACKAGE\s+\S+\s+AS\b.*?\bEND\b",
                sql,
                re.IGNORECASE | re.DOTALL,
            )
        )

    def _has_module_blocks(self, sql: str) -> bool:
        """Check if SQL contains module blocks (DB2 LUW)."""
        # Check for CREATE MODULE ... END MODULE
        return bool(
            re.search(
                r"\bCREATE\s+(?:OR\s+REPLACE\s+)?MODULE\b.*?\bEND\s+MODULE\b",
                sql,
                re.IGNORECASE | re.DOTALL,
            )
        )

    def _has_sqlpl_blocks(self, sql: str) -> bool:
        """Check if SQL contains SQL/PL blocks."""
        # Check for CREATE/ALTER PROCEDURE or FUNCTION with BEGIN...END
        # LANGUAGE SQL is optional in DB2
        # The trailing terminator is optional at the end of the script: the block
        # extractor handles an END with no delimiter, so this gate must too - and
        # so must a trailing comment after that undelimited END, see
        # _TRAILING_TRIVIA.
        return bool(
            re.search(
                r"\b(?:CREATE|ALTER)\s+(?:OR\s+REPLACE\s+)?(?:PROCEDURE|FUNCTION)\s+\S+.*?BEGIN.*?END\s*"
                r"(?:[@;]|" + _TRAILING_TRIVIA + r"$)",
                sql,
                re.IGNORECASE | re.DOTALL,
            )
        )

    def _has_compound_statements(self, sql: str) -> bool:
        """Check if SQL contains compound statements."""
        return bool(re.search(r"\bBEGIN\s+(?:ATOMIC|NOT\s+ATOMIC)\b", sql, re.IGNORECASE))

    def _has_trigger_blocks(self, sql: str) -> bool:
        """Check if SQL contains trigger blocks."""
        # Check for CREATE/ALTER TRIGGER with BEGIN (ATOMIC optional)...END
        # DB2 triggers can use BEGIN ATOMIC or just BEGIN
        # The trailing terminator is optional at the end of the script: the block
        # extractor handles an END with no delimiter, so this gate must too - and
        # so must a trailing comment after that undelimited END, see
        # _TRAILING_TRIVIA.
        return bool(
            re.search(
                r"\b(?:CREATE|ALTER)\s+(?:OR\s+REPLACE\s+)?TRIGGER\s+\S+.*?(?:BEFORE|AFTER|INSTEAD\s+OF)"
                r".*?BEGIN\s+(?:ATOMIC\s+)?.*?END\s*(?:[@;]|" + _TRAILING_TRIVIA + r"$)",
                sql,
                re.IGNORECASE | re.DOTALL,
            )
        )

    def _has_spufi_terminators(self, sql: str) -> bool:
        """Check if SQL contains SPUFI terminator customization."""
        return bool(re.search(r"--#SET\s+TERMINATOR\s+", sql, re.IGNORECASE))

    def _split_with_package_awareness(self, sql: str) -> List[str]:
        """Split SQL with package block awareness.

        Packages have the pattern:
        CREATE [OR REPLACE] PACKAGE package_name AS
            PROCEDURE proc_name(...);
            FUNCTION func_name(...) RETURN type;
        END [package_name];
        """
        statements = []
        # Find package blocks using regex
        package_pattern = (
            r"(CREATE\s+(?:OR\s+REPLACE\s+)?PACKAGE\s+\S+\s+AS\b.*?\bEND\s+(?:\S+\s*)?;)"
        )

        current_pos = 0
        for match in re.finditer(package_pattern, sql, re.IGNORECASE | re.DOTALL):
            # Add any SQL before this package
            before_package = sql[current_pos : match.start()].strip()
            if before_package:
                statements.extend(self._split_by_semicolon_db2(before_package))

            # Add the entire package as one statement
            statements.append(match.group(1).strip())
            current_pos = match.end()

        # Add any remaining SQL after the last package
        remaining_sql = sql[current_pos:].strip()
        if remaining_sql:
            statements.extend(self._split_by_semicolon_db2(remaining_sql))

        # If no packages found, fall back to regular splitting
        if not statements:
            return self._split_by_semicolon_db2(sql)

        return statements

    def _split_with_module_awareness(self, sql: str) -> List[str]:
        """Split SQL with module block awareness.

        DB2 LUW modules have the pattern:
        CREATE [OR REPLACE] MODULE module_name
            PUBLISH FUNCTION func_name(...) RETURNS type;
            CREATE FUNCTION func_name(...)
                ...
            END;
        END MODULE;
        """
        statements = []
        # Find module blocks using regex
        # Modules end with "END MODULE" (unlike packages which end with just "END")
        module_pattern = r"(CREATE\s+(?:OR\s+REPLACE\s+)?MODULE\s+.*?\bEND\s+MODULE\s*;?)"

        current_pos = 0
        for match in re.finditer(module_pattern, sql, re.IGNORECASE | re.DOTALL):
            # Add any SQL before this module
            before_module = sql[current_pos : match.start()].strip()
            if before_module:
                statements.extend(self._split_by_semicolon_db2(before_module))

            # Add the entire module as one statement
            statements.append(match.group(1).strip())
            current_pos = match.end()

        # Add any remaining SQL after the last module
        remaining_sql = sql[current_pos:].strip()
        if remaining_sql:
            statements.extend(self._split_by_semicolon_db2(remaining_sql))

        # If no modules found, fall back to regular splitting
        if not statements:
            return self._split_by_semicolon_db2(sql)

        return statements

    def _split_with_exec_sql_awareness(self, sql: str) -> List[str]:
        """Split SQL with EXEC SQL block awareness."""
        statements = []
        exec_sql_blocks = self.config.extract_exec_sql_blocks(sql)

        if not exec_sql_blocks:
            return self._split_by_semicolon_db2(sql)

        current_pos = 0
        for block in exec_sql_blocks:
            # Add any SQL before this block
            before_block = sql[current_pos : int(block["start"])].strip()
            if before_block:
                statements.extend(self._split_by_semicolon_db2(before_block))

            # Add the EXEC SQL block content as a statement
            statements.append(block["content"])
            current_pos = int(block["end"])

        # Add any remaining SQL after the last block
        remaining_sql = sql[current_pos:].strip()
        if remaining_sql:
            statements.extend(self._split_by_semicolon_db2(remaining_sql))

        return statements

    def _split_with_sqlpl_awareness(self, sql: str) -> List[str]:
        """Split SQL with SQL/PL block awareness."""
        statements = []
        sqlpl_blocks = self.config.extract_sqlpl_blocks(sql)

        if not sqlpl_blocks:
            return self._split_by_semicolon_db2(sql)

        current_pos = 0
        for block in sqlpl_blocks:
            # Add any SQL before this block
            before_block = sql[current_pos : int(block["start"])].strip()
            if before_block:
                statements.extend(self._split_by_semicolon_db2(before_block))

            # Add the SQL/PL block as a single statement
            statements.append(block["content"])
            current_pos = int(block["end"])

        # Add any remaining SQL after the last block
        remaining_sql = sql[current_pos:].strip()
        if remaining_sql:
            statements.extend(self._split_by_semicolon_db2(remaining_sql))

        return statements

    def _split_with_compound_awareness(self, sql: str) -> List[str]:
        """Split SQL with compound statement awareness."""
        statements = []
        compound_blocks = self.config.extract_compound_statements(sql)

        if not compound_blocks:
            return self._split_by_semicolon_db2(sql)

        current_pos = 0
        for block in compound_blocks:
            # Add any SQL before this block
            before_block = sql[current_pos : int(block["start"])].strip()
            if before_block:
                statements.extend(self._split_by_semicolon_db2(before_block))

            # Add the compound statement as a single statement
            statements.append(block["content"])
            current_pos = int(block["end"])

        # Add any remaining SQL after the last block
        remaining_sql = sql[current_pos:].strip()
        if remaining_sql:
            statements.extend(self._split_by_semicolon_db2(remaining_sql))

        return statements

    def _split_with_trigger_awareness(self, sql: str) -> List[str]:
        """Split SQL with trigger block awareness."""
        statements = []
        trigger_blocks = self.config.extract_trigger_blocks(sql)

        if not trigger_blocks:
            return self._split_by_semicolon_db2(sql)

        current_pos = 0
        for block in trigger_blocks:
            # Add any SQL before this block
            before_block = sql[current_pos : int(block["start"])].strip()
            if before_block:
                statements.extend(self._split_by_semicolon_db2(before_block))

            # Add the trigger block as a single statement
            statements.append(block["content"])
            current_pos = int(block["end"])

        # Add any remaining SQL after the last block
        remaining_sql = sql[current_pos:].strip()
        if remaining_sql:
            statements.extend(self._split_by_semicolon_db2(remaining_sql))

        return statements

    def _split_with_spufi_terminators(self, sql: str) -> List[str]:
        """Split SQL with SPUFI terminator awareness."""
        statements = []
        lines = sql.split("\n")
        current_terminator = ";"
        current_statement = []

        for line in lines:
            line_stripped = line.strip()

            # Check for terminator change
            terminator_match = re.match(r"--#SET\s+TERMINATOR\s+(.)", line_stripped, re.IGNORECASE)
            if terminator_match:
                current_terminator = terminator_match.group(1)
                continue

            # Check if line ends with current terminator
            if line_stripped.endswith(current_terminator):
                current_statement.append(line_stripped[: -len(current_terminator)])
                stmt = "\n".join(current_statement).strip()
                if stmt and not self._is_empty_or_comment(stmt):
                    statements.append(stmt)
                current_statement = []
            else:
                current_statement.append(line)

        # Add any remaining statement
        if current_statement:
            stmt = "\n".join(current_statement).strip()
            if stmt and not self._is_empty_or_comment(stmt):
                statements.append(stmt)

        return statements

    def _split_by_semicolon_db2(self, sql: str) -> List[str]:
        """Enhanced semicolon splitting with DB2 quoted identifier support."""
        statements = []
        current = []
        in_string = False
        in_quoted_identifier = False
        in_line_comment = False
        in_block_comment = False
        string_char = None
        i = 0

        while i < len(sql):
            char = sql[i]

            # Handle string literals
            if not in_line_comment and not in_block_comment and not in_quoted_identifier:
                if not in_string and char in ("'", '"'):
                    # Check if this is a quoted identifier (double quote) or string literal
                    if char == '"':
                        in_quoted_identifier = True
                    else:
                        in_string = True
                        string_char = char
                elif in_string and char == string_char:
                    # Check for escaped quotes
                    if i + 1 < len(sql) and sql[i + 1] == string_char:
                        current.append(char)
                        current.append(sql[i + 1])
                        i += 2
                        continue
                    else:
                        in_string = False
                        string_char = None

            # Handle quoted identifiers
            if not in_string and not in_line_comment and not in_block_comment:
                if not in_quoted_identifier and char == '"':
                    in_quoted_identifier = True
                elif in_quoted_identifier and char == '"':
                    in_quoted_identifier = False

            # Handle comments
            if not in_string and not in_quoted_identifier:
                # Line comments
                if char == "-" and i + 1 < len(sql) and sql[i + 1] == "-":
                    in_line_comment = True
                    current.append(char)
                    current.append(sql[i + 1])
                    i += 2
                    continue
                # Block comments
                elif char == "/" and i + 1 < len(sql) and sql[i + 1] == "*":
                    in_block_comment = True
                    current.append(char)
                    current.append(sql[i + 1])
                    i += 2
                    continue
                elif char == "*" and i + 1 < len(sql) and sql[i + 1] == "/" and in_block_comment:
                    in_block_comment = False
                    current.append(char)
                    current.append(sql[i + 1])
                    i += 2
                    continue

            # End line comments at newline
            if char in ["\n", "\r"] and in_line_comment:
                in_line_comment = False

            # Handle statement terminators (semicolon and @)
            if (
                char in (";", "@")
                and not in_string
                and not in_quoted_identifier
                and not in_line_comment
                and not in_block_comment
            ):
                # Don't include the delimiter in the statement
                stmt = "".join(current).strip()
                if stmt and not self._is_empty_or_comment(stmt):
                    statements.append(stmt)
                current = []
                i += 1
                continue

            current.append(char)
            i += 1

        # Add any remaining statement
        if current:
            stmt = "".join(current).strip()
            if stmt and not self._is_empty_or_comment(stmt):
                statements.append(stmt)

        return statements

    def _extract_sqlpl_procedure_name(self, sql: str) -> Optional[str]:
        """Extract SQL/PL procedure name from CREATE PROCEDURE statement."""
        match = re.search(
            r"\b(?:CREATE|ALTER)\s+(?:OR\s+REPLACE\s+)?PROCEDURE\s+(?:\"([^\"]+)\"|([a-zA-Z0-9_$#@]+))(?:\.(?:\"([^\"]+)\"|([a-zA-Z0-9_$#@]+)))?",
            sql,
            re.IGNORECASE,
        )
        if match:
            # Return the first non-None group
            return next((g for g in match.groups() if g), None)
        return None

    def _extract_sqlpl_function_name(self, sql: str) -> Optional[str]:
        """Extract SQL/PL function name from CREATE FUNCTION statement."""
        match = re.search(
            r"\b(?:CREATE|ALTER)\s+(?:OR\s+REPLACE\s+)?FUNCTION\s+(?:\"([^\"]+)\"|([a-zA-Z0-9_$#@]+))(?:\.(?:\"([^\"]+)\"|([a-zA-Z0-9_$#@]+)))?",
            sql,
            re.IGNORECASE,
        )
        if match:
            # Return the first non-None group
            return next((g for g in match.groups() if g), None)
        return None

    def _extract_trigger_name(self, sql: str) -> Optional[str]:
        """Extract trigger name from CREATE TRIGGER statement."""
        match = re.search(
            r"\b(?:CREATE|ALTER)\s+(?:OR\s+REPLACE\s+)?TRIGGER\s+(?:\"([^\"]+)\"|([a-zA-Z0-9_$#@]+))(?:\.(?:\"([^\"]+)\"|([a-zA-Z0-9_$#@]+)))?",
            sql,
            re.IGNORECASE,
        )
        if match:
            # Return the first non-None group
            return next((g for g in match.groups() if g), None)
        return None

    def _extract_tablespace_name(self, sql: str) -> Optional[str]:
        """Extract tablespace name from CREATE TABLESPACE statement."""
        match = re.search(
            r"\b(?:CREATE|ALTER|DROP)\s+(?:LOB\s+)?TABLESPACE\s+(?:\"([^\"]+)\"|([a-zA-Z0-9_$#@]+))",
            sql,
            re.IGNORECASE,
        )
        if match:
            # Return the first non-None group
            return next((g for g in match.groups() if g), None)
        return None

    def _extract_stogroup_name(self, sql: str) -> Optional[str]:
        """Extract storage group name from CREATE STOGROUP statement."""
        match = re.search(
            r"\b(?:CREATE|ALTER|DROP)\s+STOGROUP\s+(?:\"([^\"]+)\"|([a-zA-Z0-9_$#@]+))",
            sql,
            re.IGNORECASE,
        )
        if match:
            # Return the first non-None group
            return next((g for g in match.groups() if g), None)
        return None

    def parse_sql(self, sql_content: str, default_schema: Optional[str] = None) -> ParseResult:
        """Parse SQL content with DB2-specific enhancements.

        Args:
            sql_content: SQL content to parse
            default_schema: Default schema name

        Returns:
            ParseResult with statements and any errors
        """
        statements = []
        errors = []

        try:
            # Clean and normalize SQL
            cleaned_sql = self._clean_db2_comments(sql_content)

            # Enhanced statement splitting
            sql_statements = self.split_statements(cleaned_sql)

            # Parse each statement with DB2-specific handling
            for sql in sql_statements:
                if not sql.strip():
                    continue

                try:
                    stmt_type = self._classify_statement_enhanced(sql)
                    objects = self.extract_objects(sql, default_schema)

                    statement = SqlStatement(
                        sql_text=sql,
                        statement_type=stmt_type,
                        objects=objects,
                        affected_objects=objects,
                        dialect=self.dialect_name,
                        schema=default_schema or self.config.get_default_schema(),
                    )
                    statements.append(statement)
                except Exception as e:
                    error_msg = f"Error parsing DB2 statement: {str(e)}"
                    logger.warning(error_msg)
                    errors.append(error_msg)

                    # Create statement with minimal info for partial recovery
                    statement = SqlStatement(
                        sql_text=sql,
                        statement_type=SqlStatementType.UNKNOWN,
                        objects=[],
                        affected_objects=[],
                        dialect=self.dialect_name,
                        schema=default_schema or self.config.get_default_schema(),
                    )
                    statements.append(statement)

        except Exception as e:
            error_msg = f"Error splitting DB2 SQL: {str(e)}"
            logger.error(error_msg)
            errors.append(error_msg)

        # Return success if we got statements, even with some errors
        success = len(statements) > 0 or len(errors) == 0
        return ParseResult(success=success, statements=statements, errors=errors)

    def _clean_db2_comments(self, sql: str) -> str:
        """Clean DB2-specific comments from SQL."""
        # Remove -- comments
        sql = re.sub(r"--.*$", "", sql, flags=re.MULTILINE)

        # Remove /* */ comments
        sql = re.sub(r"/\*.*?\*/", "", sql, flags=re.DOTALL)

        # Remove SPUFI terminator comments but preserve for processing
        # Don't remove these as they're functional

        return sql

    def validate_sql(self, sql_content: str) -> Dict[str, Any]:
        """Validate DB2 SQL content.

        Args:
            sql_content: SQL content to validate

        Returns:
            Dictionary with validation results
        """
        try:
            # Parse the SQL
            result = self.parse_sql(sql_content)

            # Check for parsing errors
            if result.errors:
                return {
                    "valid": False,
                    "errors": result.errors,
                    "statement_count": len(result.statements) if result.statements else 0,
                }

            # Basic structural validation
            if not result.statements:
                return {
                    "valid": False,
                    "errors": ["No valid statements found"],
                    "statement_count": 0,
                }

            # Check for DB2-specific syntax issues
            db2_errors = []
            for stmt in result.statements:
                db2_errors.extend(self._validate_db2_syntax(stmt.sql_text))

            if db2_errors:
                return {
                    "valid": False,
                    "errors": db2_errors,
                    "statement_count": len(result.statements) if result.statements else 0,
                }

            return {
                "valid": True,
                "errors": [],
                "statement_count": len(result.statements) if result.statements else 0,
            }

        except Exception as e:
            return {
                "valid": False,
                "errors": [f"DB2 validation error: {str(e)}"],
                "statement_count": 0,
            }

    def _validate_db2_syntax(self, sql: str) -> List[str]:
        """Validate DB2-specific syntax."""
        errors = []

        # Check for unmatched quoted identifiers
        quote_count = sql.count('"')
        if quote_count % 2 != 0:
            errors.append("Unmatched quoted identifier")

        # Check for proper SQL/PL block structure
        if re.search(r"\bBEGIN\s+(?:ATOMIC|NOT\s+ATOMIC)\b", sql, re.IGNORECASE):
            begin_count = len(re.findall(r"\bBEGIN\b", sql, re.IGNORECASE))
            end_count = len(re.findall(r"\bEND\b", sql, re.IGNORECASE))
            if begin_count != end_count:
                errors.append("Unmatched BEGIN/END blocks in SQL/PL")

        # Check for EXEC SQL without END-EXEC
        if re.search(r"\bEXEC\s+SQL\b", sql, re.IGNORECASE):
            if not re.search(r"\bEND-EXEC\b", sql, re.IGNORECASE):
                errors.append("EXEC SQL block without END-EXEC")

        # Check for DB2-specific identifier conventions
        if re.search(r"[a-zA-Z_][a-zA-Z0-9_$#@]*", sql):
            # Valid DB2 identifier pattern
            pass

        return errors

    def is_utility_statement(self, sql: str) -> bool:
        """Check if SQL is a DB2 utility statement.

        Args:
            sql: SQL content to check

        Returns:
            True if it's a DB2 utility statement
        """
        return self.config.is_db2_utility_statement(sql)
