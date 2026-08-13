"""SQL analyzer — parses migration scripts to extract tables, views, indexes, and other objects."""

import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from core.logger import Log
from core.migration.sql.statement_splitter import StatementSplitter
from core.sql_model._base_sql_object import SqlObjectType

# Import parser system components
from core.sql_parser.parser_factory import SqlParserFactory

# Configure logging
logger = logging.getLogger(__name__)

# --- Object recognition vocabulary ------------------------------------------
# Object types recognised after CREATE / ALTER / DROP, after the ``ON`` of a
# GRANT / REVOKE, and after COMMENT ON. Ordered longest-first so a two-word type
# is never truncated to its first word: ``DROP MATERIALIZED VIEW mv`` used to be
# reported as type "MATERIALIZED" with name "default_schema.VIEW", so the object
# actually being dropped never appeared at all.
_RECOGNISED_OBJECT_TYPES: Tuple[SqlObjectType, ...] = (
    SqlObjectType.FOREIGN_DATA_WRAPPER,
    SqlObjectType.MATERIALIZED_VIEW,
    SqlObjectType.PACKAGE_BODY,
    SqlObjectType.DATABASE_LINK,
    SqlObjectType.TABLE,
    SqlObjectType.VIEW,
    SqlObjectType.INDEX,
    SqlObjectType.SEQUENCE,
    SqlObjectType.TRIGGER,
    SqlObjectType.FUNCTION,
    SqlObjectType.PROCEDURE,
    SqlObjectType.PACKAGE,
    SqlObjectType.TYPE,
    SqlObjectType.SYNONYM,
    SqlObjectType.SCHEMA,
    SqlObjectType.EXTENSION,
    SqlObjectType.DATABASE,
    SqlObjectType.ROLE,
    SqlObjectType.USER,
    SqlObjectType.EVENT,
)

# Built from the enum members themselves, so whatever the alternation matches is
# a ``SqlObjectType`` member name by construction once its spaces are collapsed
# back to underscores (see ``_object_type_name``).
_OBJECT_KEYWORDS = "|".join(t.name.replace("_", r"\s+") for t in _RECOGNISED_OBJECT_TYPES)

# The schema reported when a statement names none. An internal placeholder, not
# an identifier: consumers must strip it rather than emit it into SQL.
DEFAULT_SCHEMA_PLACEHOLDER = "default_schema"

# A SQL identifier: quoted ("x", [x], `x`) or bare, optionally schema-qualified.
_IDENTIFIER = r'(?:"[^"]+"|\[[^\]]+\]|`[^`]+`|[\w$#]+)'
_QUALIFIED_NAME = rf"{_IDENTIFIER}(?:\s*\.\s*{_IDENTIFIER})*"
# Words that stand between the object type and its name and must never be
# captured as the name -- the real name follows them:
# ``DROP TABLE IF EXISTS users``, ``ALTER TABLE ONLY users ADD COLUMN c``
# (PostgreSQL's no-inheritance modifier), ``DROP INDEX CONCURRENTLY idx``.
_NAME_PREFIX = r"(?:(?:IF\s+(?:NOT\s+)?EXISTS|ONLY|CONCURRENTLY)\s+)*"

# Leading comments must not hide the statement's leading verb.
_LEADING_COMMENTS_RE = re.compile(r"\A(?:\s*(?:--[^\n]*|/\*.*?\*/))+\s*", re.DOTALL)

