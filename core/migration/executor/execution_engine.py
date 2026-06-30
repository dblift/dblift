"""
Core migration execution engine.

This module contains the low-level execution logic for individual migrations,
callbacks, and SQL statements.
"""

import re
import time
from enum import Enum
from typing import Any, Dict, List, Optional

from config.dblift_config import DbliftConfig
from core.constants import (
    LOG_STATEMENT_PREVIEW_LENGTH,
    SECONDS_TO_MILLISECONDS,
    truncate_sql_for_logging,
)
from core.exceptions import CallbackExecutionError, TransactionAbortedError
from core.logger import Log, NullLog
from core.logger.results import MigrationInfo, OperationResult
from core.migration.executor.transaction_policy import TransactionPolicy
from core.migration.executors import MigrationExecutorFactory
from core.migration.formats import MigrationFormat
from core.migration.history.migration_history_manager import MigrationHistoryManager
from core.migration.migration import Migration
from core.migration.placeholders.placeholder_service import PlaceholderService
from core.migration.sql.execution_statement import (
    ExecutionStatement,
    classify_execution_statement,
)
from core.migration.sql.sql_analyzer import SqlAnalyzer
from core.migration.sql.sql_execution_service import SqlExecutionService
from core.sql_model.dialect import quote_qualified
from db.base_provider import BaseProvider
from db.provider_interfaces import TransactionalProvider
from db.provider_registry import ProviderRegistry
from db.value_utils import to_python_string

_DRIVER_EXCEPTION_PREFIX_RE = re.compile(
    r"^(?:[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+Exception:\s*)+" r"(?:ERROR:\s*)?",
    re.IGNORECASE,
)


def _strip_driver_exception_prefix(msg: str) -> str:
    """Strip verbose driver exception class prefixes from error strings.

    e.g. 'org.postgresql.util.PSQLException: ERROR: column "x" already exists'
         → 'column "x" already exists'
    """
    return _DRIVER_EXCEPTION_PREFIX_RE.sub("", str(msg)).strip()


def _is_ddl_statement_for_success_log(statement: str) -> bool:
    head = statement.lstrip().split(None, 1)[0].upper() if statement.strip() else ""
    return head in {"CREATE", "ALTER", "DROP", "TRUNCATE", "COMMENT", "GRANT", "REVOKE", "RENAME"}


