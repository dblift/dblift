"""DB2 dialect configuration for regex-based SQL parsing.

This module provides DB2-specific patterns and configuration for the regex parser,
extracted from DB2 grammar files and existing parser implementation.
"""

import re
from typing import Any, Dict, List, Optional, Pattern, Set

from core.sql_parser.dialects.base_config import DialectConfig


def _is_identifier_char(char: str) -> bool:
    """Whether ``char`` can continue a SQL identifier/keyword.

    Matches the identifier-continuation character set already used by
    ``BaseTokenizer._handle_keyword`` (``core/sql_parser/base_tokenizer.py``)
    so that a word-boundary check in one place doesn't drift from the same
    check elsewhere in the codebase.
    """
    return char.isalnum() or char in ("_", "$", "#")


_DB2_WHITESPACE = (" ", "\t", "\n", "\r", "\f", "\v")


def _is_db2_whitespace(char: str) -> bool:
    """Whether ``char`` is whitespace DB2's lexer treats as a token separator.

    Deliberately narrower than ``str.isspace()``, which also accepts Unicode
    whitespace (e.g. a non-breaking space, U+00A0) that real DB2 does not -
    ``END<NBSP>CASE`` is a syntax error on DB2 even though ``str.isspace()``
    considers U+00A0 a separator.
    """
    return char in _DB2_WHITESPACE