# CREATE INDEX is kept separate from the generic DDL shape because it names two
# objects: the index, and the table it is built on (reported as ``on_object``).
# An index build is an INDEX whatever index *type* it declares, so the type
# keyword is skipped rather than being allowed to make the statement
# unrecognisable: ``CREATE BITMAP INDEX`` (Oracle), ``CREATE FULLTEXT INDEX``
# and ``CREATE SPATIAL INDEX`` (MySQL), ``CREATE UNIQUE CLUSTERED INDEX`` and
# ``CREATE CLUSTERED COLUMNSTORE INDEX`` (SQL Server). Skipping one here cannot
# select a wrong type the way a modifier before an alternation can: what follows
# this group is the literal INDEX, so a mis-skip fails to match rather than
# matching something else. This branch owns every index build carrying an ON
# clause, which is why these keywords are not repeated in ``_DDL_MODIFIERS``.
_INDEX_TYPE_MODIFIERS = (
    r"(?:(?:UNIQUE|CLUSTERED|NONCLUSTERED|COLUMNSTORE|BITMAP|FULLTEXT|SPATIAL)\s+)*"
)
# Only these two literal modifiers may stand between INDEX and the name. The
# name group refuses to match either of them, or the ``ON`` that follows an
# unnamed index build: an earlier version relied on the trailing ``ON`` to force
# backtracking onto "the real name", which is precisely what reported
# ``CREATE INDEX CONCURRENTLY ON orders (email)`` as an index named
# CONCURRENTLY. When there is no name, there is no name to report.
_INDEX_MODIFIERS = r"(?:(?:CONCURRENTLY|IF\s+(?:NOT\s+)?EXISTS)\s+)*"
_NOT_AN_INDEX_NAME = r"(?!(?:ON|CONCURRENTLY)\b)"
# Anchored for the same reason as the DDL patterns below: an index build nested
# in a routine body must not displace the routine as the statement's subject.
_CREATE_INDEX_RE = re.compile(
    rf"\ACREATE\s+{_INDEX_TYPE_MODIFIERS}INDEX\s+{_INDEX_MODIFIERS}"
    rf"{_NOT_AN_INDEX_NAME}({_QUALIFIED_NAME})"
    rf"\s+ON\s+(?:ONLY\s+)?({_QUALIFIED_NAME})",
    re.IGNORECASE,
)
# Modifiers that may stand between the verb and the object type. An explicit
# allowlist rather than "skip any word": a wildcard skip let a modelled keyword
# further along the statement displace the real subject, so
# ``ALTER PUBLICATION pub ADD TABLE t`` reported the table. Each entry names a
# real statement -- ``CREATE OR REPLACE VIEW v``, ``CREATE GLOBAL TEMPORARY
# TABLE t``, ``CREATE LOCAL TEMPORARY TABLE t``, ``CREATE TEMP VIEW v``,
# ``CREATE UNLOGGED TABLE t``, ``CREATE VIRTUAL TABLE v USING fts5``,
# ``CREATE FOREIGN TABLE f``, ``CREATE PUBLIC SYNONYM s FOR t`` and
# ``CREATE PUBLIC DATABASE LINK dl`` -- and an unlisted one is not a silent
# wrong answer: the statement falls through to the UNKNOWN branch with its name
# intact. MATERIALIZED is deliberately absent: it is the first word of a
# modelled two-word type, so skipping it would report a plain VIEW. Index-type
# keywords are absent for a different reason -- the CREATE INDEX branch above
# owns those statements, and it reports the target table as well as the type.
_DDL_MODIFIER_KEYWORDS = (
    r"OR\s+REPLACE",
    "GLOBAL",
    "LOCAL",
    "TEMPORARY",
    "TEMP",
    "UNLOGGED",
    "VIRTUAL",
    "FOREIGN",
    "PUBLIC",
)
_DDL_MODIFIERS = rf"(?:(?:{'|'.join(_DDL_MODIFIER_KEYWORDS)})\s+)*"
# Multi-word object types this analyzer does not model. Listed so their trailing
# words are not read as the object's name: without ``EVENT TRIGGER`` here,
# ``CREATE EVENT TRIGGER et`` matches the modelled EVENT and reports an event
# named "TRIGGER". Each names a real statement: PostgreSQL's
# ``CREATE TEXT SEARCH DICTIONARY d (...)``, ``CREATE EVENT TRIGGER et ON ...``,
# ``CREATE USER MAPPING FOR u SERVER s``, ``ALTER DEFAULT PRIVILEGES IN SCHEMA s``
# and ``CREATE OPERATOR CLASS oc FOR TYPE int``, and Oracle's
# ``CREATE TYPE BODY t``.
_UNMODELLED_MULTI_WORD_TYPES = (
    r"TEXT\s+SEARCH\s+\w+|EVENT\s+TRIGGER|USER\s+MAPPING|TYPE\s+BODY"
    r"|DEFAULT\s+PRIVILEGES|OPERATOR\s+(?:CLASS|FAMILY)"
)