class ExecutionEngine:
    """Handles the core execution of migrations and SQL statements."""

    def __init__(
        self,
        provider: BaseProvider,
        sql_analyzer: SqlAnalyzer,
        log: Log,
        sql_execution_service: Optional[SqlExecutionService] = None,
        history_manager: Optional[MigrationHistoryManager] = None,
        placeholder_service: Optional[PlaceholderService] = None,
        config: Optional[DbliftConfig] = None,
    ):
        """Initialize the execution engine.

        Args:
            provider: Database provider for executing SQL
            sql_analyzer: SQL analyzer for statement classification
            log: Logger instance
            sql_execution_service: Optional SQL execution service with journal support
            history_manager: Optional history manager for recording migration history
            placeholder_service: Optional placeholder service for variable replacement
            config: Optional application configuration (injected by caller)
        """
        self.provider = provider
        self.sql_analyzer = sql_analyzer
        self.log = log if log is not None else NullLog()
        self.sql_execution_service = sql_execution_service
        self.history_manager = history_manager
        self.placeholder_service = placeholder_service
        self.config = config
        self.transaction_policy = TransactionPolicy()
        self._current_sqlplus_ctx: Optional[object] = (
            None  # set per-migration in _parse_sql_statements (opaque, dialect-owned)
        )

        # Initialize migration executor factory for multi-format support
        # This allows DBLIFT to support SQL and future non-SQL migrations (Python, etc.)
        self.executor_factory = MigrationExecutorFactory(
            provider=provider,
            config=config,
            log=self.log,
            sql_analyzer=sql_analyzer,
            sql_execution_service=sql_execution_service,
        )

    @staticmethod
    def _is_comment_only_statement(sql: str) -> bool:
        """True if *sql* has no executable tokens after removing block and line comments."""

        body = sql.strip()
        if not body:
            return True
        body = re.sub(r"/\*.*?\*/", "", body, flags=re.DOTALL)
        body = re.sub(r"--.*?$", "", body, flags=re.MULTILINE)
        return not body.strip()

    def execute_migration(self, migration: Migration, result: OperationResult) -> None:
        """Execute a single migration.

        Args:
            migration: The migration to execute
            result: The migration result to update
        """
        start_time = time.time()
        migration.logger = self.log

        if migration.format != MigrationFormat.SQL:
            self._execute_via_factory(migration, result)
            return

        statements = self._parse_sql_statements(
            migration, result, placeholder_service=self.placeholder_service
        )
        if statements is None:
            return

        execution_statements = self._classify_execution_statements(statements)
        policy = self.transaction_policy.decide(execution_statements, self.provider)
        if policy.unsupported_mixed_mode:
            result.set_error(
                f"Migration {migration.script_name} mixes transactional and autocommit-only statements: {policy.reason}"
            )
            return

        transaction_started = False
        if policy.transactional:
            transaction_started = self._prepare_transaction(migration)
            if not transaction_started:
                result.set_error(
                    f"Could not begin transaction for {migration.script_name}, aborting execution"
                )
                return
        elif policy.autocommit_required:
            self.log.warning(
                f"Executing {migration.script_name} without an explicit transaction: {policy.reason}"
            )
            self._ensure_autocommit_for_policy(migration)

        try:
            success = self._execute_statements(statements, migration, result, start_time)
            if not success:
                return  # _handle_statement_failure already rolled back

            execution_time = int((time.time() - start_time) * SECONDS_TO_MILLISECONDS)
            migration.execution_time = execution_time

            if policy.transactional:
                self._record_migration_history(migration, execution_time)  # may raise
                self._commit_and_verify(migration, statements, execution_time)
            else:
                self._record_autocommit_migration_history(migration, execution_time)

            self.log.info(
                f"Migration {migration.script_name} executed successfully in {execution_time}ms"
            )
        except Exception:
            # Rollback safety net: ANY exception raised during migration execution must
            # trigger a rollback before re-raise. Narrowing to typed exceptions here
            # would let unexpected types bypass the rollback path, leaving the
            # transaction open. The re-raise on the last line preserves the original
            # type for upstream classification — broad catch here, typed handling
            # happens at the call site.
            if transaction_started:
                try:
                    self.provider.rollback_transaction()
                    self.log.debug(
                        f"Rolled back transaction due to unexpected error in {migration.script_name}"
                    )
                except Exception as rollback_e:
                    # Best-effort rollback: log and continue so the original error
                    # (about to be re-raised below) is not masked by a rollback failure.
                    self.log.warning(
                        f"Could not rollback transaction after unexpected error: {rollback_e}"
                    )
            raise

    def _classify_execution_statements(self, statements: List[str]) -> List[ExecutionStatement]:
        """Attach transaction metadata to executable SQL statements."""
        dialect = self._probe_dialect_key() or getattr(self.sql_analyzer, "dialect", "") or ""
        quirks = ProviderRegistry.get_quirks(dialect)
        execution_statements: List[ExecutionStatement] = []
        for statement in statements:
            stripped = statement.strip()
            if (
                not stripped
                or quirks.is_batch_separator(stripped)
                or self._is_comment_only_statement(stripped)
            ):
                continue
            statement_type = self.sql_analyzer.get_statement_type(statement)
            execution_statements.append(
                classify_execution_statement(
                    statement,
                    dialect=dialect,
                    statement_type=statement_type,
                )
            )
        return execution_statements

    def get_executable_sql_statements(
        self, migration: Migration, result: OperationResult
    ) -> List[str]:
        """Return SQL statements that would be sent to the provider for a migration."""
        if migration.format != MigrationFormat.SQL:
            return []

        statements = self._parse_sql_statements(
            migration, result, placeholder_service=self.placeholder_service
        )
        if statements is None:
            return []

        dialect = self._probe_dialect_key() or getattr(self.sql_analyzer, "dialect", "") or ""
        quirks = ProviderRegistry.get_quirks(dialect)
        is_oracle_sqlplus = self._current_sqlplus_ctx is not None
        executable: List[str] = []
        execution_statements: List[ExecutionStatement] = []
        for statement in statements:
            stripped = statement.strip()
            if not stripped:
                continue
            if quirks.is_batch_separator(stripped):
                continue
            if self._is_comment_only_statement(stripped):
                continue
            if is_oracle_sqlplus and quirks.parse_error_policy_directive(stripped) is not None:
                continue
            statement_type = self.sql_analyzer.get_statement_type(statement)
            execution_statements.append(
                classify_execution_statement(
                    statement,
                    dialect=dialect,
                    statement_type=statement_type,
                )
            )
            executable.append(statement)
        policy = self.transaction_policy.decide(execution_statements, self.provider)
        if policy.unsupported_mixed_mode:
            result.set_error(
                f"Migration {migration.script_name} mixes transactional and autocommit-only statements: {policy.reason}"
            )
            return []
        return executable

    def _ensure_autocommit_for_policy(self, migration: Migration) -> None:
        """Best-effort rollback so autocommit-only statements are not inside an old transaction."""
        if not isinstance(self.provider, TransactionalProvider):
            return
        try:
            self.provider.rollback_transaction()
        except Exception as exc:
            self.log.debug(
                f"Could not rollback before autocommit execution for {migration.script_name}: {exc}"
            )
        conn = getattr(self.provider, "connection", None)
        if conn is not None and hasattr(conn, "setAutoCommit"):
            try:
                conn.setAutoCommit(True)
            except Exception as exc:
                self.log.debug(f"Could not force autocommit before {migration.script_name}: {exc}")

    def _parse_sql_statements(
        self,
        migration: Migration,
        result: OperationResult,
        placeholder_service: Optional[PlaceholderService] = None,
    ) -> Optional[List[str]]:
        """Parse SQL statements from a migration.

        Args:
            migration: The migration to parse.
            result: Operation result to record errors in.
            placeholder_service: If provided, placeholder substitution is applied to the
                migration content *before* the SQL tokeniser runs.  This prevents the
                tokeniser from inserting whitespace inside ``${...}`` fragments that are
                embedded within identifier names (e.g. ``${schema}_config`` → ``app_config``
                instead of the broken ``app _config``).

        Returns:
            List of SQL statements, or None if parsing fails (result.set_error called).
        """
        try:
            dialect_key: Optional[str] = None
            if self.config is not None:
                db = getattr(self.config, "database", None)
                raw_type = getattr(db, "type", None) if db is not None else None
                if raw_type is not None:
                    # Prefer .value (works for real DatabaseType enums and mock stubs alike).
                    # Fall back to str() for plain-string config values.
                    _raw_val = getattr(raw_type, "value", None)
                    if _raw_val is not None:
                        dialect_key = str(_raw_val).strip().lower()
                    else:
                        dialect_key = str(raw_type).strip().lower()  # lint: allow-enum-str
                    # Only normalize SQL Server aliases (preserves original behaviour
                    # where other aliases like "postgres" pass through unchanged).
                    # The SQL-Server-family check is a quirks capability
                    # (``is_sqlserver_family``) set by the SQL Server plugin, so
                    # this branch carries no hardcoded dialect-name literal. Only
                    # SQL Server aliases (``mssql``/``tsql``/``sql_server``) are
                    # canonicalised; other aliases such as ``postgres`` pass
                    # through unchanged.
                    if ProviderRegistry.get_quirks(dialect_key).is_sqlserver_family:
                        dialect_key = ProviderRegistry.canonical_dialect_name(dialect_key)
            if not dialect_key:
                dialect_key = self.sql_analyzer.dialect

            # Substitute placeholders in content BEFORE parsing so the tokeniser never
            # sees raw ${...} fragments, which it would split from adjacent characters.
            content_override: Optional[str] = None
            if placeholder_service:
                content_override = placeholder_service.replace_placeholders(migration.content)

            # Dialects with script-level preprocessing (Oracle SQL*Plus today) get their
            # context extracted + variable substitution + directive termination applied
            # via quirks hooks. Must run after placeholder substitution so ${...}
            # fragments are already resolved.
            self._current_sqlplus_ctx = None
            quirks = ProviderRegistry.get_quirks(dialect_key)
            if quirks.supports_sqlplus_preprocessing:
                base = content_override if content_override is not None else migration.content
                ctx = quirks.extract_script_context(base)
                self._current_sqlplus_ctx = ctx
                for msg in getattr(ctx, "prompts", []) or []:
                    self.log.info(f"[PROMPT] {msg}")
                # Append ';' to directive lines (SET, DEFINE, PROMPT, WHENEVER SQLERROR …)
                # so the tokeniser does not merge them with the next DDL/DML. Without this,
                # ``SET SERVEROUTPUT ON\nCREATE TABLE ...`` becomes a single statement that
                # the driver rejects (or that ``is_script_directive`` filters wholesale, dropping
                # the user's CREATE TABLE).
                terminated = quirks.terminate_script_directives(base)
                substituted = quirks.apply_script_substitution(terminated, ctx)
                if substituted != base:
                    content_override = substituted

            return migration.parse_sql_statements(
                dialect=dialect_key, content_override=content_override
            )
        except Exception as e:
            self.log.error(
                f"Failed to parse SQL for {migration.script_name}: {to_python_string(e)}"
            )
            result.set_error(
                f"Failed to parse SQL for {migration.script_name}: {to_python_string(e)}"
            )
            return None

    def _prepare_transaction(self, migration: Migration) -> bool:
        """Prepare transaction state: rollback any active transaction, then begin new one.

        Returns:
            True if begin_transaction succeeded, False otherwise.
        """
        try:
            # Check connection state before beginning
            if (
                isinstance(self.provider, TransactionalProvider)
                and hasattr(self.provider, "connection")
                and self.provider.connection
            ):
                try:
                    auto_commit_state = self.provider.connection.getAutoCommit()

                    # Rollback any existing transaction to ensure clean state
                    if not auto_commit_state:
                        try:
                            self.provider.rollback_transaction()
                        except Exception as rollback_e:
                            self.log.debug(
                                f"Could not rollback pre-migration transaction (may be no active transaction): {rollback_e}"
                            )
                except Exception as e:
                    self.log.debug(
                        f"Could not check connection state before {migration.script_name}: {e}"
                    )

            self.provider.begin_transaction()
            return True
        except Exception as e:
            self.log.warning(f"Could not begin transaction for {migration.script_name}: {e}")
            return False

    def _probe_dialect_key(self) -> Optional[str]:
        """Best-effort dialect string for transaction probes (lowercase, non-empty).

        Epic 26 dialect isolation: the provider is **authoritative** for
        its own dialect (each plugin sets
        :attr:`db.base_provider.BaseProvider.canonical_dialect_key`). The
        framework no longer URL-sniffs or branches on dialect names; it
        asks the provider.

        The legacy fallback cascade is retained only for non-plugin
        providers (e.g. ``MagicMock`` in unit tests) that don't declare
        ``canonical_dialect_key``: it normalizes whatever signal happens
        to be set (``sql_analyzer.dialect`` / ``config.database.type`` /
        ``provider.dialect``) through ``ProviderRegistry.canonical_dialect_name``
        so aliases like ``mssql`` resolve correctly.
        """

        def _normalize(raw: Any) -> Optional[str]:
            if raw is None:
                return None
            if isinstance(raw, Enum):
                raw = raw.value
            s = str(raw).strip().lower()
            if not s:
                return None
            from db.provider_registry import ProviderRegistry

            return ProviderRegistry.canonical_dialect_name(s)

        # Provider is authoritative: each plugin's concrete class declares
        # its own ``canonical_dialect_key``. No dialect literals in core.
        key = getattr(self.provider, "canonical_dialect_key", "") or ""
        if isinstance(key, str) and key.strip():
            return key.strip().lower()

        # Legacy fallback for providers / fakes without ``canonical_dialect_key``.
        d = _normalize(getattr(self.sql_analyzer, "dialect", None))
        if d:
            return d
        if self.config is not None:
            db = getattr(self.config, "database", None)
            d = _normalize(getattr(db, "type", None)) if db is not None else None
            if d:
                return d
        return _normalize(getattr(self.provider, "dialect", None))

    def _transaction_liveness_probe_sql(self) -> str:
        """Return a single-row SELECT valid for the active dialect.

        Delegates to ``provider.quirks.connection_probe_sql`` so the
        framework no longer hardcodes the dialect-specific variants
        (DB2 rejects bare ``SELECT 1``; Oracle requires ``FROM DUAL``).
        """
        from db.provider_registry import ProviderRegistry

        return ProviderRegistry.get_quirks(self._probe_dialect_key() or "").connection_probe_sql

    def _execute_statements(
        self,
        statements: List[str],
        migration: Migration,
        result: OperationResult,
        start_time: float,
    ) -> bool:
        """Execute all SQL statements in order.

        Returns:
            True if all statements executed successfully, False if any failed
            (in which case _handle_statement_failure was already called).
        """
        # Session-level output capture (Oracle DBMS_OUTPUT) — enabled before the loop
        # when the dialect's script context signals it. The quirks layer owns both
        # the directive recognition and the provider execution.
        ctx = self._current_sqlplus_ctx
        dialect = self._probe_dialect_key() or getattr(self.sql_analyzer, "dialect", "") or ""
        quirks = ProviderRegistry.get_quirks(dialect)
        _session_output_conn = getattr(self.provider, "connection", None)
        _session_output_active = False
        if (
            ctx is not None
            and getattr(ctx, "wants_session_output", False)
            and _session_output_conn is not None
        ):
            try:
                quirks.enable_session_output(_session_output_conn)
                _session_output_active = True
            except Exception as e:
                self.log.warning(f"Could not enable session output capture: {e}")

        # WHENEVER SQLERROR is Oracle/SQL*Plus-only. ctx is None for every other dialect,
        # so we gate all WHENEVER logic on this flag to avoid silently consuming
        # WHENEVER SQLERROR CONTINUE statements that appear in non-Oracle migrations.
        is_oracle_sqlplus = ctx is not None
        whenever_policy = "exit"  # SQL*Plus default; only meaningful when is_oracle_sqlplus

        probe_sql = self._transaction_liveness_probe_sql()
        for i, statement in enumerate(statements):
            self.log.debug(
                f"Executing statement {i+1}/{len(statements)} from {migration.script_name}"
            )

            stripped_stmt = statement.strip()
            # Skip empty statements
            if not stripped_stmt:
                continue
            # Dialect-specific batch separator (T-SQL ``GO``); not executable by the native driver
            if quirks.is_batch_separator(stripped_stmt):
                continue
            if self._is_comment_only_statement(stripped_stmt):
                continue
            # Positional error-handling directive (Oracle WHENEVER SQLERROR) — update
            # policy positionally, do not send to the provider. Gated on the script context
            # so non-Oracle dialects never consume CONTINUE/EXIT lookalikes.
            if is_oracle_sqlplus:
                _new_policy = quirks.parse_error_policy_directive(stripped_stmt)
                if _new_policy is not None:
                    whenever_policy = _new_policy
                    self.log.debug(f"WHENEVER SQLERROR policy → {whenever_policy}")
                    continue

            # Placeholders were already substituted in `_parse_sql_statements` on the
            # full content before tokenisation (BUG-06 fix). Re-substituting here would
            # risk re-interpreting `${...}` fragments that legitimately appear *inside*
            # a resolved placeholder value.

            # Log the statement (truncated for readability)
            self.log.debug(
                f"Executing: {truncate_sql_for_logging(statement, LOG_STATEMENT_PREVIEW_LENGTH)}"
            )

            stmt_start_time = time.time()
            try:
                # Pre-check transaction state (PostgreSQL anti-aborted-transaction).
                # Skip when supports_transactions() is False (e.g. Cosmos DB): the provider
                # still exposes ``connection`` and TransactionalProvider, but there is no SQL
                # session and execute_query("SELECT 1") would run against a default container
                # that may not exist yet.
                try:
                    run_precheck = (
                        isinstance(self.provider, TransactionalProvider)
                        and self.provider.supports_transactions()
                    )
                    if run_precheck:
                        if hasattr(self.provider, "connection") and self.provider.connection:
                            conn = self.provider.connection
                            stmt_check: Any = None
                            try:
                                stmt_check = conn.prepareStatement(probe_sql)
                            except AttributeError:
                                self.provider.execute_query(probe_sql)
                            else:
                                try:
                                    rs = stmt_check.executeQuery()
                                    rs.close()
                                finally:
                                    if stmt_check is not None:
                                        stmt_check.close()
                        else:
                            self.provider.execute_query(probe_sql)
                except Exception as pre_check_e:
                    error_msg = str(pre_check_e).lower()
                    if (
                        "transaction is aborted" in error_msg
                        or "current transaction is aborted" in error_msg
                    ):
                        raise TransactionAbortedError(
                            f"Transaction is aborted before executing statement {i+1}: {pre_check_e}"
                        ) from pre_check_e
                    else:
                        raise

                if self.sql_execution_service:
                    is_query, result_data = self.sql_execution_service.execute_statement(
                        statement, i
                    )
                    if is_query:
                        if not isinstance(result_data, list):
                            raise TypeError(
                                f"Expected list for query result, got {type(result_data).__name__}"
                            )
                        rows_affected = len(result_data) if result_data else 0
                    else:
                        if not isinstance(result_data, int):
                            raise TypeError(
                                f"Expected int for rows affected, got {type(result_data).__name__}"
                            )
                        rows_affected = result_data
                else:
                    rows_affected = self.provider.execute_statement(statement)

                if _is_ddl_statement_for_success_log(statement):
                    self.log.info("Statement executed successfully ")
                elif rows_affected is not None and rows_affected >= 0:
                    self.log.info(
                        f"Statement executed successfully, {rows_affected} rows affected "
                    )
                else:
                    self.log.info("Statement executed successfully ")

                execution_time = int((time.time() - stmt_start_time) * SECONDS_TO_MILLISECONDS)
                self.log.debug(f"Statement execution took {execution_time}ms")

                if _session_output_active:
                    try:
                        quirks.read_session_output(_session_output_conn, self.log)
                    except Exception as e:
                        self.log.warning(
                            f"Could not read session output after statement {i + 1}: {e}"
                        )

            except Exception as stmt_error:
                execution_time = int((time.time() - stmt_start_time) * SECONDS_TO_MILLISECONDS)
                self.log.debug(f"Statement execution took {execution_time}ms before failure")

                # WHENEVER SQLERROR CONTINUE mirrors SQL*Plus behaviour: only database-level
                # SQL errors are skippable. Infrastructure failures (aborted transaction,
                # connection loss) must propagate — continuing would just produce more errors.
                if (
                    is_oracle_sqlplus
                    and whenever_policy == "continue"
                    and not isinstance(
                        stmt_error, (TransactionAbortedError, ConnectionError, OSError)
                    )
                ):
                    self.log.warning(
                        f"Statement {i + 1} failed (WHENEVER SQLERROR CONTINUE): {stmt_error}"
                    )
                    continue

                total_execution_time = int((time.time() - start_time) * SECONDS_TO_MILLISECONDS)
                self._handle_statement_failure(
                    migration, stmt_error, i, total_execution_time, result
                )
                return False

        return True

    def _handle_statement_failure(
        self,
        migration: Migration,
        error: Exception,
        stmt_index: int,
        total_ms: int,
        result: OperationResult,
    ) -> None:
        """Handle a failed statement execution.

        Sequence: result.set_error -> result.add_migration(FAILED) -> rollback ->
        begin_transaction + record_migration(success=False) + commit.
        """
        error_msg = _strip_driver_exception_prefix(to_python_string(error) or str(error))
        self.log.error(
            f"Failed to execute statement {stmt_index+1} from {migration.script_name}: {error_msg}"
        )

        result.set_error(
            f"Failed to execute statement {stmt_index+1} in {migration.script_name}: {error_msg}"
        )

        # Record failed migration info to result
        try:
            migration_info = MigrationInfo(
                script=migration.script_name,
                version=migration.version,
                description=migration.description,
                type=migration.type.value if migration.type else "SQL",
                status="FAILED",
                execution_time=total_ms,
                checksum=migration.checksum,
                error=error_msg,
            )
            if hasattr(result, "add_migration"):
                result.add_migration(migration_info)

        except Exception as record_e:
            self.log.warning(
                f"Could not add failed migration {migration.script_name} to result: {record_e}"
            )

        # Rollback transaction for failed migration FIRST
        try:
            self.provider.rollback_transaction()
            self.log.debug(f"Rolled back transaction for failed migration {migration.script_name}")
        except Exception as rollback_e:
            self.log.warning(
                f"Could not rollback transaction for {migration.script_name}: {rollback_e}"
            )

        # Warn if the database does not support transactional DDL (MySQL, Oracle)
        if (
            isinstance(self.provider, TransactionalProvider)
            and not self.provider.supports_transactional_ddl()
        ):
            ddl_warning = (
                "This database does not support transactional DDL. "
                "DDL statements (CREATE, ALTER, DROP) from this migration may have been "
                "partially applied and cannot be rolled back automatically. "
                "Review the database state and use 'repair' before retrying."
            )
            self.log.warning(ddl_warning)
            if hasattr(result, "add_warning"):
                result.add_warning(ddl_warning)

        # Record failed migration in the history table AFTER rollback
        # Use a separate transaction to persist the failure record
        if self.history_manager:
            try:
                self.provider.begin_transaction()
                self.log.debug(
                    f"Recording failed migration {migration.script_name} in history table"
                )
                self.history_manager.record_migration(
                    migration, success=False, execution_time=total_ms
                )
                self.provider.commit_transaction()
                result.failed_history_persisted = True
                self.log.debug(f"Committed failed migration record for {migration.script_name}")
            except Exception as history_e:
                result.failed_history_persisted = False
                if hasattr(result, "add_warning"):
                    result.add_warning(
                        f"Failed migration was not persisted to history: {history_e}"
                    )
                self.log.warning(
                    f"Could not record failed migration {migration.script_name} in history: {history_e}"
                )
                try:
                    self.provider.rollback_transaction()
                except Exception as rollback_history_e:
                    self.log.debug(
                        f"Could not rollback history record transaction for {migration.script_name}: {rollback_history_e}"
                    )

    def _record_autocommit_migration_history(
        self, migration: Migration, execution_time: int
    ) -> None:
        """Record history after an autocommit-only migration using a short transaction."""
        if not self.history_manager:
            return
        transaction_started = False
        try:
            if isinstance(self.provider, TransactionalProvider):
                self.provider.begin_transaction()
                transaction_started = True
            self.history_manager.record_migration(
                migration, success=True, execution_time=execution_time
            )
            if transaction_started:
                self.provider.commit_transaction()
        except Exception as history_error:
            self.log.error(
                f"Failed to record migration history for {migration.script_name}: {history_error}"
            )
            if transaction_started:
                try:
                    self.provider.rollback_transaction()
                except Exception as rollback_e:
                    self.log.warning(
                        f"Could not rollback history transaction for {migration.script_name}: {rollback_e}"
                    )
            raise history_error

    def _record_migration_history(self, migration: Migration, execution_time: int) -> None:
        """Record successful migration in history table.

        Does nothing if history_manager is None.
        Raises on failure (after rollback).
        """
        if not self.history_manager:
            return
        try:
            self.history_manager.record_migration(
                migration, success=True, execution_time=execution_time
            )
        except Exception as history_error:
            self.log.error(
                f"Failed to record migration history for {migration.script_name}: {history_error}"
            )
            try:
                self.provider.rollback_transaction()
                self.log.debug(
                    f"Rolled back transaction due to history recording failure for {migration.script_name}"
                )
            except Exception as rollback_e:
                self.log.warning(
                    f"Could not rollback transaction for {migration.script_name}: {rollback_e}"
                )
            raise history_error

    def _commit_and_verify(
        self, migration: Migration, statements: List[str], execution_time: int
    ) -> None:
        """Commit transaction and optionally verify CREATE TABLE results.

        Raises:
            Exception: If commit_transaction() fails — caller must handle and rollback.

        Note:
            Post-commit verification failures (CREATE TABLE SELECT check) are non-critical
            and are caught internally — they do not raise.
        """
        try:
            self.provider.commit_transaction()

            if (
                isinstance(self.provider, TransactionalProvider)
                and hasattr(self.provider, "connection")
                and self.provider.connection
            ):
                try:
                    if "CREATE TABLE" in str(statements).upper():
                        for sql_stmt in statements:
                            if "CREATE TABLE" in sql_stmt.upper():
                                match = re.search(
                                    r'CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?["\']?(\w+)["\']?\.["\']?(\w+)["\']?',
                                    sql_stmt,
                                    re.IGNORECASE,
                                )
                                if match:
                                    schema_name = match.group(1)
                                    table_name = match.group(2)
                                    # Explicit guard: validate names before SQL interpolation (OWASP defense-in-depth)
                                    if not re.match(
                                        r"^[a-zA-Z0-9_]+$", schema_name
                                    ) or not re.match(r"^[a-zA-Z0-9_]+$", table_name):
                                        break  # skip verification if names don't match alphanumeric+underscore
                                    try:
                                        if (
                                            self.provider.connection
                                            and not self.provider.connection.isClosed()
                                        ):
                                            dialect = getattr(
                                                self.sql_analyzer, "dialect", ""
                                            ).lower()
                                            # B10-BUG-01: quote identifiers per dialect rules
                                            # (backticks for MySQL, brackets for SQL Server,
                                            # ANSI double-quotes elsewhere). The prior
                                            # hardcoded ``"schema"."table"`` form crashed on
                                            # MySQL and mismatched Oracle's default
                                            # upper-cased storage. Oracle folds unquoted
                                            # identifiers to uppercase — match that so
                                            # verification finds the table created by
                                            # scripts that wrote plain (unquoted) names.
                                            # Safe: schema/table validated as \w+ —
                                            # alphanumeric and underscore only.
                                            qualified = quote_qualified(
                                                dialect, schema_name, table_name
                                            )
                                            from db.provider_registry import ProviderRegistry

                                            _quirks = ProviderRegistry.get_quirks(dialect)
                                            if _quirks.select_supports_limit:
                                                test_query = f"SELECT COUNT(*) as cnt FROM {qualified} LIMIT 1"
                                            else:
                                                test_query = (
                                                    f"SELECT COUNT(*) as cnt FROM {qualified}"
                                                )
                                            self.provider.execute_query(test_query)
                                    except Exception as verify_e:
                                        self.log.debug(
                                            f"Post-commit verification query failed for {migration.script_name} (non-critical): {verify_e}"
                                        )
                                break
                except Exception as e:
                    self.log.debug(
                        f"Could not perform post-commit state verification for {migration.script_name}: {e}"
                    )

        except Exception as e:
            self.log.warning(f"Could not commit transaction for {migration.script_name}: {e}")
            raise  # Propagate commit failure to caller

    def _execute_via_factory(self, migration: Migration, result: OperationResult) -> None:
        """Delegate execution to the executor factory for non-SQL formats (Python, etc.).

        Runs the script inside an explicit transaction lifecycle — begin → execute → record
        history → commit — mirroring the SQL path so that DDL issued by a Python migration
        is actually persisted. Without this envelope, the DDL and the history insert stay in
        an uncommitted transaction that `_prepare_transaction` for the *next* migration
        rolls back, silently discarding the user's work (BUG-04).

        Placeholder substitution (``placeholder_service``) is intentionally not applied
        here.  Non-SQL formats (Python scripts) are executed as code, not SQL text, so
        ``${...}`` SQL-style placeholders are not meaningful.  Python migrations receive
        the full config via ``MigrationContext`` and resolve values programmatically.
        Any SQL they issue should apply placeholders through that context, not via the
        pre-parse substitution used by the SQL path.
        """
        migration_type = migration.format.value.upper() if migration.format else "UNKNOWN"

        transaction_started = False
        if isinstance(self.provider, TransactionalProvider):
            transaction_started = self._prepare_transaction(migration)
            if not transaction_started:
                result.set_error(
                    f"Could not begin transaction for {migration.script_name}, aborting execution"
                )
                return

        def _rollback_best_effort() -> None:
            if transaction_started and isinstance(self.provider, TransactionalProvider):
                try:
                    self.provider.rollback_transaction()
                except Exception as rb_err:
                    self.log.debug(
                        f"Could not rollback transaction for {migration.script_name}: {rb_err}"
                    )

        try:
            exec_result = self.executor_factory.execute(migration)
            elapsed_ms = exec_result.execution_time_ms
            migration.execution_time = elapsed_ms

            if exec_result.success:
                if self.history_manager:
                    try:
                        self.history_manager.record_migration(
                            migration, success=True, execution_time=elapsed_ms
                        )
                    except Exception as history_error:
                        self.log.error(
                            f"Failed to record migration history for {migration.script_name}: {history_error}"
                        )
                        result.set_error(f"Failed to record migration history: {history_error}")
                        _rollback_best_effort()
                        return

                if transaction_started and isinstance(self.provider, TransactionalProvider):
                    try:
                        self.provider.commit_transaction()
                    except Exception as commit_error:
                        self.log.error(
                            f"Failed to commit transaction for {migration.script_name}: {commit_error}"
                        )
                        result.set_error(f"Failed to commit transaction: {commit_error}")
                        _rollback_best_effort()
                        return

                if hasattr(result, "add_migration"):
                    result.add_migration(
                        MigrationInfo(
                            script=migration.script_name,
                            version=migration.version,
                            description=migration.description,
                            type=migration_type,
                            status="SUCCESS",
                            execution_time=elapsed_ms,
                            checksum=migration.checksum,
                        )
                    )
                self.log.info(
                    f"Migration {migration.script_name} executed successfully in {elapsed_ms}ms"
                )
            else:
                error_msg = (
                    exec_result.error or f"Script execution failed for type {migration_type}"
                )
                result.set_error(error_msg)
                _rollback_best_effort()
                if hasattr(result, "add_migration"):
                    result.add_migration(
                        MigrationInfo(
                            script=migration.script_name,
                            version=migration.version,
                            description=migration.description,
                            type=migration_type,
                            status="FAILED",
                            execution_time=elapsed_ms,
                            error=error_msg,
                        )
                    )
                # BUG-04: Python/non-SQL executor failures must leave a FAILED
                # row in dblift_schema_history so `repair` can detect and clear
                # them. Mirror the SQL failure path in _handle_statement_failure:
                # post-rollback, open a fresh transaction just to persist the
                # failure record, commit, then continue. Swallow history-write
                # errors — losing the history row is preferable to masking the
                # original migration failure.
                if self.history_manager:
                    try:
                        if isinstance(self.provider, TransactionalProvider):
                            self.provider.begin_transaction()
                        self.history_manager.record_migration(
                            migration, success=False, execution_time=elapsed_ms
                        )
                        if isinstance(self.provider, TransactionalProvider):
                            self.provider.commit_transaction()
                        result.failed_history_persisted = True
                        self.log.debug(f"Recorded FAILED history row for {migration.script_name}")
                    except Exception as history_e:
                        result.failed_history_persisted = False
                        if hasattr(result, "add_warning"):
                            result.add_warning(
                                f"Failed migration was not persisted to history: {history_e}"
                            )
                        self.log.warning(
                            f"Could not record failed migration {migration.script_name} in history: {history_e}"
                        )
                        if isinstance(self.provider, TransactionalProvider):
                            try:
                                self.provider.rollback_transaction()
                            except Exception:
                                # Best-effort: history recording already failed and the
                                # surrounding flow is itself an error path. A rollback
                                # exception here would only mask the original failure;
                                # swallowing keeps the upstream error visible.
                                pass
        except ValueError as e:
            error_msg = f"No executor found for format {migration.format}: {e}"
            self.log.error(error_msg)
            result.set_error(error_msg)
            _rollback_best_effort()
        except Exception as e:
            error_msg = f"Unexpected error during non-SQL execution: {e}"
            self.log.error(error_msg)
            result.set_error(error_msg)
            _rollback_best_effort()

    def execute_callback(self, callback: Migration) -> None:
        """Execute a callback migration.

        Args:
            callback: The callback migration to execute
        """
        # Route non-SQL callbacks to the executor factory (mirrors execute_migration routing — B5 fix)
        if callback.format != MigrationFormat.SQL:
            exec_result = self.executor_factory.execute(callback)
            if not exec_result.success:
                self.log.error(
                    f"Python callback {callback.script_name} failed: {exec_result.error}"
                )
                raise CallbackExecutionError(
                    f"Python callback {callback.script_name} failed: {exec_result.error}"
                )
            self.log.info(f"Python callback {callback.script_name} executed successfully")
            return

        # Pass our dialect to the migration to ensure proper SQL parsing
        dialect = self.sql_analyzer.dialect

        # Make sure the callback knows about our logger to avoid issues
        # where it might try to create its own DbliftLogger
        callback.dialect = dialect

        # Parse SQL statements, ensuring we use our logger
        try:
            sql_statements = callback.parse_sql_statements(dialect=dialect)
        except Exception as e:
            self.log.error(
                f"Error parsing SQL in callback {callback.script_name}: {to_python_string(e)}"
            )
            raise

        # Begin transaction for callback execution
        transaction_started = False
        try:
            self.provider.begin_transaction()
            transaction_started = True
            self.log.debug(f"Started transaction for callback {callback.script_name}")
        except Exception as e:
            self.log.warning(
                f"Could not begin transaction for callback {callback.script_name}: {e}"
            )
            # Continue without explicit transaction management

        schema = getattr(getattr(self.config, "database", None), "schema", None)
        if isinstance(schema, str) and schema:
            self.provider.set_current_schema(schema)

        # Execute SQL statements in the callback
        try:
            for statement in sql_statements:
                # Replace placeholders in the statement
                if self.placeholder_service:
                    statement = self.placeholder_service.replace_placeholders(statement)

                # Check what kind of SQL statement this is (DDL, DML, or query)
                statement_type = self.sql_analyzer.get_statement_type(statement)

                # Add more verbose debug logging about statement type
                if (
                    statement.strip().upper().startswith("CREATE VIEW")
                    or "SELECT" in statement.upper()
                ):
                    self.log.debug(
                        f"Callback statement classification: '{statement_type}' for statement: {statement[:LOG_STATEMENT_PREVIEW_LENGTH]}{'...' if len(statement) > LOG_STATEMENT_PREVIEW_LENGTH else ''}"
                    )

                # Execute statement using provider
                self.log.debug(f"Executing callback SQL: {statement}")

                try:
                    if self.sql_execution_service:
                        is_query, result_data = self.sql_execution_service.execute_statement(
                            statement
                        )
                        if is_query:
                            if result_data:
                                row_count = (
                                    len(result_data) if isinstance(result_data, list) else "unknown"
                                )
                                self.log.info(
                                    f"Query executed successfully, {row_count} rows returned"
                                )
                        else:
                            rows_affected = result_data if isinstance(result_data, int) else -1
                            if _is_ddl_statement_for_success_log(statement):
                                self.log.info("Statement executed successfully")
                            elif rows_affected is not None and rows_affected >= 0:
                                self.log.info(
                                    f"Statement executed successfully, {rows_affected} rows affected"
                                )
                            else:
                                self.log.info("Statement executed successfully")
                    elif statement_type == "QUERY":
                        # This is a SELECT statement - execute as query
                        query_result: List[Dict[str, Any]] = self.provider.execute_query(statement)
                        if query_result:
                            # Log query summary (e.g., "10 rows returned")
                            row_count = (
                                len(query_result) if isinstance(query_result, list) else "unknown"
                            )
                            self.log.info(f"Query executed successfully, {row_count} rows returned")
                    else:
                        # This is DDL or DML - execute as regular SQL
                        rows_affected = self.provider.execute_statement(statement)
                        if _is_ddl_statement_for_success_log(statement):
                            self.log.info("Statement executed successfully")
                        elif rows_affected is not None and rows_affected >= 0:
                            self.log.info(
                                f"Statement executed successfully, {rows_affected} rows affected"
                            )
                        else:
                            self.log.info("Statement executed successfully")

                except Exception as e:
                    self.log.error(f"Error executing callback SQL statement: {to_python_string(e)}")
                    self.log.error(f"Failed statement: {statement}")
                    raise

            # Commit transaction for successful callback execution
            try:
                self.provider.commit_transaction()
                self.log.debug(f"Committed transaction for callback {callback.script_name}")
            except Exception as e:
                self.log.warning(
                    f"Could not commit transaction for callback {callback.script_name}: {e}"
                )
                # Continue - the transaction might already be committed

        except Exception:
            # Rollback safety net for callback execution. Same rationale as the
            # migration-execution path above: ANY uncaught error here must rollback
            # before re-raise, narrowing would let unexpected types skip rollback.
            if transaction_started:
                try:
                    self.provider.rollback_transaction()
                    self.log.debug(
                        f"Rolled back transaction for failed callback {callback.script_name}"
                    )
                except Exception as rollback_e:
                    self.log.warning(
                        f"Could not rollback transaction for callback {callback.script_name}: {rollback_e}"
                    )
            # Re-raise the original exception
            raise

    def execute_callbacks(
        self, callbacks: List[Migration], callback_type: str = "AFTER_EACH"
    ) -> None:
        """Execute a list of callback migrations.

        Args:
            callbacks: List of callback migrations to execute
            callback_type: Type of callback (BEFORE_EACH, AFTER_EACH, etc.)
        """
        if not callbacks:
            return

        self.log.info(f"Executing {len(callbacks)} {callback_type.lower()} callback(s)")

        for callback in callbacks:
            try:
                self.log.info(f"Executing {callback_type.lower()} callback: {callback.script_name}")
                self.execute_callback(callback)
                self.log.info(f"Callback {callback.script_name} executed successfully")

            except Exception as e:
                self.log.error(f"Callback {callback.script_name} failed: {to_python_string(e)}")
                # For callbacks, we typically want to continue execution
                # rather than failing the entire migration
                continue
