"""DDL execution + pre-CREATE drop machinery extracted from ``RoundTripTester``.

Provides ``_DropPhaseMixin``: the autocommit handling, transaction-state
probing, per-statement drop+execute loop, and the dialect-specific
``DROP TABLE`` SQL builder used before each ``CREATE TABLE``. The retry-
on-error path (Oracle/DB2 "already exists" recovery) lives in
``_retry_strategy.py``; this mixin only dispatches to it via
``self._retry_drop_and_create``.

Logger name is hardcoded to ``core.validation.round_trip_tester`` so unit
tests using ``assertLogs("core.validation.round_trip_tester", ...)`` still
observe records emitted from this module.
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, Any, Dict, List

from core.exceptions import ConnectionClosedError

if TYPE_CHECKING:
    from db.base_quirks import BaseQuirks

# Preserve the historical logger name so `assertLogs("core.validation.round_trip_tester", ...)`
# in the unit tests keeps capturing records emitted from this mixin.
logger = logging.getLogger("core.validation.round_trip_tester")


class _DropPhaseMixin:
    """DDL execution + pre-CREATE drop helpers for ``RoundTripTester``.

    Requires the composing class to expose: ``dialect``, ``test_provider``,
    ``test_schema``, ``results``, ``_quirks``, and the
    ``_retry_drop_and_create`` method (provided by ``_RetryStrategyMixin``).
    ``_retry_drop_and_create`` is intentionally not declared on this mixin
    so MRO resolves it to ``_RetryStrategyMixin``'s real implementation.
    """

    # Attributes supplied by the composing class (declared for mypy clarity).
    dialect: str
    test_provider: Any
    test_schema: str
    results: Dict[str, Any]
    _quirks: "BaseQuirks"

    def _execute_ddl_statements(self, statements: List[str]) -> None:
        """Orchestrator: execute DDL statements with dialect-specific error handling."""
        self._set_autocommit()
        logger.info(
            f"[{self.dialect.upper()}] Starting execution of {len(statements)} CREATE statements"
        )
        for idx, statement in enumerate(statements, 1):
            logger.debug(f"[{self.dialect.upper()}] Executing statement {idx}/{len(statements)}")
            self._ensure_clean_transaction_state()
            try:
                self._drop_preexisting_objects(statement)
                self._execute_single_statement(statement, idx)
            except Exception as e:
                self._recover_from_statement_error(e, statement)

    def _set_autocommit(self) -> None:
        """Configure autoCommit based on dialect before DDL execution."""
        if self._quirks.supports_session_autocommit:
            if hasattr(self.test_provider.connection, "setAutoCommit"):  # type: ignore[attr-defined]
                try:
                    if hasattr(self.test_provider.connection, "isClosed"):  # type: ignore[attr-defined]
                        if self.test_provider.connection.isClosed():  # type: ignore[attr-defined]
                            logger.warning(
                                f"[{self.dialect.upper()}] Connection is closed, cannot set autoCommit"
                            )
                            raise ConnectionClosedError("Connection is closed")
                    if hasattr(self.test_provider.connection, "getAutoCommit"):  # type: ignore[attr-defined]
                        current_auto_commit = self.test_provider.connection.getAutoCommit()  # type: ignore[attr-defined]
                        if current_auto_commit:
                            self.test_provider.connection.setAutoCommit(False)  # type: ignore[attr-defined]
                            logger.debug(f"[{self.dialect.upper()}] Set autoCommit to False")
                        else:
                            logger.debug(f"[{self.dialect.upper()}] autoCommit already False")
                    else:
                        self.test_provider.connection.setAutoCommit(False)  # type: ignore[attr-defined]
                except Exception as auto_commit_err:
                    logger.warning(
                        f"[{self.dialect.upper()}] Failed to set autoCommit: {auto_commit_err}"
                    )
        else:
            # Dialect handles autoCommit at connection-creation time (Oracle)
            # or auto-commits DDL anyway (MySQL/DB2 — setting setAutoCommit(False)
            # could hang).
            logger.debug(
                f"[{self.dialect.upper()}] Skipping setAutoCommit (dialect handles autocommit "
                f"at connection-creation time or auto-commits DDL)"
            )

    def _ensure_clean_transaction_state(self) -> None:
        """Check transaction state and rollback if aborted."""
        try:
            if hasattr(self.test_provider.connection, "getAutoCommit"):  # type: ignore[attr-defined]
                if not self.test_provider.connection.getAutoCommit():  # type: ignore[attr-defined]
                    test_query = self._quirks.connection_probe_sql
                    self.test_provider.query_executor.execute_query(  # type: ignore[attr-defined]
                        self.test_provider.connection, test_query, []  # type: ignore[attr-defined]
                    )
        except Exception as e:
            logger.debug(
                f"[{self.dialect.upper()}] Transaction state check failed (non-critical): {e}"
            )
            try:
                if hasattr(self.test_provider.connection, "rollback"):  # type: ignore[attr-defined]
                    self.test_provider.connection.rollback()  # type: ignore[attr-defined]
            except Exception as rollback_err:
                logger.debug(
                    f"[{self.dialect.upper()}] Rollback in bad-state handler failed (non-critical): {rollback_err}"
                )

    def _drop_preexisting_objects(self, statement: str) -> None:
        """Drop preexisting table before CREATE, if the statement is a CREATE TABLE."""
        table_match = re.search(
            r'CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?(?:(?:"([^"]+)"|([a-zA-Z_][a-zA-Z0-9_]*))\.)?(?:"([^"]+)"|([a-zA-Z_][a-zA-Z0-9_]*))',
            statement,
            re.IGNORECASE,
        )
        if not table_match:
            return

        schema_name = table_match.group(1) or table_match.group(2) or self.test_schema
        table_name = table_match.group(3) or table_match.group(4)
        if not schema_name or schema_name == table_name:
            schema_name = self.test_schema
        schema_was_quoted = table_match.group(1) is not None
        table_was_quoted = table_match.group(3) is not None

        drop_sql = self._build_drop_sql(
            schema_name, table_name, schema_was_quoted, table_was_quoted
        )

        try:
            self.test_provider.query_executor.execute_statement(  # type: ignore[attr-defined]
                self.test_provider.connection, drop_sql, []  # type: ignore[attr-defined]
            )
            if self._quirks.requires_explicit_commit_after_ddl and hasattr(self.test_provider.connection, "commit"):  # type: ignore[attr-defined]
                self.test_provider.connection.commit()  # type: ignore[attr-defined]
        except Exception as drop_err:
            error_msg = str(drop_err).lower()
            if (
                "transaction is aborted" in error_msg
                or "current transaction is aborted" in error_msg
            ):
                try:
                    if hasattr(self.test_provider.connection, "rollback"):  # type: ignore[attr-defined]
                        self.test_provider.connection.rollback()  # type: ignore[attr-defined]
                except Exception as e:
                    logger.debug(
                        f"[{self.dialect.upper()}] Rollback after failed drop failed (non-critical): {e}"
                    )
            else:
                logger.debug(
                    f"[{self.dialect.upper()}] DROP before CREATE failed (non-critical, likely table does not exist): {drop_err}"
                )

    def _build_drop_sql(
        self,
        schema_name: str,
        table_name: str,
        schema_was_quoted: bool,
        table_was_quoted: bool,
    ) -> str:
        """Build dialect-specific DROP TABLE SQL.

        Round-trip uses bespoke DROP grammar (BEGIN/EXCEPTION on Oracle,
        OBJECT_ID guard on SQL Server) that's distinct from
        ``BaseQuirks.render_drop_for_object``. The branching here stays
        keyed on identifier-quoting / dialect-specific recovery rather
        than calling out to a generic hook.
        """
        # Dialects whose data dictionary stores unquoted identifiers
        # upper-cased (Oracle, DB2) share the same target-formatting rule:
        # quote the schema/table when the source quoted them, otherwise
        # upper-case. The actual DROP SQL differs (Oracle needs a PL/SQL
        # EXCEPTION wrapper + CASCADE CONSTRAINTS, DB2 has no IF EXISTS) —
        # that variance lives in ``Quirks.render_round_trip_drop_table_sql``.
        if self._quirks.unquoted_identifiers_uppercase_in_dictionary:
            schema_clean = f'"{schema_name}"' if schema_was_quoted else f'"{self.test_schema}"'
            table_clean = (
                f'"{table_name}"' if table_was_quoted else table_name.replace('"', "").upper()
            )
            target = f"{schema_clean}.{table_clean}"
            logger.debug(
                f"[{self.dialect.upper()}] Attempting to drop table {target} before CREATE "
                f"(quoted schema: {schema_was_quoted}, quoted table: {table_was_quoted})"
            )
            return self._quirks.render_round_trip_drop_table_sql(target)
        # SQL Server uses [bracketed] identifiers and an OBJECT_ID guard.
        if self._quirks.quote_open == "[":
            return f"IF OBJECT_ID('[{schema_name}].{table_name}', 'U') IS NOT NULL DROP TABLE [{schema_name}].{table_name}"
        # MySQL/MariaDB use backtick identifiers.
        if self._quirks.quote_open == "`":
            return f"DROP TABLE IF EXISTS `{schema_name}`.`{table_name}`"
        # Generic double-quoted dialects: PostgreSQL adds CASCADE; others
        # (SQLite, default) use plain DROP TABLE IF EXISTS.
        if self._quirks.table_drop_style == "if_exists_cascade":
            return f'DROP TABLE IF EXISTS "{schema_name}"."{table_name}" CASCADE'
        return f'DROP TABLE IF EXISTS "{schema_name}"."{table_name}"'

    def _execute_single_statement(self, statement: str, idx: int) -> None:
        """Execute a single DDL statement, raising on failure."""
        logger.debug(f"[{self.dialect.upper()}] Executing statement {idx}: {statement[:200]}...")
        try:
            self.test_provider.query_executor.execute_statement(  # type: ignore[attr-defined]
                self.test_provider.connection, statement, []  # type: ignore[attr-defined]
            )
            logger.debug(f"[{self.dialect.upper()}] Statement {idx} executed successfully")
        except Exception as exec_err:
            error_msg = str(exec_err)
            is_view_creation = "CREATE" in statement.upper() and "VIEW" in statement.upper()
            is_dependency_error = (
                "does not exist" in error_msg.lower()
                or "doesn't exist" in error_msg.lower()
                or "invalid object name" in error_msg.lower()
            )
            if is_view_creation and is_dependency_error:
                logger.warning(
                    f"View creation failed due to missing dependency (expected): {error_msg}"
                )
                logger.debug(f"Failed statement: {statement[:1000]}...")
            else:
                logger.error(f"Statement execution failed: {error_msg}")
                logger.error(f"Failed statement: {statement[:1000]}...")
            if self._quirks.quote_open == "[" and "CREATE TABLE" in statement.upper():
                logger.error(f"Full CREATE TABLE statement:\n{statement}")
            raise

    def _recover_from_statement_error(self, error: Exception, statement: str) -> None:
        """Handle statement execution errors: rollback, retry, or log."""
        error_msg = str(error)
        logger.debug(f"Statement execution error: {error_msg}")

        # Transaction aborted → rollback and skip
        if (
            "transaction is aborted" in error_msg.lower()
            or "current transaction is aborted" in error_msg.lower()
        ):
            logger.warning(f"Transaction aborted, rolling back: {error}")
            try:
                if hasattr(self.test_provider.connection, "rollback"):  # type: ignore[attr-defined]
                    self.test_provider.connection.rollback()  # type: ignore[attr-defined]
            except Exception as rollback_err:
                logger.warning(f"Rollback failed: {rollback_err}")
            return

        # Already exists → retry drop+create for Oracle/DB2
        if (
            "already exists" in error_msg.lower()
            or "00955" in error_msg
            or "existe déjà" in error_msg.lower()
            or "42710" in error_msg
            or "duplicate" in error_msg.lower()
        ):
            logger.debug(f"Table already exists, attempting to drop again: {error}")
            logger.debug(f"Error message: {error_msg}")
            if self._quirks.retry_drop_create_on_error and "CREATE TABLE" in statement.upper():
                # ``_retry_drop_and_create`` is supplied by ``_RetryStrategyMixin``
                # on the composing class; declared abstract on this mixin would
                # shadow that implementation via MRO.
                if self._retry_drop_and_create(statement):  # type: ignore[attr-defined]
                    return

        # SQL Server syntax errors: surface immediately rather than retry.
        if self._quirks.quote_open == "[":
            if "syntax" in error_msg.lower() or "incorrect" in error_msg.lower():
                logger.error(f"SQL Server syntax error in statement: {statement[:500]}")
                self.results["errors"].append(f"Failed to execute statement: {error_msg[:200]}")
                return

        self.results["errors"].append(f"Failed to execute statement: {error_msg[:100]}")
        logger.error(f"Statement execution failed: {error}")