# Anchored: the object a DDL statement acts on is named at its head, so a
# keyword appearing later must never be reached by scanning forward.
_DDL_OBJECT_RE = re.compile(
    rf"\A(?:CREATE|ALTER|DROP)\s+{_DDL_MODIFIERS}({_OBJECT_KEYWORDS})\b\s+"
    rf"{_NAME_PREFIX}({_QUALIFIED_NAME})",
    re.IGNORECASE,
)
# Vetoes the match above when the head is really an unmodelled multi-word type.
_UNMODELLED_MULTI_WORD_RE = re.compile(
    rf"\A(?:CREATE|ALTER|DROP)\s+{_DDL_MODIFIERS}(?:{_UNMODELLED_MULTI_WORD_TYPES})\b",
    re.IGNORECASE,
)
# Same shape, but for an object type this analyzer does not model (TABLESPACE,
# POLICY, PUBLICATION, ...). The keyword itself is deliberately not captured:
# admitting it as an ``object_type`` is what broke the one-vocabulary invariant,
# so these degrade to ``UNKNOWN`` while still reporting the object's name.
# ``(?:\w+\s+)?(?:{_OBJECT_KEYWORDS})`` is what makes an unlisted modifier fail
# safely: in ``CREATE PUBLIC SYNONYM s`` the modelled SYNONYM sitting one word
# in is evidence that PUBLIC was a modifier, so the name is still ``s`` rather
# than the keyword. The type stays UNKNOWN -- widening the *typed* path to skip
# arbitrary words is what let a later keyword displace the subject.
_UNMODELLED_DDL_RE = re.compile(
    rf"\A(?:CREATE|ALTER|DROP)\s+{_DDL_MODIFIERS}"
    rf"(?:{_UNMODELLED_MULTI_WORD_TYPES}|(?:\w+\s+)?(?:{_OBJECT_KEYWORDS})|\w+)\s+"
    rf"{_NAME_PREFIX}({_QUALIFIED_NAME})",
    re.IGNORECASE,
)
_TRUNCATE_RE = re.compile(
    rf"TRUNCATE\s+(?:TABLE\s+)?(?:ONLY\s+)?({_QUALIFIED_NAME})", re.IGNORECASE
)
_COMMENT_ON_RE = re.compile(
    rf"COMMENT\s+ON\s+(COLUMN|{_OBJECT_KEYWORDS})\b\s+({_QUALIFIED_NAME})", re.IGNORECASE
)
# ``ON ALL TABLES IN SCHEMA s`` names a set rather than one object; the name it
# yields is rejected by ``_names_an_object`` rather than by a second mechanism.
_GRANT_RE = re.compile(
    rf"(?:GRANT|REVOKE)\b.*?\bON\s+(?:({_OBJECT_KEYWORDS})\b\s+)?({_QUALIFIED_NAME})",
    re.IGNORECASE | re.DOTALL,
)
_DML_TARGET_RE = re.compile(
    rf"(?:INSERT\s+INTO|MERGE\s+INTO|DELETE\s+FROM|UPDATE)\s+(?:ONLY\s+)?({_QUALIFIED_NAME})",
    re.IGNORECASE,
)


# Words no grammar makes an object's name, refused in the name slot whatever
# vouched for it. Each is reserved in SQL and so cannot be a bare identifier:
# ``CREATE INDEX ON orders (email)`` names no index, ``DROP OWNED BY r`` names
# no object, ``GRANT SELECT ON ALL TABLES IN SCHEMA s`` names a set, and
# ``GRANT USAGE ON FOREIGN SERVER srv`` names a server type this module does
# not model. Quoted identifiers keep their quotes and so never match here: a
# table really called "set" is written ``DROP TABLE "set"``.
_RESERVED_WORDS = frozenset(
    "ALL AS BY CONCURRENTLY EXISTS FOR FOREIGN FROM IF IN INTO IS NOT ON ONLY TO"
    " USING VALUES WITH".split()
)

