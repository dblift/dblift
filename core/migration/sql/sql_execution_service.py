"""SQL execution service — runs migration statements with timing, batching, and error capture."""

import re
import time
from typing import Any, Dict, List, Optional, Tuple, Union

from core.constants import (
    LOG_STATEMENT_PREVIEW_LENGTH,
    SECONDS_TO_MILLISECONDS,
    truncate_sql_for_logging,
)
from core.logger import NullLog
from core.sql_model.base import SqlStatementType
from db.base_quirks import BaseQuirks
from db.provider_interfaces import TransactionalProvider


def _format_execution_error(exc: BaseException) -> str:
    """Produce a concise log message for database driver and Python failures.

    Driver exceptions can omit SQLSTATE / vendor codes from ``str(exc)`` but still
    expose them via attributes or getSQLState() / getErrorCode().
    Mirrors the rationale in cli.db_utils._extract_sqlstate alongside error
    string patterns matched in db/error.py (e.g. ``sqlstate=42...``).
    """
    from core.migration.executor.execution_engine import _strip_driver_exception_prefix
    from db.value_utils import to_python_string

    base = _strip_driver_exception_prefix((to_python_string(exc) or str(exc)).strip())
    fragments: List[str] = []
    if base:
        fragments.append(base)

    sqlstate: Optional[str] = None
    get_sqlstate = getattr(exc, "getSQLState", None)
    if callable(get_sqlstate):
        try:
            raw = get_sqlstate()
            if raw:
                sqlstate = str(raw).strip() or None
        except Exception:
            sqlstate = None
    if not sqlstate:
        attr_ss = getattr(exc, "sqlstate", None) or getattr(exc, "SQLState", None)
        if attr_ss:
            sqlstate = str(attr_ss).strip() or None
    if sqlstate:
        fragments.append(f"sqlstate={sqlstate}")

    code: Optional[Union[int, str]] = None
    get_code = getattr(exc, "getErrorCode", None)
    if callable(get_code):
        try:
            raw_c = get_code()
            if raw_c is not None:
                code = raw_c
        except Exception:
            code = None
    if code is None:
        attr_c = getattr(exc, "errorcode", None)
        if attr_c is None:
            attr_c = getattr(exc, "errorCode", None)
        if attr_c is not None:
            code = attr_c

    if code is not None:
        fragments.append(f"errorcode={code}")

    return " ".join(fragments) if fragments else ""