class DB2Config(DialectConfig):
    """DB2 dialect configuration with comprehensive regex patterns."""

    dialect_name = "db2"  # lint: allow-dialect-string: dialect dispatch

    def __init__(self) -> None:
        """Initialize DB2 dialect configuration."""
        super().__init__()  # type: ignore[no-untyped-call]
        self._compile_patterns()

    def _compile_patterns(self) -> None:
        """Compile all DB2-specific regex patterns."""
        self._ddl_patterns = self._compile_ddl_patterns()
        self._dml_patterns = self._compile_dml_patterns()
        self._query_patterns = self._compile_query_patterns()
        self._object_patterns = self._compile_object_patterns()
        self._comment_patterns = self._compile_comment_patterns()
        self._batch_separators = self._compile_batch_separators()

    def _compile_ddl_patterns(self) -> Dict[str, Pattern[str]]:
        """Compile DB2 DDL patterns."""
        return {
            # CREATE statements
            # Grammar-based: CREATE [GLOBAL TEMPORARY | AUXILIARY] TABLE
            # Note: DB2 z/OS grammar does not have IF NOT EXISTS for tables
            "create_table": re.compile(
                r"\b(?:CREATE)\s+(?:GLOBAL\s+TEMPORARY\s+|AUXILIARY\s+)?TABLE\s+(?:\"[^\"]+\"|[a-zA-Z0-9_$#@]+(?:\.[a-zA-Z0-9_$#@]+)?)",
                re.IGNORECASE,
            ),
            # Grammar-based: CREATE VIEW (no OR REPLACE or IF NOT EXISTS in DB2 z/OS grammar)
            "create_view": re.compile(
                r"\b(?:CREATE)\s+VIEW\s+(?:\"[^\"]+\"|[a-zA-Z0-9_$#@]+(?:\.[a-zA-Z0-9_$#@]+)?)",
                re.IGNORECASE,
            ),
            # Grammar-based: CREATE [TYPE n] [UNIQUE [WHERE NOT NULL]] INDEX
            # DB2-specific: TYPE 1/2 (deprecated), UNIQUE WHERE NOT NULL (partial unique indexes)
            "create_index": re.compile(
                r"\b(?:CREATE)\s+(?:TYPE\s+\d+\s+)?(?:UNIQUE(?:\s+WHERE\s+NOT\s+NULL)?\s+)?INDEX\s+(?:\"[^\"]+\"|[a-zA-Z0-9_$#@]+)\s+ON\s+(?:\"[^\"]+\"|[a-zA-Z0-9_$#@]+(?:\.[a-zA-Z0-9_$#@]+)?)",
                re.IGNORECASE,
            ),
            # Grammar-based: CREATE SEQUENCE (no OR REPLACE or IF NOT EXISTS)
            "create_sequence": re.compile(
                r"\b(?:CREATE)\s+SEQUENCE\s+(?:\"[^\"]+\"|[a-zA-Z0-9_$#@]+(?:\.[a-zA-Z0-9_$#@]+)?)",
                re.IGNORECASE,
            ),
            # Grammar-based: CREATE [OR REPLACE] PROCEDURE
            # Supports VERSION option and WRAPPED code
            "create_procedure": re.compile(
                r"\b(?:CREATE)\s+(?:OR\s+REPLACE\s+)?PROCEDURE\s+(?:\"[^\"]+\"|[a-zA-Z0-9_$#@]+(?:\.[a-zA-Z0-9_$#@]+)?)",
                re.IGNORECASE,
            ),
            # Grammar-based: CREATE FUNCTION (no OR REPLACE in DB2 z/OS)
            # Note: Functions don't support OR REPLACE per grammar, only procedures/triggers do
            "create_function": re.compile(
                r"\b(?:CREATE)\s+FUNCTION\s+(?:\"[^\"]+\"|[a-zA-Z0-9_$#@]+(?:\.[a-zA-Z0-9_$#@]+)?)",
                re.IGNORECASE,
            ),
            # Grammar-based: CREATE [OR REPLACE] TRIGGER
            # Advanced triggers support OR REPLACE
            "create_trigger": re.compile(
                r"\b(?:CREATE)\s+(?:OR\s+REPLACE\s+)?TRIGGER\s+(?:\"[^\"]+\"|[a-zA-Z0-9_$#@]+(?:\.[a-zA-Z0-9_$#@]+)?)",
                re.IGNORECASE,
            ),
            "create_database": re.compile(
                r"\b(?:CREATE)\s+DATABASE\s+(?:IF\s+NOT\s+EXISTS\s+)?(?:\"[^\"]+\"|[a-zA-Z0-9_$#@]+)",
                re.IGNORECASE,
            ),
            "create_tablespace": re.compile(
                r"\b(?:CREATE)\s+(?:LOB\s+)?TABLESPACE\s+(?:\"[^\"]+\"|[a-zA-Z0-9_$#@]+)",
                re.IGNORECASE,
            ),
            "create_stogroup": re.compile(
                r"\b(?:CREATE)\s+STOGROUP\s+(?:\"[^\"]+\"|[a-zA-Z0-9_$#@]+)", re.IGNORECASE
            ),
            "create_alias": re.compile(
                r"\b(?:CREATE)\s+ALIAS\s+(?:\"[^\"]+\"|[a-zA-Z0-9_$#@]+(?:\.[a-zA-Z0-9_$#@]+)?)",
                re.IGNORECASE,
            ),
            "create_role": re.compile(
                r"\b(?:CREATE)\s+ROLE\s+(?:\"[^\"]+\"|[a-zA-Z0-9_$#@]+)", re.IGNORECASE
            ),
            "create_mask": re.compile(
                r"\b(?:CREATE)\s+(?:OR\s+REPLACE\s+)?MASK\s+(?:\"[^\"]+\"|[a-zA-Z0-9_$#@]+(?:\.[a-zA-Z0-9_$#@]+)?)",
                re.IGNORECASE,
            ),
            "create_permission": re.compile(
                r"\b(?:CREATE)\s+(?:OR\s+REPLACE\s+)?PERMISSION\s+(?:\"[^\"]+\"|[a-zA-Z0-9_$#@]+(?:\.[a-zA-Z0-9_$#@]+)?)",
                re.IGNORECASE,
            ),
            "create_trusted_context": re.compile(
                r"\b(?:CREATE)\s+TRUSTED\s+CONTEXT\s+(?:\"[^\"]+\"|[a-zA-Z0-9_$#@]+)", re.IGNORECASE
            ),
            "create_type": re.compile(
                r"\b(?:CREATE)\s+(?:OR\s+REPLACE\s+)?TYPE\s+(?:\"[^\"]+\"|[a-zA-Z0-9_$#@]+(?:\.[a-zA-Z0-9_$#@]+)?)",
                re.IGNORECASE,
            ),
            "create_variable": re.compile(
                r"\b(?:CREATE)\s+(?:OR\s+REPLACE\s+)?VARIABLE\s+(?:\"[^\"]+\"|[a-zA-Z0-9_$#@]+(?:\.[a-zA-Z0-9_$#@]+)?)",
                re.IGNORECASE,
            ),
            "create_synonym": re.compile(
                r"\b(?:CREATE)\s+(?:OR\s+REPLACE\s+)?(?:SYNONYM|ALIAS)\s+(?:\"[^\"]+\"|[a-zA-Z0-9_$#@]+(?:\.[a-zA-Z0-9_$#@]+)?)",
                re.IGNORECASE,
            ),
            "create_module": re.compile(
                r"\b(?:CREATE)\s+(?:OR\s+REPLACE\s+)?MODULE\s+(?:\"[^\"]+\"|[a-zA-Z0-9_$#@]+(?:\.[a-zA-Z0-9_$#@]+)?)",
                re.IGNORECASE,
            ),
            "drop_module": re.compile(
                r"\b(?:DROP)\s+MODULE\s+(?:IF\s+EXISTS\s+)?(?:\"[^\"]+\"|[a-zA-Z0-9_$#@]+(?:\.[a-zA-Z0-9_$#@]+)?)",
                re.IGNORECASE,
            ),
            # ALTER statements
            "alter_table": re.compile(
                r"\b(?:ALTER)\s+TABLE\s+(?:\"[^\"]+\"|[a-zA-Z0-9_$#@]+(?:\.[a-zA-Z0-9_$#@]+)?)",
                re.IGNORECASE,
            ),
            "alter_view": re.compile(
                r"\b(?:ALTER)\s+VIEW\s+(?:\"[^\"]+\"|[a-zA-Z0-9_$#@]+(?:\.[a-zA-Z0-9_$#@]+)?)",
                re.IGNORECASE,
            ),
            "alter_index": re.compile(
                r"\b(?:ALTER)\s+INDEX\s+(?:\"[^\"]+\"|[a-zA-Z0-9_$#@]+(?:\.[a-zA-Z0-9_$#@]+)?)",
                re.IGNORECASE,
            ),
            "alter_sequence": re.compile(
                r"\b(?:ALTER)\s+SEQUENCE\s+(?:\"[^\"]+\"|[a-zA-Z0-9_$#@]+(?:\.[a-zA-Z0-9_$#@]+)?)",
                re.IGNORECASE,
            ),
            "alter_procedure": re.compile(
                r"\b(?:ALTER)\s+PROCEDURE\s+(?:\"[^\"]+\"|[a-zA-Z0-9_$#@]+(?:\.[a-zA-Z0-9_$#@]+)?)",
                re.IGNORECASE,
            ),
            "alter_function": re.compile(
                r"\b(?:ALTER)\s+FUNCTION\s+(?:\"[^\"]+\"|[a-zA-Z0-9_$#@]+(?:\.[a-zA-Z0-9_$#@]+)?)",
                re.IGNORECASE,
            ),
            "alter_trigger": re.compile(
                r"\b(?:ALTER)\s+TRIGGER\s+(?:\"[^\"]+\"|[a-zA-Z0-9_$#@]+(?:\.[a-zA-Z0-9_$#@]+)?)",
                re.IGNORECASE,
            ),
            "alter_database": re.compile(
                r"\b(?:ALTER)\s+DATABASE\s+(?:\"[^\"]+\"|[a-zA-Z0-9_$#@]+)", re.IGNORECASE
            ),
            "alter_tablespace": re.compile(
                r"\b(?:ALTER)\s+TABLESPACE\s+(?:\"[^\"]+\"|[a-zA-Z0-9_$#@]+)", re.IGNORECASE
            ),
            "alter_stogroup": re.compile(
                r"\b(?:ALTER)\s+STOGROUP\s+(?:\"[^\"]+\"|[a-zA-Z0-9_$#@]+)", re.IGNORECASE
            ),
            "alter_mask": re.compile(
                r"\b(?:ALTER)\s+MASK\s+(?:\"[^\"]+\"|[a-zA-Z0-9_$#@]+(?:\.[a-zA-Z0-9_$#@]+)?)",
                re.IGNORECASE,
            ),
            "alter_permission": re.compile(
                r"\b(?:ALTER)\s+PERMISSION\s+(?:\"[^\"]+\"|[a-zA-Z0-9_$#@]+(?:\.[a-zA-Z0-9_$#@]+)?)",
                re.IGNORECASE,
            ),
            "alter_trusted_context": re.compile(
                r"\b(?:ALTER)\s+TRUSTED\s+CONTEXT\s+(?:\"[^\"]+\"|[a-zA-Z0-9_$#@]+)", re.IGNORECASE
            ),
            # DROP statements
            "drop_table": re.compile(
                r"\b(?:DROP)\s+TABLE\s+(?:IF\s+EXISTS\s+)?(?:\"[^\"]+\"|[a-zA-Z0-9_$#@]+(?:\.[a-zA-Z0-9_$#@]+)?)",
                re.IGNORECASE,
            ),
            "drop_view": re.compile(
                r"\b(?:DROP)\s+VIEW\s+(?:IF\s+EXISTS\s+)?(?:\"[^\"]+\"|[a-zA-Z0-9_$#@]+(?:\.[a-zA-Z0-9_$#@]+)?)",
                re.IGNORECASE,
            ),
            "drop_index": re.compile(
                r"\b(?:DROP)\s+INDEX\s+(?:IF\s+EXISTS\s+)?(?:\"[^\"]+\"|[a-zA-Z0-9_$#@]+(?:\.[a-zA-Z0-9_$#@]+)?)",
                re.IGNORECASE,
            ),
            "drop_sequence": re.compile(
                r"\b(?:DROP)\s+SEQUENCE\s+(?:IF\s+EXISTS\s+)?(?:\"[^\"]+\"|[a-zA-Z0-9_$#@]+(?:\.[a-zA-Z0-9_$#@]+)?)",
                re.IGNORECASE,
            ),
            "drop_procedure": re.compile(
                r"\b(?:DROP)\s+PROCEDURE\s+(?:IF\s+EXISTS\s+)?(?:\"[^\"]+\"|[a-zA-Z0-9_$#@]+(?:\.[a-zA-Z0-9_$#@]+)?)",
                re.IGNORECASE,
            ),
            "drop_function": re.compile(
                r"\b(?:DROP)\s+FUNCTION\s+(?:IF\s+EXISTS\s+)?(?:\"[^\"]+\"|[a-zA-Z0-9_$#@]+(?:\.[a-zA-Z0-9_$#@]+)?)",
                re.IGNORECASE,
            ),
            "drop_trigger": re.compile(
                r"\b(?:DROP)\s+TRIGGER\s+(?:IF\s+EXISTS\s+)?(?:\"[^\"]+\"|[a-zA-Z0-9_$#@]+(?:\.[a-zA-Z0-9_$#@]+)?)",
                re.IGNORECASE,
            ),
            "drop_database": re.compile(
                r"\b(?:DROP)\s+DATABASE\s+(?:IF\s+EXISTS\s+)?(?:\"[^\"]+\"|[a-zA-Z0-9_$#@]+)",
                re.IGNORECASE,
            ),
            "drop_tablespace": re.compile(
                r"\b(?:DROP)\s+TABLESPACE\s+(?:IF\s+EXISTS\s+)?(?:\"[^\"]+\"|[a-zA-Z0-9_$#@]+)",
                re.IGNORECASE,
            ),
            "drop_stogroup": re.compile(
                r"\b(?:DROP)\s+STOGROUP\s+(?:IF\s+EXISTS\s+)?(?:\"[^\"]+\"|[a-zA-Z0-9_$#@]+)",
                re.IGNORECASE,
            ),
            "drop_alias": re.compile(
                r"\b(?:DROP)\s+ALIAS\s+(?:IF\s+EXISTS\s+)?(?:\"[^\"]+\"|[a-zA-Z0-9_$#@]+(?:\.[a-zA-Z0-9_$#@]+)?)",
                re.IGNORECASE,
            ),
            "drop_role": re.compile(
                r"\b(?:DROP)\s+ROLE\s+(?:IF\s+EXISTS\s+)?(?:\"[^\"]+\"|[a-zA-Z0-9_$#@]+)",
                re.IGNORECASE,
            ),
            "drop_mask": re.compile(
                r"\b(?:DROP)\s+MASK\s+(?:IF\s+EXISTS\s+)?(?:\"[^\"]+\"|[a-zA-Z0-9_$#@]+(?:\.[a-zA-Z0-9_$#@]+)?)",
                re.IGNORECASE,
            ),
            "drop_permission": re.compile(
                r"\b(?:DROP)\s+PERMISSION\s+(?:IF\s+EXISTS\s+)?(?:\"[^\"]+\"|[a-zA-Z0-9_$#@]+(?:\.[a-zA-Z0-9_$#@]+)?)",
                re.IGNORECASE,
            ),
            "drop_trusted_context": re.compile(
                r"\b(?:DROP)\s+TRUSTED\s+CONTEXT\s+(?:IF\s+EXISTS\s+)?(?:\"[^\"]+\"|[a-zA-Z0-9_$#@]+)",
                re.IGNORECASE,
            ),
            "drop_type": re.compile(
                r"\b(?:DROP)\s+TYPE\s+(?:IF\s+EXISTS\s+)?(?:\"[^\"]+\"|[a-zA-Z0-9_$#@]+(?:\.[a-zA-Z0-9_$#@]+)?)",
                re.IGNORECASE,
            ),
            "drop_variable": re.compile(
                r"\b(?:DROP)\s+VARIABLE\s+(?:IF\s+EXISTS\s+)?(?:\"[^\"]+\"|[a-zA-Z0-9_$#@]+(?:\.[a-zA-Z0-9_$#@]+)?)",
                re.IGNORECASE,
            ),
            "drop_synonym": re.compile(
                r"\b(?:DROP)\s+SYNONYM\s+(?:IF\s+EXISTS\s+)?(?:\"[^\"]+\"|[a-zA-Z0-9_$#@]+(?:\.[a-zA-Z0-9_$#@]+)?)",
                re.IGNORECASE,
            ),
            # Other DDL statements
            "truncate_table": re.compile(
                r"\b(?:TRUNCATE)\s+(?:TABLE\s+)?(?:\"[^\"]+\"|[a-zA-Z0-9_$#@]+(?:\.[a-zA-Z0-9_$#@]+)?)",
                re.IGNORECASE,
            ),
            "comment": re.compile(
                r"\b(?:COMMENT)\s+ON\s+(?:TABLE|VIEW|COLUMN|INDEX|SEQUENCE|PROCEDURE|FUNCTION|TRIGGER)\s+",
                re.IGNORECASE,
            ),
            "grant": re.compile(r"\b(?:GRANT)\s+", re.IGNORECASE),
            "revoke": re.compile(r"\b(?:REVOKE)\s+", re.IGNORECASE),
        }

    def _compile_dml_patterns(self) -> Dict[str, Pattern[str]]:
        """Compile DB2 DML patterns."""
        return {
            "insert": re.compile(
                r"\b(?:INSERT)\s+(?:INTO\s+)?(?:\"[^\"]+\"|[a-zA-Z0-9_$#@]+(?:\.[a-zA-Z0-9_$#@]+)?)",
                re.IGNORECASE,
            ),
            "update": re.compile(
                r"\b(?:UPDATE)\s+(?:\"[^\"]+\"|[a-zA-Z0-9_$#@]+(?:\.[a-zA-Z0-9_$#@]+)?)",
                re.IGNORECASE,
            ),
            "delete": re.compile(
                r"\b(?:DELETE)\s+(?:FROM\s+)?(?:\"[^\"]+\"|[a-zA-Z0-9_$#@]+(?:\.[a-zA-Z0-9_$#@]+)?)",
                re.IGNORECASE,
            ),
            "merge": re.compile(
                r"\b(?:MERGE)\s+(?:INTO\s+)?(?:\"[^\"]+\"|[a-zA-Z0-9_$#@]+(?:\.[a-zA-Z0-9_$#@]+)?)",
                re.IGNORECASE,
            ),
            "call": re.compile(
                r"\b(?:CALL)\s+(?:\"[^\"]+\"|[a-zA-Z0-9_$#@]+(?:\.[a-zA-Z0-9_$#@]+)?)",
                re.IGNORECASE,
            ),
            "set": re.compile(r"\b(?:SET)\s+(?:\"[^\"]+\"|[a-zA-Z0-9_$#@]+)", re.IGNORECASE),
            "values": re.compile(r"\b(?:VALUES)\s+", re.IGNORECASE),
        }

    def _compile_query_patterns(self) -> Dict[str, Pattern[str]]:
        """Compile DB2 query patterns."""
        return {
            "select": re.compile(r"\b(?:SELECT)\s+(?:DISTINCT\s+|ALL\s+)?", re.IGNORECASE),
            "with": re.compile(r"\b(?:WITH)\s+(?:RECURSIVE\s+)?", re.IGNORECASE),
            "explain": re.compile(r"\b(?:EXPLAIN)\s+(?:PLAN\s+)?(?:FOR\s+)?", re.IGNORECASE),
            "describe": re.compile(
                r"\b(?:DESCRIBE)\s+(?:TABLE\s+)?(?:\"[^\"]+\"|[a-zA-Z0-9_$#@]+(?:\.[a-zA-Z0-9_$#@]+)?)",
                re.IGNORECASE,
            ),
            "show": re.compile(r"\b(?:SHOW)\s+", re.IGNORECASE),
        }

    def _compile_object_patterns(self) -> Dict[str, Pattern[str]]:
        """Compile DB2 object extraction patterns."""
        return {
            "table": re.compile(
                r"\b(?:CREATE|DROP|ALTER)\s+(?:GLOBAL\s+TEMPORARY\s+|AUXILIARY\s+)?TABLE\s+(?:IF\s+(?:NOT\s+)?EXISTS\s+)?(?:(?:\"([^\"]+)\")|([a-zA-Z0-9_$#@]+))(?:\.(?:(?:\"([^\"]+)\")|([a-zA-Z0-9_$#@]+)))?",
                re.IGNORECASE,
            ),
            "view": re.compile(
                r"\b(?:CREATE|DROP|ALTER)\s+(?:OR\s+REPLACE\s+)?VIEW\s+(?:IF\s+(?:NOT\s+)?EXISTS\s+)?(?:(?:\"([^\"]+)\")|([a-zA-Z0-9_$#@]+))(?:\.(?:(?:\"([^\"]+)\")|([a-zA-Z0-9_$#@]+)))?",
                re.IGNORECASE,
            ),
            "index": re.compile(
                r"\b(?:CREATE|DROP|ALTER)\s+(?:UNIQUE\s+)?INDEX\s+(?:IF\s+(?:NOT\s+)?EXISTS\s+)?(?:(?:\"([^\"]+)\")|([a-zA-Z0-9_$#@]+))(?:\s+ON\s+(?:(?:\"([^\"]+)\")|([a-zA-Z0-9_$#@]+))(?:\.(?:(?:\"([^\"]+)\")|([a-zA-Z0-9_$#@]+)))?)?",
                re.IGNORECASE,
            ),
            "sequence": re.compile(
                r"\b(?:CREATE|DROP|ALTER)\s+(?:OR\s+REPLACE\s+)?SEQUENCE\s+(?:IF\s+(?:NOT\s+)?EXISTS\s+)?(?:(?:\"([^\"]+)\")|([a-zA-Z0-9_$#@]+))(?:\.(?:(?:\"([^\"]+)\")|([a-zA-Z0-9_$#@]+)))?",
                re.IGNORECASE,
            ),
            "procedure": re.compile(
                r"\b(?:CREATE|DROP|ALTER)\s+(?:OR\s+REPLACE\s+)?PROCEDURE\s+(?:IF\s+(?:NOT\s+)?EXISTS\s+)?(?:(?:\"([^\"]+)\")|([a-zA-Z0-9_$#@]+))(?:\.(?:(?:\"([^\"]+)\")|([a-zA-Z0-9_$#@]+)))?",
                re.IGNORECASE,
            ),
            "function": re.compile(
                r"\b(?:CREATE|DROP|ALTER)\s+(?:OR\s+REPLACE\s+)?FUNCTION\s+(?:IF\s+(?:NOT\s+)?EXISTS\s+)?(?:(?:\"([^\"]+)\")|([a-zA-Z0-9_$#@]+))(?:\.(?:(?:\"([^\"]+)\")|([a-zA-Z0-9_$#@]+)))?",
                re.IGNORECASE,
            ),
            "trigger": re.compile(
                r"\b(?:CREATE|DROP|ALTER)\s+(?:OR\s+REPLACE\s+)?TRIGGER\s+(?:IF\s+(?:NOT\s+)?EXISTS\s+)?(?:(?:\"([^\"]+)\")|([a-zA-Z0-9_$#@]+))(?:\.(?:(?:\"([^\"]+)\")|([a-zA-Z0-9_$#@]+)))?",
                re.IGNORECASE,
            ),
            "database": re.compile(
                r"\b(?:CREATE|DROP|ALTER)\s+DATABASE\s+(?:IF\s+(?:NOT\s+)?EXISTS\s+)?(?:(?:\"([^\"]+)\")|([a-zA-Z0-9_$#@]+))",
                re.IGNORECASE,
            ),
            "tablespace": re.compile(
                r"\b(?:CREATE|DROP|ALTER)\s+(?:LOB\s+)?TABLESPACE\s+(?:(?:\"([^\"]+)\")|([a-zA-Z0-9_$#@]+))",
                re.IGNORECASE,
            ),
            "stogroup": re.compile(
                r"\b(?:CREATE|DROP|ALTER)\s+STOGROUP\s+(?:(?:\"([^\"]+)\")|([a-zA-Z0-9_$#@]+))",
                re.IGNORECASE,
            ),
            "alias": re.compile(
                r"\b(?:CREATE|DROP)\s+ALIAS\s+(?:(?:\"([^\"]+)\")|([a-zA-Z0-9_$#@]+))(?:\.(?:(?:\"([^\"]+)\")|([a-zA-Z0-9_$#@]+)))?",
                re.IGNORECASE,
            ),
            "role": re.compile(
                r"\b(?:CREATE|DROP)\s+ROLE\s+(?:(?:\"([^\"]+)\")|([a-zA-Z0-9_$#@]+))", re.IGNORECASE
            ),
            "mask": re.compile(
                r"\b(?:CREATE|DROP|ALTER)\s+(?:OR\s+REPLACE\s+)?MASK\s+(?:(?:\"([^\"]+)\")|([a-zA-Z0-9_$#@]+))(?:\.(?:(?:\"([^\"]+)\")|([a-zA-Z0-9_$#@]+)))?",
                re.IGNORECASE,
            ),
            "permission": re.compile(
                r"\b(?:CREATE|DROP|ALTER)\s+(?:OR\s+REPLACE\s+)?PERMISSION\s+(?:(?:\"([^\"]+)\")|([a-zA-Z0-9_$#@]+))(?:\.(?:(?:\"([^\"]+)\")|([a-zA-Z0-9_$#@]+)))?",
                re.IGNORECASE,
            ),
            "trusted_context": re.compile(
                r"\b(?:CREATE|DROP|ALTER)\s+TRUSTED\s+CONTEXT\s+(?:(?:\"([^\"]+)\")|([a-zA-Z0-9_$#@]+))",
                re.IGNORECASE,
            ),
            "type": re.compile(
                r"\b(?:CREATE|DROP)\s+(?:OR\s+REPLACE\s+)?TYPE\s+(?:(?:\"([^\"]+)\")|([a-zA-Z0-9_$#@]+))(?:\.(?:(?:\"([^\"]+)\")|([a-zA-Z0-9_$#@]+)))?",
                re.IGNORECASE,
            ),
            "variable": re.compile(
                r"\b(?:CREATE|DROP)\s+(?:OR\s+REPLACE\s+)?VARIABLE\s+(?:(?:\"([^\"]+)\")|([a-zA-Z0-9_$#@]+))(?:\.(?:(?:\"([^\"]+)\")|([a-zA-Z0-9_$#@]+)))?",
                re.IGNORECASE,
            ),
            "synonym": re.compile(
                r"\b(?:CREATE|DROP)\s+(?:OR\s+REPLACE\s+)?SYNONYM\s+(?:(?:\"([^\"]+)\")|([a-zA-Z0-9_$#@]+))(?:\.(?:(?:\"([^\"]+)\")|([a-zA-Z0-9_$#@]+)))?",
                re.IGNORECASE,
            ),
        }

    def _compile_comment_patterns(self) -> List[Pattern[str]]:
        """Compile DB2 comment patterns."""
        return [
            # Single-line comments with --
            re.compile(r"--.*$", re.MULTILINE),
            # Multi-line comments /* ... */
            re.compile(r"/\*.*?\*/", re.DOTALL),
            # SPUFI terminator comments
            re.compile(r"--#SET\s+TERMINATOR.*$", re.MULTILINE | re.IGNORECASE),
        ]

    def _compile_batch_separators(self) -> List[Pattern[str]]:
        """Compile DB2 batch separator patterns."""
        return [
            # SQL statement terminators
            re.compile(r";\s*$", re.MULTILINE),
            # SPUFI terminator customization
            re.compile(r"--#SET\s+TERMINATOR\s+(\S)", re.IGNORECASE),
            # SQL/PL statement terminators
            re.compile(r"SQL_STATEMENT_TERMINATOR", re.IGNORECASE),
        ]

    @property
    def name(self) -> str:
        """Dialect name."""
        return self.dialect_name

    @property
    def ddl_patterns(self) -> Dict[str, Pattern[str]]:
        """DDL statement regex patterns."""
        return self._ddl_patterns

    @property
    def dml_patterns(self) -> Dict[str, Pattern[str]]:
        """DML statement regex patterns."""
        return self._dml_patterns

    @property
    def query_patterns(self) -> Dict[str, Pattern[str]]:
        """Query statement regex patterns."""
        return self._query_patterns

    @property
    def object_patterns(self) -> Dict[str, Pattern[str]]:
        """Object extraction regex patterns."""
        return self._object_patterns

    @property
    def comment_patterns(self) -> List[Pattern[str]]:
        """Regex patterns for comments."""
        return self._comment_patterns

    @property
    def batch_separators(self) -> List[Pattern[str]]:
        """Regex patterns for batch separators."""
        return self._batch_separators

    @property
    def quoted_identifiers(self) -> List[Pattern[str]]:
        """Regex patterns for quoted identifiers."""
        return [re.compile(r"\"([^\"]+)\"")]

    @property
    def block_keywords(self) -> List[str]:
        """Keywords that start block statements (procedures, functions, etc.)."""
        return [
            "BEGIN",
            "END",
            "DECLARE",
            "IF",
            "THEN",
            "ELSE",
            "ELSEIF",
            "ENDIF",
            "WHILE",
            "FOR",
            "LOOP",
            "REPEAT",
            "UNTIL",
            "CASE",
            "WHEN",
            "ATOMIC",
            "NOT ATOMIC",
            "COMPOUND",
            "SIGNAL",
            "RESIGNAL",
            "CONTINUE",
            "EXIT",
            "UNDO",
            "GOTO",
            "ITERATE",
            "LEAVE",
            "SQLPL",
            "LANGUAGE SQL",
            "WRAPPED",
        ]

    def get_default_schema(self) -> str:
        """Get default schema name for DB2."""
        return "SYSIBM"

    def normalize_identifier(self, identifier: str, is_quoted: bool = False) -> str:
        """Normalize DB2 identifier according to dialect rules.

        Args:
            identifier: Raw identifier string
            is_quoted: Whether the identifier was quoted

        Returns:
            Normalized identifier
        """
        if not identifier:
            return identifier

        # Remove quotes if present
        if identifier.startswith('"') and identifier.endswith('"'):
            identifier = identifier[1:-1]
            is_quoted = True

        # DB2 identifiers are case-insensitive unless quoted
        if not is_quoted:
            identifier = identifier.upper()

        return identifier

    def _find_block_end(self, sql: str, begin_pos: int) -> Optional[int]:
        """Find where the BEGIN block opened at ``begin_pos`` closes.

        Scans forward counting nested ``BEGIN``/``END`` pairs, ignoring string
        literals and comments, and skipping ``END`` keywords that close a
        control structure (``END IF``, ``END WHILE``, ``END LOOP``, ...) or a
        ``CASE`` expression rather than a block.

        A regex cannot express "the ``END`` that closes *this* block" — a lazy
        match stops at the first candidate and a greedy one runs to the last —
        so every caller that needs a block's real boundary uses this scan.

        Args:
            sql: SQL content being scanned
            begin_pos: Offset of the ``BEGIN`` keyword that opens the block

        Returns:
            Offset just past the block, including the trailing ``@`` or ``;``
            when one is present, or None if the block is never closed.
        """
        i = begin_pos + 5  # Start after "BEGIN"
        depth = 1
        case_depth = 0  # Track CASE expressions separately
        in_string = False
        comment_depth = 0  # DB2 block comments nest; see /* below
        string_char = None

        while i < len(sql) and depth > 0:
            # Handle string literals
            if comment_depth == 0:
                if not in_string and sql[i] in ("'", '"'):
                    in_string = True
                    string_char = sql[i]
                elif in_string and sql[i] == string_char:
                    # Check for escaped quotes
                    if i + 1 < len(sql) and sql[i + 1] == string_char:
                        i += 2
                        continue
                    in_string = False
                    string_char = None

            # Handle comments
            if not in_string:
                if sql[i : i + 2] == "--" and comment_depth == 0:
                    # Line comment - skip to end of line
                    while i < len(sql) and sql[i] not in ("\n", "\r"):
                        i += 1
                    continue
                elif sql[i : i + 2] == "/*":
                    # Block comment. DB2 nests these (confirmed live: a
                    # /* /* */ */ pair only closes at the balancing outer
                    # */, and content in between - even a bare -- line -
                    # stays comment text), so every /* opens another level
                    # regardless of whether one is already open.
                    comment_depth += 1
                    i += 2
                    continue
                elif sql[i : i + 2] == "*/" and comment_depth > 0:
                    comment_depth -= 1
                    i += 2
                    continue

            # Count BEGIN/END and CASE/END pairs outside strings and comments
            if not in_string and comment_depth == 0:
                # Check for CASE keyword (starts a CASE expression)
                if sql[i : i + 4].upper() == "CASE":
                    if (i == 0 or not _is_identifier_char(sql[i - 1])) and (
                        i + 4 >= len(sql) or not _is_identifier_char(sql[i + 4])
                    ):
                        case_depth += 1
                        i += 4
                        continue
                # Check for BEGIN keyword
                elif sql[i : i + 5].upper() == "BEGIN":
                    # Make sure it's a word boundary
                    if (i == 0 or not _is_identifier_char(sql[i - 1])) and (
                        i + 5 >= len(sql) or not _is_identifier_char(sql[i + 5])
                    ):
                        depth += 1
                        i += 5
                        continue
                elif sql[i : i + 3].upper() == "END":
                    # Make sure it's a word boundary on both sides of END -
                    # otherwise an identifier that merely *starts* with the
                    # letters END ("ENDDATE", "END_IF", "ENDPOINT", ...) has
                    # its first 3 characters mistaken for a genuine closing
                    # END token, mirroring the BEGIN/CASE-open checks above.
                    if (i == 0 or not _is_identifier_char(sql[i - 1])) and (
                        i + 3 >= len(sql) or not _is_identifier_char(sql[i + 3])
                    ):
                        # Check what comes after END
                        # Skip whitespace after END. A comment (-- or /* */)
                        # between END and the control keyword is not skipped
                        # here and is out of scope for this lookahead - it
                        # falls through to being treated as a block-closing
                        # END, same as before this fix.
                        j = i + 3
                        while j < len(sql) and _is_db2_whitespace(sql[j]):
                            j += 1

                        # Check if this is "END IF", "END WHILE", "END FOR", "END LOOP", "END CASE", etc.
                        # These are control structure endings, not block endings
                        is_control_end = False
                        if j < len(sql):
                            next_word_upper = ""
                            k = j
                            while k < len(sql) and sql[k].isalpha():
                                next_word_upper += sql[k].upper()
                                k += 1

                            # Control structure keywords that follow END
                            if next_word_upper in (
                                "IF",
                                "WHILE",
                                "FOR",
                                "LOOP",
                                "CASE",
                                "REPEAT",
                            ) and (k >= len(sql) or not _is_identifier_char(sql[k])):
                                is_control_end = True
                                # Special case: END CASE decrements case_depth
                                if next_word_upper == "CASE":
                                    case_depth -= 1

                        # Check if this END matches a CASE expression (not END CASE)
                        # A CASE expression is a *scalar expression*, so its closing
                        # END can be legally followed by almost anything a SQL
                        # expression permits (INTO, AS, FROM, an alias, ), ,, ;, or
                        # end of input) - there is no fixed set of continuation
                        # tokens to allow-list. The only ENDs that do NOT close the
                        # innermost open CASE are the control-structure endings
                        # already recognised above (END IF, END WHILE, END CASE,
                        # ...), so once those are ruled out, any END while a CASE is
                        # still open must be that CASE's own END.
                        is_case_expression_end = False
                        if not is_control_end and case_depth > 0:
                            case_depth -= 1
                            is_case_expression_end = True

                        # Only count as block END if it's not a control structure end or CASE expression end
                        if not is_control_end and not is_case_expression_end:
                            depth -= 1
                            if depth == 0:
                                # Found the matching END, now look for delimiter (@ or ;)
                                j = i + 3
                                while j < len(sql) and _is_db2_whitespace(sql[j]):
                                    j += 1

                                # Accept either @ or ; as delimiter
                                if j < len(sql) and sql[j] in ("@", ";"):
                                    return j + 1
                                # No explicit delimiter, use position after END
                                return j
                        if is_control_end:
                            # Advance past the entire matched keyword (e.g. "CASE"),
                            # not just "END". Otherwise the next scan iteration
                            # re-reads that keyword as a fresh token - and for CASE,
                            # which also has a generic open detector above, that
                            # means re-matching it as a brand-new CASE expression
                            # and double-counting case_depth for a CASE that
                            # already closed, poisoning the depth state used to
                            # find the enclosing block's own terminating END.
                            i = k
                        else:
                            i += 3
                        continue

            i += 1

        return None

    def extract_sqlpl_blocks(self, sql: str) -> List[Dict[str, Any]]:
        """Extract SQL/PL blocks from SQL content.

        Args:
            sql: SQL content to parse

        Returns:
            List of SQL/PL blocks with their content
        """
        blocks = []

        # Pattern to find the start of SQL/PL procedures and functions
        start_pattern = re.compile(
            r"\b(?:CREATE|ALTER)\s+(?:OR\s+REPLACE\s+)?(?:PROCEDURE|FUNCTION)\s+", re.IGNORECASE
        )

        for start_match in start_pattern.finditer(sql):
            start_pos = start_match.start()

            # Find the BEGIN keyword after the start
            begin_match = re.search(r"\bBEGIN\b", sql[start_pos:], re.IGNORECASE)
            if not begin_match:
                continue

            end_pos = self._find_block_end(sql, start_pos + begin_match.start())
            if end_pos is None:
                continue

            blocks.append(
                {
                    "type": "sqlpl_block",
                    "content": sql[start_pos:end_pos].rstrip("@;").strip(),
                    "start": start_pos,
                    "end": end_pos,
                }
            )

        return blocks

    def extract_compound_statements(self, sql: str) -> List[Dict[str, Any]]:
        """Extract compound statements from SQL content.

        Args:
            sql: SQL content to parse

        Returns:
            List of compound statements with their content
        """
        blocks = []

        # The span returned here is what the splitter cuts on, so the closing END
        # has to be the one that actually belongs to this block. Match only the
        # opening keyword and count depth from there — a pattern reaching for the
        # END itself either stops at a nested one or runs past the block.
        start_pattern = re.compile(r"\bBEGIN\s+(?:ATOMIC|NOT\s+ATOMIC)\b", re.IGNORECASE)

        search_from = 0
        for match in start_pattern.finditer(sql):
            # Skip BEGIN ATOMIC blocks nested inside one already extracted, so the
            # blocks stay ordered and non-overlapping for the caller.
            if match.start() < search_from:
                continue

            end_pos = self._find_block_end(sql, match.start())
            if end_pos is None:
                continue

            blocks.append(
                {
                    "type": "compound_statement",
                    "content": sql[match.start() : end_pos].rstrip(";@").strip(),
                    "start": match.start(),
                    "end": end_pos,
                }
            )
            search_from = end_pos

        return blocks

    def extract_trigger_blocks(self, sql: str) -> List[Dict[str, Any]]:
        """Extract trigger blocks from SQL content.

        Args:
            sql: SQL content to parse

        Returns:
            List of trigger blocks with their content
        """
        blocks = []

        # Pattern to find the start of a trigger statement
        trigger_start_pattern = re.compile(
            r"\b(?:CREATE|ALTER)\s+(?:OR\s+REPLACE\s+)?TRIGGER\s+",
            re.IGNORECASE,
        )

        # Find all trigger starts
        for match in trigger_start_pattern.finditer(sql):
            start_pos = match.start()

            # Find the BEGIN keyword after the trigger start. ATOMIC is
            # optional here: confirmed live against DB2 12.1.5.0, a trigger
            # body opened with plain BEGIN (no ATOMIC) compiles and fires
            # correctly, so requiring the literal keyword ATOMIC (as this
            # used to) silently skipped every trigger that didn't have it,
            # falling back to naive semicolon splitting for the whole thing.
            begin_match = re.search(r"\bBEGIN\b", sql[start_pos:], re.IGNORECASE)

            if not begin_match:
                continue

            # Use the shared depth-counting scan so a trigger body gets the same
            # control-structure lookahead (END IF, END WHILE, CASE...END, ...) as
            # procedures and compound statements - a private copy of this scan
            # previously decremented depth on any END, truncating trigger bodies
            # that contained a control structure like IF ... END IF.
            begin_pos = start_pos + begin_match.start()
            end_pos = self._find_block_end(sql, begin_pos)
            if end_pos is None:
                continue

            content = sql[start_pos:end_pos].rstrip("@;").strip()
            blocks.append(
                {
                    "type": "trigger_block",
                    "content": content,
                    "start": start_pos,
                    "end": end_pos,
                }
            )

        return blocks

    def is_db2_utility_statement(self, sql: str) -> bool:
        """Check if SQL is a DB2 utility statement.

        Args:
            sql: SQL content to check

        Returns:
            True if it's a DB2 utility statement
        """
        utility_keywords = [
            "DSNUTILX",
            "DSNUTILU",
            "DSNUTILC",
            "DSNUTILP",
            "REORG",
            "RUNSTATS",
            "BIND",
            "REBIND",
            "COPY",
            "RECOVER",
            "REPAIR",
            "LOAD",
            "UNLOAD",
            "CHECK",
        ]

        sql_upper = sql.upper()
        return any(keyword in sql_upper for keyword in utility_keywords)

    def extract_module_blocks(self, sql: str) -> List[Dict[str, Any]]:
        """Extract DB2 module blocks (CREATE MODULE ... END MODULE).

        DB2 LUW modules are compound statements containing procedures, functions,
        and variables. The entire module must be treated as a single statement.

        Args:
            sql: SQL content to parse

        Returns:
            List of module blocks with their content
        """
        blocks = []

        # Pattern to find CREATE MODULE statements
        # Modules end with "END MODULE" not just "END"
        pattern = re.compile(
            r"\bCREATE\s+(?:OR\s+REPLACE\s+)?MODULE\s+.*?\bEND\s+MODULE\s*;?",
            re.IGNORECASE | re.DOTALL,
        )

        for match in pattern.finditer(sql):
            content = match.group(0).strip()
            blocks.append(
                {
                    "type": "module",
                    "content": content,
                    "start": match.start(),
                    "end": match.end(),
                }
            )

        return blocks

    def extract_exec_sql_blocks(self, sql: str) -> List[Dict[str, Any]]:
        """Extract EXEC SQL blocks from SQL content.

        Args:
            sql: SQL content to parse

        Returns:
            List of EXEC SQL blocks with their content
        """
        blocks = []

        # Pattern to match EXEC SQL ... END-EXEC blocks
        exec_sql_pattern = re.compile(r"\bEXEC\s+SQL\s+(.*?)\s+END-EXEC", re.IGNORECASE | re.DOTALL)

        matches = exec_sql_pattern.finditer(sql)
        for match in matches:
            blocks.append(
                {
                    "type": "exec_sql_block",
                    "content": match.group(1).strip(),
                    "start": match.start(),
                    "end": match.end(),
                }
            )

        return blocks

    def split_statements(self, sql: str) -> List[str]:
        """Split SQL into individual statements, handling procedures/functions with BEGIN/END blocks.

        Args:
            sql: SQL script containing multiple statements

        Returns:
            List of individual SQL statements
        """
        statements = []

        # Extract SQL/PL blocks (procedures and functions with BEGIN/END)
        sqlpl_blocks = self.extract_sqlpl_blocks(sql)

        # Extract trigger blocks
        trigger_blocks = self.extract_trigger_blocks(sql)

        # Extract module blocks (DB2 LUW - CREATE MODULE ... END MODULE)
        module_blocks = self.extract_module_blocks(sql)

        # Combine all blocks and sort by position
        all_blocks = sqlpl_blocks + trigger_blocks + module_blocks
        all_blocks.sort(key=lambda b: b["start"])

        # Track which parts of the SQL have been processed
        processed_ranges = []
        for block in all_blocks:
            processed_ranges.append((block["start"], block["end"]))
            statements.append(block["content"])

        # Now process the remaining SQL (non-block statements)
        remaining_sql = ""
        last_end = 0

        for start, end in processed_ranges:
            if start > last_end:
                remaining_sql += sql[last_end:start]
            last_end = end

        # Add any remaining SQL after the last block
        if last_end < len(sql):
            remaining_sql += sql[last_end:]

        # Split the remaining SQL by semicolons (simple statements)
        if remaining_sql.strip():
            # Split by semicolons, but be careful with strings and comments
            remaining_statements = self._split_simple_statements(remaining_sql)
            statements.extend(remaining_statements)

        # Filter out empty statements
        statements = [s.strip() for s in statements if s.strip()]

        return statements

    def _split_simple_statements(self, sql: str) -> List[str]:
        """Split simple SQL statements by semicolons, handling strings and comments.

        Args:
            sql: SQL content without complex blocks

        Returns:
            List of individual statements
        """
        statements = []
        current_statement = []
        i = 0
        in_string = False
        string_char = None
        in_line_comment = False
        in_block_comment = False

        while i < len(sql):
            char = sql[i]

            # Handle line comments
            if not in_string and not in_block_comment and sql[i : i + 2] == "--":
                in_line_comment = True
                current_statement.append(char)
                i += 1
                continue

            if in_line_comment:
                current_statement.append(char)
                if char in ("\n", "\r"):
                    in_line_comment = False
                i += 1
                continue

            # Handle block comments
            if not in_string and not in_line_comment and sql[i : i + 2] == "/*":
                in_block_comment = True
                current_statement.append(char)
                i += 1
                continue

            if in_block_comment:
                current_statement.append(char)
                if sql[i : i + 2] == "*/":
                    in_block_comment = False
                    current_statement.append(sql[i + 1])
                    i += 2
                    continue
                i += 1
                continue

            # Handle strings
            if not in_line_comment and not in_block_comment:
                if not in_string and char in ("'", '"'):
                    in_string = True
                    string_char = char
                    current_statement.append(char)
                    i += 1
                    continue

                if in_string:
                    current_statement.append(char)
                    if char == string_char:
                        # Check for escaped quote
                        if i + 1 < len(sql) and sql[i + 1] == string_char:
                            current_statement.append(sql[i + 1])
                            i += 2
                            continue
                        in_string = False
                        string_char = None
                    i += 1
                    continue

            # Handle semicolon as statement separator
            if char == ";" and not in_string and not in_line_comment and not in_block_comment:
                # End of statement
                stmt = "".join(current_statement).strip()
                if stmt:
                    statements.append(stmt)
                current_statement = []
                i += 1
                continue

            # Regular character
            current_statement.append(char)
            i += 1

        # Add the last statement if there's anything left
        stmt = "".join(current_statement).strip()
        if stmt:
            statements.append(stmt)

        return statements

    # Abstract method implementations
    def get_ddl_keywords(self) -> Set[str]:
        """Get DDL keywords for DB2."""
        return {
            "CREATE",
            "ALTER",
            "DROP",
            "TRUNCATE",
            "COMMENT",
            "GRANT",
            "REVOKE",
            "TABLE",
            "VIEW",
            "INDEX",
            "SEQUENCE",
            "PROCEDURE",
            "FUNCTION",
            "TRIGGER",
            "DATABASE",
            "TABLESPACE",
            "STOGROUP",
            "ALIAS",
            "ROLE",
            "MASK",
            "PERMISSION",
            "TRUSTED",
            "CONTEXT",
            "TYPE",
            "VARIABLE",
            "SYNONYM",
            "MODULE",
            "PACKAGE",
        }

    def get_dml_keywords(self) -> Set[str]:
        """Get DML keywords for DB2."""
        return {"INSERT", "UPDATE", "DELETE", "MERGE", "CALL", "SET", "VALUES"}

    def get_query_keywords(self) -> Set[str]:
        """Get query keywords for DB2."""
        return {"SELECT", "WITH", "EXPLAIN", "DESCRIBE", "SHOW"}

    def get_identifier_pattern(self) -> Pattern[str]:
        """Get regex pattern for DB2 identifiers."""
        # DB2 supports quoted identifiers with double quotes
        return re.compile(r'(?:"[^"]+"|[a-zA-Z_][a-zA-Z0-9_$#@]*)', re.IGNORECASE)

    def get_qualified_identifier_pattern(self) -> Pattern[str]:
        """Get regex pattern for qualified identifiers (schema.table)."""
        identifier = r'(?:"[^"]+"|[a-zA-Z_][a-zA-Z0-9_$#@]*)'
        return re.compile(rf"(?:{identifier}\\.)?{identifier}", re.IGNORECASE)

    def get_string_literal_pattern(self) -> Pattern[str]:
        """Get regex pattern for string literals."""
        return re.compile(r"'([^']|'')*'", re.IGNORECASE)

    def get_comment_pattern(self) -> Pattern[str]:
        """Get regex pattern for comments."""
        return re.compile(r"(?:--.*$|/\*.*?\*/)", re.MULTILINE | re.DOTALL)

    def get_statement_separator_pattern(self) -> Pattern[str]:
        """Get regex pattern for statement separators."""
        return re.compile(r";\s*$", re.MULTILINE)

    def is_ddl_statement(self, statement: str) -> bool:
        """Check if statement is a DDL statement."""
        statement_upper = statement.strip().upper()
        ddl_keywords = self.get_ddl_keywords()
        first_words = statement_upper.split()[:2]
        return any(word in ddl_keywords for word in first_words if word)

    def is_dml_statement(self, statement: str) -> bool:
        """Check if statement is a DML statement."""
        statement_upper = statement.strip().upper()
        dml_keywords = self.get_dml_keywords()
        words = statement_upper.split()
        first_word = words[0] if words else ""
        return first_word in dml_keywords

    def is_query_statement(self, statement: str) -> bool:
        """Check if statement is a query statement."""
        statement_upper = statement.strip().upper()
        query_keywords = self.get_query_keywords()
        words = statement_upper.split()
        first_word = words[0] if words else ""
        return first_word in query_keywords

    def get_batch_separator(self) -> str:
        """Get batch separator for DB2."""
        return ";"

    def supports_block_comments(self) -> bool:
        """Check if DB2 supports block comments."""
        return True

    def supports_line_comments(self) -> bool:
        """Check if DB2 supports line comments."""
        return True