# The wider net, consulted only where nothing vouched for the name. It holds
# every word this module reads as syntax -- statement verbs, object types and
# the modifier allowlists -- derived from those patterns so it cannot drift out
# of sync when one of them gains a keyword, plus the words that occupy the name
# slot in statements which configure a session or instance rather than name an
# object (``ALTER SESSION SET x = y``, ``ALTER SESSION ENABLE PARALLEL DML``,
# ``ALTER SYSTEM RESET ALL``, ``ALTER SYSTEM FLUSH SHARED_POOL``,
# ``ALTER SYSTEM CHECKPOINT``) and Oracle's editionable-object modifiers
# (``CREATE OR REPLACE FORCE EDITIONABLE VIEW v``).
_SESSION_CLAUSE_WORDS = "SET RESET ENABLE DISABLE FLUSH CHECKPOINT EDITIONABLE NONEDITIONABLE"
_STATEMENT_VERBS = (
    "CREATE ALTER DROP TRUNCATE COMMENT GRANT REVOKE INSERT UPDATE DELETE MERGE SELECT"
)
_SYNTAX_WORDS = _RESERVED_WORDS | frozenset(
    re.findall(
        r"[A-Z]{2,}",
        " ".join(
            (
                _OBJECT_KEYWORDS,
                _INDEX_TYPE_MODIFIERS,
                _INDEX_MODIFIERS,
                _NAME_PREFIX,
                _DDL_MODIFIERS,
                _UNMODELLED_MULTI_WORD_TYPES,
                _SESSION_CLAUSE_WORDS,
                _STATEMENT_VERBS,
            )
        ),
    )
)


def _names_an_object(raw: str, vouched: bool) -> bool:
    """Whether the name slot holds a name rather than a keyword.

    ``vouched`` says a modelled object-type keyword was matched immediately
    before this token, which is what identifies the token as a name: a table
    may legitimately be called ``checkpoint`` or ``data``, and after
    ``ON TABLE`` it plainly is one. Reserved words are refused either way --
    no grammar makes ``ON`` an object name, which is how the unnamed index
    build ``CREATE INDEX ON orders (email)`` reports no index rather than one
    called "ON". Where nothing vouched, the wider syntax net applies: naming
    a keyword is the one outcome worse than naming nothing.
    """
    word = raw.upper()
    if word in _RESERVED_WORDS:
        return False
    return vouched or word not in _SYNTAX_WORDS


def _object_type_name(keyword: str) -> str:
    """Return the ``SqlObjectType`` member name for a matched type keyword."""
    return re.sub(r"\s+", "_", keyword.strip().upper())


def _qualified_object_name(raw: str, drop_last_part: bool = False) -> str:
    """Render a matched identifier as ``schema.name``.

    Unqualified names take the literal ``default_schema`` prefix, the convention
    the CREATE TABLE branch has always used. ``drop_last_part`` reports the
    parent of a column reference, so ``users.email`` becomes ``users``.
    """
    parts = re.findall(_IDENTIFIER, raw)
    if drop_last_part and len(parts) > 1:
        parts = parts[:-1]
    if len(parts) >= 2:
        return f"{parts[-2]}.{parts[-1]}"
    return f"{DEFAULT_SCHEMA_PLACEHOLDER}.{parts[0]}"


