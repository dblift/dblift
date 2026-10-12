"""DB2 dialect configuration for regex-based SQL parsing.

This module provides DB2-specific patterns and configuration for the regex parser,
extracted from DB2 grammar files and existing parser implementation.
"""

import re
from typing import Dict, List, Pattern, Set

from dblift.core.sql_parser.dialects.base_config import DialectConfig
from dblift.core.sql_parser.dialects.identifier_tokens import (
    DOUBLE_QUOTED_IDENTIFIER,
    strip_identifier_quotes,
)

# A double-quoted identifier, captured together with its quotes so that
# normalize_identifier keeps its exact text instead of folding it like a
# bare name. Interpolated into the object patterns below.
_QUOTED = f"({DOUBLE_QUOTED_IDENTIFIER})"


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
                rf"\b(?:CREATE|DROP|ALTER)\s+(?:GLOBAL\s+TEMPORARY\s+|AUXILIARY\s+)?TABLE\s+(?:IF\s+(?:NOT\s+)?EXISTS\s+)?(?:{_QUOTED}|([a-zA-Z0-9_$#@]+))(?:\.(?:{_QUOTED}|([a-zA-Z0-9_$#@]+)))?",
                re.IGNORECASE,
            ),
            "view": re.compile(
                rf"\b(?:CREATE|DROP|ALTER)\s+(?:OR\s+REPLACE\s+)?VIEW\s+(?:IF\s+(?:NOT\s+)?EXISTS\s+)?(?:{_QUOTED}|([a-zA-Z0-9_$#@]+))(?:\.(?:{_QUOTED}|([a-zA-Z0-9_$#@]+)))?",
                re.IGNORECASE,
            ),
            # A Db2 index is independently schema-qualified
            # ([indexschema.]indexname), unlike its ON-target table -
            # SYSCAT.INDEXES has its own INDSCHEMA, separate from the
            # table's TABSCHEMA. So the index's own name gets the same
            # optional schema.name capture every other pattern here has,
            # while the ON-target is matched but never captured.
            "index": re.compile(
                r"\b(?:CREATE|DROP|ALTER)\s+(?:UNIQUE\s+)?INDEX\s+(?:IF\s+(?:NOT\s+)?EXISTS\s+)?"
                rf"(?:{_QUOTED}|([a-zA-Z0-9_$#@]+))"
                rf"(?:\.(?:{_QUOTED}|([a-zA-Z0-9_$#@]+)))?"
                r"(?:\s+ON\s+(?:\"[^\"]+\"|[a-zA-Z0-9_$#@]+)(?:\.(?:\"[^\"]+\"|[a-zA-Z0-9_$#@]+))?)?",
                re.IGNORECASE,
            ),
            "sequence": re.compile(
                rf"\b(?:CREATE|DROP|ALTER)\s+(?:OR\s+REPLACE\s+)?SEQUENCE\s+(?:IF\s+(?:NOT\s+)?EXISTS\s+)?(?:{_QUOTED}|([a-zA-Z0-9_$#@]+))(?:\.(?:{_QUOTED}|([a-zA-Z0-9_$#@]+)))?",
                re.IGNORECASE,
            ),
            "procedure": re.compile(
                rf"\b(?:CREATE|DROP|ALTER)\s+(?:OR\s+REPLACE\s+)?PROCEDURE\s+(?:IF\s+(?:NOT\s+)?EXISTS\s+)?(?:{_QUOTED}|([a-zA-Z0-9_$#@]+))(?:\.(?:{_QUOTED}|([a-zA-Z0-9_$#@]+)))?",
                re.IGNORECASE,
            ),
            "function": re.compile(
                rf"\b(?:CREATE|DROP|ALTER)\s+(?:OR\s+REPLACE\s+)?FUNCTION\s+(?:IF\s+(?:NOT\s+)?EXISTS\s+)?(?:{_QUOTED}|([a-zA-Z0-9_$#@]+))(?:\.(?:{_QUOTED}|([a-zA-Z0-9_$#@]+)))?",
                re.IGNORECASE,
            ),
            "trigger": re.compile(
                rf"\b(?:CREATE|DROP|ALTER)\s+(?:OR\s+REPLACE\s+)?TRIGGER\s+(?:IF\s+(?:NOT\s+)?EXISTS\s+)?(?:{_QUOTED}|([a-zA-Z0-9_$#@]+))(?:\.(?:{_QUOTED}|([a-zA-Z0-9_$#@]+)))?",
                re.IGNORECASE,
            ),
            "database": re.compile(
                rf"\b(?:CREATE|DROP|ALTER)\s+DATABASE\s+(?:IF\s+(?:NOT\s+)?EXISTS\s+)?(?:{_QUOTED}|([a-zA-Z0-9_$#@]+))",
                re.IGNORECASE,
            ),
            "tablespace": re.compile(
                rf"\b(?:CREATE|DROP|ALTER)\s+(?:LOB\s+)?TABLESPACE\s+(?:{_QUOTED}|([a-zA-Z0-9_$#@]+))",
                re.IGNORECASE,
            ),
            "stogroup": re.compile(
                rf"\b(?:CREATE|DROP|ALTER)\s+STOGROUP\s+(?:{_QUOTED}|([a-zA-Z0-9_$#@]+))",
                re.IGNORECASE,
            ),
            "alias": re.compile(
                rf"\b(?:CREATE|DROP)\s+ALIAS\s+(?:{_QUOTED}|([a-zA-Z0-9_$#@]+))(?:\.(?:{_QUOTED}|([a-zA-Z0-9_$#@]+)))?",
                re.IGNORECASE,
            ),
            "role": re.compile(
                rf"\b(?:CREATE|DROP)\s+ROLE\s+(?:{_QUOTED}|([a-zA-Z0-9_$#@]+))", re.IGNORECASE
            ),
            "mask": re.compile(
                rf"\b(?:CREATE|DROP|ALTER)\s+(?:OR\s+REPLACE\s+)?MASK\s+(?:{_QUOTED}|([a-zA-Z0-9_$#@]+))(?:\.(?:{_QUOTED}|([a-zA-Z0-9_$#@]+)))?",
                re.IGNORECASE,
            ),
            "permission": re.compile(
                rf"\b(?:CREATE|DROP|ALTER)\s+(?:OR\s+REPLACE\s+)?PERMISSION\s+(?:{_QUOTED}|([a-zA-Z0-9_$#@]+))(?:\.(?:{_QUOTED}|([a-zA-Z0-9_$#@]+)))?",
                re.IGNORECASE,
            ),
            "trusted_context": re.compile(
                rf"\b(?:CREATE|DROP|ALTER)\s+TRUSTED\s+CONTEXT\s+(?:{_QUOTED}|([a-zA-Z0-9_$#@]+))",
                re.IGNORECASE,
            ),
            "type": re.compile(
                rf"\b(?:CREATE|DROP)\s+(?:OR\s+REPLACE\s+)?TYPE\s+(?:{_QUOTED}|([a-zA-Z0-9_$#@]+))(?:\.(?:{_QUOTED}|([a-zA-Z0-9_$#@]+)))?",
                re.IGNORECASE,
            ),
            "variable": re.compile(
                rf"\b(?:CREATE|DROP)\s+(?:OR\s+REPLACE\s+)?VARIABLE\s+(?:{_QUOTED}|([a-zA-Z0-9_$#@]+))(?:\.(?:{_QUOTED}|([a-zA-Z0-9_$#@]+)))?",
                re.IGNORECASE,
            ),
            "synonym": re.compile(
                rf"\b(?:CREATE|DROP)\s+(?:OR\s+REPLACE\s+)?SYNONYM\s+(?:{_QUOTED}|([a-zA-Z0-9_$#@]+))(?:\.(?:{_QUOTED}|([a-zA-Z0-9_$#@]+)))?",
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
            identifier = strip_identifier_quotes(identifier)
            is_quoted = True

        # DB2 identifiers are case-insensitive unless quoted
        if not is_quoted:
            identifier = identifier.upper()

        return identifier

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
        return re.compile(rf"(?:{identifier}\.)?{identifier}", re.IGNORECASE)

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