class SqlExecutionService:
    """Service for executing SQL statements in a database.

    This service handles statement classification, execution, and error reporting.
    It delegates to the appropriate provider methods based on the statement type.
    """

    def __init__(
        self,
        provider: Any,
        sql_analyzer: Any,
        logger: Any = None,
        journal: Any = None,
        schema: Optional[str] = None,
        quirks: Optional[BaseQuirks] = None,
    ) -> None:
        """Initialize the SQL execution service.

        Args:
            provider: Database provider for executing statements
            sql_analyzer: SQL analyzer for statement classification
            logger: Optional logger instance
            journal: Optional journal for recording execution details
            schema: Optional schema name for object parsing
            quirks: Dialect quirks overlay; when ``None`` the service tries
                ``provider.quirks`` and finally falls back to a vanilla
                :class:`BaseQuirks`. Used to recognise batch separators.
        """
        self.provider = provider
        self.sql_analyzer = sql_analyzer
        self.log = logger if logger is not None else NullLog()
        self.journal = journal
        self.schema = schema
        self._quirks: Optional[BaseQuirks] = quirks

    @property
    def quirks(self) -> BaseQuirks:
        """Resolve the dialect-quirks overlay, caching the lookup."""
        if self._quirks is None:
            provider_quirks = getattr(self.provider, "quirks", None)
            self._quirks = (
                provider_quirks if isinstance(provider_quirks, BaseQuirks) else BaseQuirks()
            )
        return self._quirks

    def execute_statement(
        self,
        statement: str,
        stmt_index: Optional[int] = None,
        params: Optional[List[Any]] = None,
        autocommit: bool = False,
    ) -> Tuple[bool, Union[List[Dict[str, Any]], int]]:
        """Execute a SQL statement.

        Args:
            statement: SQL statement to execute
            stmt_index: Optional index for journal tracking
            params: Optional parameters for prepared statements
            autocommit: Route the statement through the provider's
                ``execute_autocommit_statement`` so it reaches the server
                outside a transaction block (statements flagged by
                ``TransactionPolicy``, e.g. ``CREATE INDEX CONCURRENTLY``)

        Returns:
            Tuple of (is_query_result, result) where:
              - is_query_result is True for query results, False for DDL/DML row counts
              - result is either a list of row dictionaries (for queries) or row count (for DDL/DML)
        """
        if self.quirks.is_batch_separator(statement):
            self.log.debug("Skipping dialect batch separator statement")
            return False, 0

        # Log statement for debugging
        if len(statement) > LOG_STATEMENT_PREVIEW_LENGTH:
            self.log.debug(
                f"Executing statement (preview): {truncate_sql_for_logging(statement, LOG_STATEMENT_PREVIEW_LENGTH)}"
            )
        else:
            self.log.debug(f"Executing statement: {statement}")

        # Record statement start in journal if enabled
        stmt_start_time = time.time()
        if self.journal and hasattr(self.journal, "record_statement_start"):
            self.journal.record_statement_start(statement, stmt_index)

        try:
            # Classify statement using the SQL analyzer
            statement_type = self.sql_analyzer.get_statement_type(statement)

            # Execute based on statement type
            if statement_type == SqlStatementType.QUERY.value:
                result_set = self.provider.execute_query(statement, params=params)
                row_count = len(result_set) if result_set else 0

                # Record statement completion in journal
                if self.journal and hasattr(self.journal, "record_statement_complete"):
                    execution_time = int((time.time() - stmt_start_time) * SECONDS_TO_MILLISECONDS)
                    self.journal.record_statement_complete(
                        statement, stmt_index, execution_time, {"rows_affected": row_count}
                    )

                # Return query results
                return True, result_set

            elif statement_type in [SqlStatementType.DDL.value, SqlStatementType.DML.value]:
                # For Oracle DDL, apply special handling if available
                if statement_type == SqlStatementType.DDL.value and hasattr(
                    self.provider, "_normalize_ddl_for_oracle"
                ):
                    # Apply Oracle-specific DDL normalization if this is Oracle
                    normalized_sql = self.provider._normalize_ddl_for_oracle(statement)
                    if normalized_sql != statement:
                        statement = normalized_sql

                # Execute the statement, providing schema context so providers can ensure readiness
                rows_affected = self._provider_execute(statement, params, autocommit)

                # Record statement completion in journal
                if self.journal and hasattr(self.journal, "record_statement_complete"):
                    execution_time = int((time.time() - stmt_start_time) * SECONDS_TO_MILLISECONDS)
                    self.journal.record_statement_complete(
                        statement, stmt_index, execution_time, {"rows_affected": rows_affected}
                    )

                    # Extract and record object changes for DDL and DML statements
                    # DDL: CREATE, ALTER, DROP, COMMENT, etc.
                    # DML: INSERT, UPDATE, DELETE (affect TABLE objects)
                    if statement_type in (
                        SqlStatementType.DDL.value,
                        SqlStatementType.DML.value,
                    ) and hasattr(self.journal, "record_object_changes"):
                        try:
                            objects_affected = []

                            # For DDL statements, use parser to extract objects
                            if statement_type == SqlStatementType.DDL.value:
                                # Use the parser factory directly to get proper schema handling
                                if getattr(self.sql_analyzer, "parser_factory", None):
                                    objects_affected = (
                                        self.sql_analyzer.parser_factory.extract_objects(
                                            statement, self.schema
                                        )
                                    )
                                else:
                                    # Fallback to analyzer method
                                    objects_affected = self.sql_analyzer.extract_objects(statement)

                            # For DML statements (INSERT, UPDATE, DELETE), extract table name
                            elif statement_type == SqlStatementType.DML.value:
                                stmt_upper = statement.strip().upper()
                                if stmt_upper.startswith(("INSERT", "UPDATE", "DELETE")):
                                    # Try to use parser to extract table name
                                    if getattr(self.sql_analyzer, "parser_factory", None):
                                        try:
                                            objects_affected = (
                                                self.sql_analyzer.parser_factory.extract_objects(
                                                    statement, self.schema
                                                )
                                                or []
                                            )
                                        except Exception as e:
                                            self.log.debug(
                                                f"Could not extract objects from statement: {e}"
                                            )

                                    # Fallback: parsers only cover DDL, so DML normally
                                    # yields no objects (empty list, no exception)
                                    if not objects_affected:
                                        table_name = self._extract_table_from_dml(statement)
                                        if table_name:
                                            from core.sql_model.base import (
                                                SqlObject,
                                                SqlObjectType,
                                            )

                                            objects_affected = [
                                                SqlObject(
                                                    name=table_name,
                                                    object_type=SqlObjectType.TABLE,
                                                    schema=self.schema or "",
                                                )
                                            ]

                            if objects_affected:
                                # Convert SqlObject instances to dictionaries for JSON serialization
                                # Deduplicate objects by (object_name, object_type, schema) to avoid counting the same object multiple times
                                seen_objects = set()
                                objects_dict = []
                                for obj in objects_affected:
                                    if hasattr(obj, "__dict__"):
                                        # SqlObject instance - convert to dict
                                        obj_name = getattr(obj, "name", "unknown")
                                        obj_type = getattr(obj, "object_type", "UNKNOWN")
                                        obj_schema = getattr(obj, "schema", "")

                                        # Handle object_type enum (schema object, not MigrationType)
                                        if hasattr(obj_type, "value"):
                                            obj_type_str = obj_type.value
                                        else:
                                            obj_type_str = str(obj_type)  # lint: allow-enum-str

                                        # Create deduplication key
                                        dedup_key = (
                                            obj_name.lower(),
                                            obj_type_str.upper(),
                                            (obj_schema or "").lower(),
                                        )

                                        # Skip if we've already seen this object
                                        if dedup_key in seen_objects:
                                            continue

                                        seen_objects.add(dedup_key)

                                        obj_dict = {
                                            "object_name": obj_name,
                                            "object_type": obj_type_str,
                                            "schema": obj_schema,
                                            "dialect": getattr(obj, "dialect", ""),
                                        }
                                        objects_dict.append(obj_dict)
                                    else:
                                        # Already a dict - deduplicate
                                        obj_name = obj.get("object_name", "unknown")
                                        obj_type = str(obj.get("object_type", "UNKNOWN")).upper()
                                        obj_schema = (obj.get("schema") or "").lower()

                                        dedup_key = (obj_name.lower(), obj_type, obj_schema)
                                        if dedup_key in seen_objects:
                                            continue

                                        seen_objects.add(dedup_key)
                                        objects_dict.append(obj)

                                # Only record if we have unique objects
                                if objects_dict:
                                    self.journal.record_object_changes(
                                        statement, stmt_index, objects_dict
                                    )
                        except Exception as e:
                            self.log.debug(f"Could not extract objects from statement: {e}")

                # Return affected row count
                return False, rows_affected

            else:
                # Unknown statement type - fallback to execute_statement
                self.log.debug(
                    f"Unknown statement type '{statement_type}' - using execute_statement"
                )

                rows_affected = self._provider_execute(statement, params, autocommit)

                # Record statement completion in journal
                if self.journal and hasattr(self.journal, "record_statement_complete"):
                    execution_time = int((time.time() - stmt_start_time) * SECONDS_TO_MILLISECONDS)
                    self.journal.record_statement_complete(
                        statement, stmt_index, execution_time, {"rows_affected": rows_affected}
                    )

                # Return affected row count
                return False, rows_affected

        except Exception as e:
            # Record statement failure in journal if enabled
            if self.journal and hasattr(self.journal, "record_statement_failed"):
                execution_time = int((time.time() - stmt_start_time) * SECONDS_TO_MILLISECONDS)
                error_message = str(e)
                self.journal.record_statement_failed(
                    statement, stmt_index, error_message, execution_time
                )

            try:
                formatted = _format_execution_error(e)
            except Exception:
                formatted = ""
            sql_snippet = statement.strip().splitlines()[0][:120]
            self.log.error(f"SQL: {sql_snippet}")
            self.log.error(formatted or str(e))

            # Re-raise the exception
            raise

    def _provider_execute(
        self, statement: str, params: Optional[List[Any]], autocommit: bool
    ) -> int:
        """Send a non-query statement to the provider.

        Autocommit routing lives here so the DDL/DML branch and the
        unknown-type fallback treat flagged statements identically.
        """
        if autocommit and isinstance(self.provider, TransactionalProvider):
            return int(
                self.provider.execute_autocommit_statement(
                    statement, schema=self.schema, params=params
                )
            )
        return int(self.provider.execute_statement(statement, schema=self.schema, params=params))

    @staticmethod
    def _extract_simple_table_name(identifier: str) -> str:
        """Extract the simple (unqualified, unquoted) table name from a potentially
        qualified or quoted identifier.

        Handles:
        - schema.table → table
        - catalog.schema.table → table
        - "quoted.table" → quoted.table  (dot inside quotes is NOT a separator)
        - "schema"."my.table" → my.table
        - [dbo].[users] → users  (SQL Server brackets)
        - public."my.table" → my.table
        """
        if not identifier:
            return identifier
        # Match the last component: bracket notation, double-quoted, backtick-quoted, or plain identifier
        pattern = r'(?:\[([^\]]+)\]|"([^"]+)"|`([^`]+)`|([^\.\[\]"`\s]+))$'
        match = re.search(pattern, identifier.strip())
        if match:
            return (
                match.group(1) or match.group(2) or match.group(3) or match.group(4) or identifier
            )
        return identifier

    def _extract_table_from_dml(self, statement: str) -> Optional[str]:
        """Extract table name from DML statement (INSERT, UPDATE, DELETE).

        Args:
            statement: SQL DML statement

        Returns:
            Table name if found, None otherwise
        """
        if not statement:
            return None

        stmt_upper = statement.strip().upper()
        stmt_original = statement.strip()

        # INSERT INTO table_name ...
        if stmt_upper.startswith("INSERT"):
            match = re.search(r"INSERT\s+INTO\s+([^\s(]+)", stmt_original, re.IGNORECASE)
            if match:
                table_name = match.group(1).strip()
                # Extract simple table name: handles qualified names (catalog.schema.table),
                # quoted identifiers ("my.table"), and SQL Server brackets ([dbo].[table])
                return self._extract_simple_table_name(table_name)

        # UPDATE table_name ...
        elif stmt_upper.startswith("UPDATE"):
            match = re.search(r"UPDATE\s+([^\s]+)", stmt_original, re.IGNORECASE)
            if match:
                table_name = match.group(1).strip()
                # Extract simple table name: handles qualified names (catalog.schema.table),
                # quoted identifiers ("my.table"), and SQL Server brackets ([dbo].[table])
                return self._extract_simple_table_name(table_name)

        # DELETE FROM table_name ...
        elif stmt_upper.startswith("DELETE"):
            match = re.search(r"DELETE\s+FROM\s+([^\s]+)", stmt_original, re.IGNORECASE)
            if match:
                table_name = match.group(1).strip()
                # Extract simple table name: handles qualified names (catalog.schema.table),
                # quoted identifiers ("my.table"), and SQL Server brackets ([dbo].[table])
                return self._extract_simple_table_name(table_name)

        return None