class SqlAnalyzer:
    """Analyzes SQL statements for type and affected objects."""

    def __init__(
        self,
        dialect: str,
        logger: Optional[Log] = None,
        parser_factory: Any = None,
        statement_splitter: Optional[StatementSplitter] = None,
    ):
        """Initialize SQL analyzer.

        Args:
            dialect: SQL dialect to use (required — callers resolve it from
                config/provider or the plugin registry; ADR-26 E5)
            logger: Optional logger to use
            parser_factory: Optional parser factory to use
        """
        self.dialect = dialect.lower()
        self.logger = logger or logging.getLogger(__name__)

        # Statement execution only needs regex/tokenizer splitting. Rich parser
        # construction remains reserved for schema/object analysis paths.
        self._db_specific_parser = None
        try:
            classification_factory = SqlParserFactory(self.dialect, parser_type="regex")
            self._db_specific_parser = classification_factory.get_parser()

            self.logger.debug(
                f"Initialized parser: {type(self._db_specific_parser).__name__} for dialect: {self.dialect}"
            )
        except Exception as e:
            # Use a basic logger if the class logger isn't available yet
            import logging as log_module

            basic_logger = log_module.getLogger(__name__)
            basic_logger.debug(
                f"Failed to initialize database-specific parser for {self.dialect}: {e}"
            )
            self._db_specific_parser = None

        self.statement_splitter = statement_splitter or StatementSplitter(
            self.dialect, logger=self.logger
        )

        # Set up rich parser factory for object extraction and schema analysis.
        if parser_factory is not None:
            self.parser_factory = parser_factory
        else:
            self.parser_factory = SqlParserFactory(self.dialect)

    def get_statement_type(self, sql: str) -> str:
        """Get the high-level type of SQL statement (DDL, DML, QUERY, UNKNOWN).

        Uses database-specific regex parser, falling back to string analysis.
        """
        sql = sql.strip()

        if not sql:
            return "UNKNOWN"

        # Try database-specific parser classification first
        if self.dialect and hasattr(self, "_db_specific_parser") and self._db_specific_parser:
            try:
                # Use database-specific parser's improved classification
                pass

                # Check if the parser has the method before calling it
                if hasattr(self._db_specific_parser, "_identify_statement_type"):
                    stmt_type = self._db_specific_parser._identify_statement_type(sql)

                    # Convert SqlStatementType enum to string (not MigrationType).
                    if hasattr(stmt_type, "value"):
                        result = str(stmt_type.value)
                    else:
                        result = str(stmt_type)  # lint: allow-enum-str  SqlStatementType fallback

                    # If we got a definitive result (not UNKNOWN), use it
                    if result != "UNKNOWN":
                        return result

            except Exception as e:
                logger.debug(f"Database-specific parser classification failed: {e}")

        # Fallback to enhanced string-based classification
        return self._get_statement_type_string(sql)

    def _get_statement_type_string(self, sql: str) -> str:
        """Enhanced string-based statement type identification with EXEC support."""
        # Remove leading/trailing whitespace
        sql_clean = sql.strip()
        # UTF-8 BOM breaks startswith("CREATE") / DDL detection if left in place
        if sql_clean.startswith("\ufeff"):
            sql_clean = sql_clean.lstrip("\ufeff").lstrip()

        # Remove SQL comments to get the actual first keyword
        # Remove block comments /* ... */
        sql_clean = re.sub(r"/\*.*?\*/", "", sql_clean, flags=re.DOTALL)
        # Remove line comments -- ...
        sql_clean = re.sub(r"--.*?$", "", sql_clean, flags=re.MULTILINE)

        # Get the cleaned and normalized statement
        sql_upper = sql_clean.upper().strip()

        if not sql_upper:
            return "UNKNOWN"

        # DDL patterns - include GRANT/REVOKE as they are DDL statements
        ddl_keywords = ["CREATE", "ALTER", "DROP", "TRUNCATE", "COMMENT", "GRANT", "REVOKE"]
        if any(sql_upper.startswith(ddl) for ddl in ddl_keywords):
            return "DDL"

        # Special handling for RENAME - it's DDL but might have different syntax
        if sql_upper.startswith("RENAME"):
            return "DDL"

        # DML patterns (including EXEC/EXECUTE)
        dml_keywords = ["INSERT", "UPDATE", "DELETE", "MERGE", "UPSERT"]
        if any(sql_upper.startswith(dml) for dml in dml_keywords):
            return "DML"

        # Handle EXEC/EXECUTE patterns more carefully
        if re.match(r"^EXEC(?:\s|\t|\n|\r)", sql_upper) or sql_upper.startswith("EXECUTE "):
            return "DML"

        # QUERY patterns
        query_keywords = ["SELECT", "WITH", "SHOW", "DESCRIBE", "DESC", "EXPLAIN"]
        if any(sql_upper.startswith(query) for query in query_keywords):
            return "QUERY"

        return "UNKNOWN"

    def extract_objects(self, sql: str) -> List[Dict[str, str]]:
        """Extract objects from a SQL statement.

        Args:
            sql: SQL statement to analyze

        Returns:
            List of dictionaries with object information
        """
        # Use regex-based extraction

        # Use the regex-based extraction as a reliable method
        return self._extract_objects_regex(sql)

    def analyze_statement(self, sql: str) -> Dict[str, Any]:
        """Analyze a SQL statement for type and affected objects.

        Args:
            sql: SQL statement to analyze

        Returns:
            Dictionary containing analysis results
        """
        # Use regex-based analysis
        try:
            objects = self.extract_objects(sql)

            analysis = {
                "type": self.get_statement_type(sql),
                "objects": objects,
                "is_valid": True,
                "errors": [],
                "parsed_with": "regex",
            }

            # Log details about the statement for debugging
            if hasattr(self.logger, "is_debug_enabled") and self.logger.is_debug_enabled():
                stmt_type = analysis.get("type", "UNKNOWN")
                obj_names = [
                    f"{obj.get('object_type', 'Unknown')}:{obj.get('object_name', 'unknown')}"
                    for obj in objects
                ]

                self.logger.debug(
                    f"SQL Statement analyzed with regex: Type={stmt_type}, "
                    f"Objects={', '.join(obj_names) if obj_names else 'None'}"
                )
                self.logger.debug(f"SQL: {sql[:100]}{'...' if len(sql) > 100 else ''}")

            return dict(analysis)
        except Exception as e:
            self.logger.warning(f"Error analyzing statement: {e}")
            try:
                objects = self.extract_objects(sql)
            except Exception as obj_e:
                self.logger.debug(f"Could not extract objects from SQL: {obj_e}")
                objects = []

            try:
                stmt_type = self.get_statement_type(sql)
            except Exception as type_e:
                self.logger.debug(f"Could not determine statement type: {type_e}")
                stmt_type = "UNKNOWN"

            return {
                "type": stmt_type,
                "objects": objects,
                "is_valid": False,
                "errors": [str(e)],
                "parsed_with": "regex",
            }

    def validate_sql(self, sql: str) -> Tuple[bool, Optional[str]]:
        """Validate SQL syntax and return (is_valid, error_message)."""
        # Try to use database-specific parser first if available
        if self._db_specific_parser and hasattr(self._db_specific_parser, "validate_sql"):
            try:
                self.logger.debug(f"Using {self.dialect}-specific parser for SQL validation")
                result = self._db_specific_parser.validate_sql(sql)

                # Handle different return formats from database-specific parsers
                if isinstance(result, tuple) and len(result) == 2:
                    is_valid, error_message = result
                elif isinstance(result, dict):
                    is_valid = bool(result.get("is_valid", result.get("valid", True)))
                    raw_error_message = result.get("error_message", None)
                    error_message = (
                        str(raw_error_message) if raw_error_message is not None else None
                    )
                else:
                    # If parser returns something else, assume it's a boolean
                    is_valid = bool(result)
                    error_message = None

                self.logger.debug(
                    f"Validated SQL using {self.dialect}-specific parser: valid={is_valid}"
                )

                # Log validation details for debugging
                if hasattr(self.logger, "is_debug_enabled") and self.logger.is_debug_enabled():
                    truncated_sql = sql[:100] + ("..." if len(sql) > 100 else "")
                    if is_valid:
                        self.logger.debug(f"Valid SQL ({self.dialect}): {truncated_sql}")
                    else:
                        self.logger.debug(f"Invalid SQL ({self.dialect}): {truncated_sql}")
                        self.logger.debug(f"Error: {error_message}")

                return is_valid, error_message
            except Exception as e:
                self.logger.warning(
                    f"{self.dialect}-specific parser validation failed: {e}, assuming SQL is valid"
                )

        # Without database-specific parser validation, we use basic structural checks
        # This provides minimal validation but avoids complex ANTLR-based parsing
        self.logger.info("Using basic structural SQL validation")

        # Basic checks for common syntax errors
        sql_clean = sql.strip()
        if not sql_clean:
            return False, "Empty SQL statement"

        # Check for obvious syntax errors
        if sql_clean.count("(") != sql_clean.count(")"):
            return False, "Unmatched parentheses"

        if sql_clean.count("'") % 2 != 0:
            return False, "Unmatched single quotes"

        # If basic checks pass, assume SQL is valid
        return True, None

    def split_statements(self, sql: str, strict_tokenizer: bool = False) -> List[str]:
        """Split SQL into individual statements.

        Args:
            sql: SQL script containing multiple statements
            strict_tokenizer: If True, dialect tokenizers fail on unknown
                characters instead of falling back to permissive splitting.

        Returns:
            List of individual SQL statements
        """
        statements = self.statement_splitter.split_statements(
            sql,
            strict_tokenizer=strict_tokenizer,
            fallback=self._split_statements_with_regex,
        )

        # Log each statement for debugging
        for i, stmt in enumerate(statements):
            self.logger.debug(
                f"Execution Statement {i+1}: '{stmt[:50]}{'...' if len(stmt) > 50 else ''}'"
            )

        return list(statements)

    def _split_statements_with_regex(self, sql: str) -> List[str]:
        """Split SQL statements using regex.

        This handles SQL server GO statements, semicolons, and takes into
        account strings, identifiers, and comments.

        Args:
            sql: SQL script containing multiple statements

        Returns:
            List of individual SQL statements
        """
        # Special handling for dialects that use a ``GO`` batch
        # separator (SQL Server / Sybase). The capability flag lives on
        # the plugin's quirks; SQL Server is currently the only opt-in.
        from db.provider_registry import ProviderRegistry

        if ProviderRegistry.get_quirks(self.dialect).supports_go_batch_separator:
            if re.search(r"(?i)^\s*GO\s*(?:--.*)?$", sql, flags=re.MULTILINE):
                return self._split_sqlserver_with_go(sql)

        # Handle normal semicolon-separated statements
        statements = []
        current_statement = []
        in_string = False
        in_identifier = False
        in_line_comment = False
        in_block_comment = False

        # Split by lines to handle line comments properly
        lines = sql.split("\n")

        for line in lines:
            # If we're in a line comment from the previous line, reset the flag
            if in_line_comment:
                in_line_comment = False

            # Skip empty lines
            if not line.strip():
                continue

            # Process line character by character
            i = 0
            while i < len(line):
                char = line[i]
                next_char = line[i + 1] if i < len(line) - 1 else ""

                # Handle string literals
                if char == "'" and not in_line_comment and not in_block_comment:
                    # Check for escaped quotes
                    if i < len(line) - 1 and line[i + 1] == "'":
                        # This is an escaped quote, not a string delimiter
                        current_statement.append(char)
                        current_statement.append(next_char)
                        i += 2
                        continue
                    in_string = not in_string

                # Handle quoted identifiers (e.g., [name] in SQL Server, "name" in Oracle/PostgreSQL)
                elif (
                    (char == "[" or char == '"')
                    and not in_string
                    and not in_line_comment
                    and not in_block_comment
                ):
                    in_identifier = True
                elif (char == "]" or char == '"') and in_identifier:
                    in_identifier = False

                # Handle line comments (--) but only if not in string or block comment
                elif (
                    char == "-"
                    and next_char == "-"
                    and not in_string
                    and not in_identifier
                    and not in_block_comment
                ):
                    in_line_comment = True
                    i += 1  # Skip the next character

                # Handle block comments (/* */) but only if not in string
                elif char == "/" and next_char == "*" and not in_string and not in_line_comment:
                    in_block_comment = True
                    i += 1  # Skip the next character
                elif char == "*" and next_char == "/" and in_block_comment:
                    in_block_comment = False
                    i += 1  # Skip the next character

                # Handle semicolons (statement separators) but only if not in literals or comments
                elif (
                    char == ";"
                    and not in_string
                    and not in_identifier
                    and not in_line_comment
                    and not in_block_comment
                ):
                    # Add the current character to complete the statement
                    current_statement.append(char)

                    # Join the accumulated characters to form a statement
                    statement = "".join(current_statement).strip()
                    if statement and statement != ";":
                        statements.append(statement)

                    # Reset for the next statement
                    current_statement = []

                    # Skip to the next character
                    i += 1
                    continue

                # Add the current character to the statement
                if not in_line_comment and not in_block_comment:
                    current_statement.append(char)

                i += 1

            # Add a newline at the end of the line if we're collecting a statement
            if current_statement and not in_line_comment and not in_block_comment:
                current_statement.append("\n")

        # Add the last statement if there's any content left
        if current_statement:
            statement = "".join(current_statement).strip()
            if statement:
                statements.append(statement)

        return statements

    def _split_sqlserver_with_go(self, sql: str) -> List[str]:
        """Split SQL Server script with GO statements.

        Args:
            sql: SQL Server script with GO statements

        Returns:
            List of SQL statements
        """
        # Split on GO statements - properly handle GO statements at the end of lines
        # This regex matches GO on a line by itself, optionally with whitespace and comments
        batches = re.split(r"(?i)^\s*GO\s*(?:--.*)?$", sql, flags=re.MULTILINE)

        # Filter out empty batches and any standalone GO statements
        statements = []
        for batch in batches:
            batch = batch.strip()
            if batch and batch.upper() != "GO":
                statements.append(batch)

        return statements

    def _extract_objects_regex(self, statement: str) -> List[Dict[str, str]]:
        """Extract objects from a SQL statement using regex.

        This is the single place that answers "which object does this statement
        touch". Every branch reports an ``object_type`` that is a
        ``SqlObjectType`` member name, so callers can map the string back to the
        enum instead of matching a spelling that varies per branch.

        Args:
            statement: SQL statement to analyze

        Returns:
            List of dictionaries with object information
        """
        objects: List[Dict[str, str]] = []

        # Handle empty input
        if not statement or not statement.strip():
            return objects

        statement = _LEADING_COMMENTS_RE.sub("", statement.strip()).strip()
        if not statement:
            return objects

        upper = statement.upper()
        # Matched up front rather than guarded by a literal prefix: the index
        # type keyword varies by dialect, and a prefix guard admitting only
        # CREATE INDEX / CREATE UNIQUE INDEX left every other index build
        # without the table it is built on.
        create_index = _CREATE_INDEX_RE.search(statement) if upper.startswith("CREATE") else None

        # CREATE INDEX also names the table the index is built on
        if create_index:
            objects.append(
                {
                    "object_type": SqlObjectType.INDEX.name,
                    "object_name": create_index.group(1),
                    "on_object": _qualified_object_name(create_index.group(2)),
                }
            )

        # CREATE / ALTER / DROP of any recognised object type
        elif upper.startswith("CREATE") or upper.startswith("ALTER") or upper.startswith("DROP"):
            match = _DDL_OBJECT_RE.search(statement)
            if match and not _UNMODELLED_MULTI_WORD_RE.search(statement):
                # The modelled keyword vouches for what follows it being a name.
                if _names_an_object(match.group(2), vouched=True):
                    objects.append(
                        {
                            "object_type": _object_type_name(match.group(1)),
                            "object_name": _qualified_object_name(match.group(2)),
                        }
                    )
            else:
                # An object type this analyzer does not model still names an
                # object. Reporting nothing would drop the statement from every
                # caller's view; reporting the raw keyword as a type would break
                # the one vocabulary. So: the name, typed honestly as UNKNOWN.
                # Nothing vouches for the token here, so the wider syntax net
                # applies (``ALTER SYSTEM RESET ALL`` names no object).
                match = _UNMODELLED_DDL_RE.search(statement)
                if match and _names_an_object(match.group(1), vouched=False):
                    objects.append(
                        {
                            "object_type": SqlObjectType.UNKNOWN.name,
                            "object_name": _qualified_object_name(match.group(1)),
                        }
                    )

        # TRUNCATE always targets a table, with or without the TABLE keyword
        elif upper.startswith("TRUNCATE"):
            match = _TRUNCATE_RE.search(statement)
            if match:
                objects.append(
                    {
                        "object_type": SqlObjectType.TABLE.name,
                        "object_name": _qualified_object_name(match.group(1)),
                    }
                )

        # COMMENT ON <type> <name>; a column comment reports its table
        elif upper.startswith("COMMENT"):
            match = _COMMENT_ON_RE.search(statement)
            if match:
                is_column = match.group(1).upper() == "COLUMN"
                objects.append(
                    {
                        "object_type": (
                            SqlObjectType.TABLE.name
                            if is_column
                            else _object_type_name(match.group(1))
                        ),
                        "object_name": _qualified_object_name(
                            match.group(2), drop_last_part=is_column
                        ),
                    }
                )

        # GRANT / REVOKE name the object the privilege is on; without an
        # explicit type keyword the object is a table
        elif upper.startswith("GRANT") or upper.startswith("REVOKE"):
            match = _GRANT_RE.search(statement)
            keyword = match.group(1) if match else None
            # ``GRANT ... ON x`` names an object by grammar whether or not it
            # spells the type, so the position itself vouches; the reserved
            # words still apply, which is what stops ``ON ALL TABLES IN SCHEMA``
            # and ``ON FOREIGN SERVER srv``.
            if match and _names_an_object(match.group(2), vouched=True):
                objects.append(
                    {
                        "object_type": (
                            _object_type_name(keyword) if keyword else SqlObjectType.TABLE.name
                        ),
                        "object_name": _qualified_object_name(match.group(2)),
                    }
                )

        # DML names the table it writes to. A read (SELECT) affects no object.
        elif (
            upper.startswith("INSERT")
            or upper.startswith("UPDATE")
            or upper.startswith("DELETE")
            or upper.startswith("MERGE")
        ):
            match = _DML_TARGET_RE.search(statement)
            if match:
                objects.append(
                    {
                        "object_type": SqlObjectType.TABLE.name,
                        "object_name": _qualified_object_name(match.group(1)),
                    }
                )

        return objects
