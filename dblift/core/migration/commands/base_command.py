"""
Base command class with shared functionality for migration commands.
"""

from __future__ import annotations

import re
import sys
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Dict, Iterable, Iterator, List, Optional

from dblift.config import DbliftConfig
from dblift.config.database_config import BaseDatabaseConfig

if TYPE_CHECKING:
    from dblift.core.logger.results import OperationResult
    from dblift.core.migration.journals.migration_journal import MigrationJournal
    from dblift.core.migration.migration import Migration
    from dblift.core.migration.placeholders.placeholder_service import PlaceholderService
    from rich.panel import Panel
    from rich.text import Text

from dblift.core.exceptions import CallbackExecutionError
from dblift.core.logger import Log, NullLog
from dblift.core.logger.console import rich_available
from dblift.core.logger.log import LogFormat  # noqa: F401 - historical export
from dblift.core.logger.results import CallbackExecution
from dblift.core.migration.executor.execution_engine import ExecutionEngine
from dblift.core.migration.executor.migration_helpers import MigrationHelpers
from dblift.core.migration.formats.migration_format import MigrationFormat
from dblift.core.migration.history.migration_history_manager import MigrationHistoryManager
from dblift.core.migration.migration_types import MigrationType
from dblift.core.migration.presentation import presentation_for
from dblift.core.migration.rules.migration_rules import MigrationRules
from dblift.core.migration.scripting.migration_script_manager import MigrationScriptManager
from dblift.core.migration.state.migration_state import CallbackReadSnapshot, MigrationReadSnapshot
from dblift.core.migration.state.migration_state_manager import MigrationStateManager
from dblift.core.migration.ui.migration_ui import MigrationUI
from dblift.core.seams.runtime_checks import SqlPreflightError, registered_checks
from dblift.core.sql_validator.migration_validator import MigrationValidator
from dblift.core.utils.url_masking import mask_database_url
from dblift.db.base_provider import BaseProvider
from dblift.db.error import redact_driver_error_text
from dblift.db.provider_capabilities import (
    ensure_provider_connection,
    get_provider_display_url,
    get_provider_driver_display,
)
from dblift.db.provider_interfaces import SchemaProvider, TransactionalProvider
from dblift.db.provider_registry import ProviderRegistry

from ._script_events import emit_script_event as _emit_script_event

# Message text for a schema-history DDL failure during preflight. The
# raised type is PreflightConnectionError; the wording stays stable.
SCHEMA_HISTORY_CREATE_ERROR_PREFIX = "Could not create the schema-history table"

# Error reported by the commands that hold the migration lock when they cannot get it.
MIGRATION_LOCK_REFUSAL = "Could not acquire migration lock - another migration may be running"

# Shared by the CLI config validation and the command preflight.
SCHEMA_REQUIRED_ERROR = (
    "Database schema is required. Specify it in the config file, environment variables, "
    "or command line."
)


def is_required_schema_missing(database_config: BaseDatabaseConfig) -> bool:
    """True when the dialect needs a schema and none is set or derivable."""
    if database_config.schema or not database_config.type:
        return False
    quirks = ProviderRegistry.get_quirks(database_config.type)
    return quirks.schema_required and not quirks.derive_schema_name(database_config)


class PreflightConnectionError(ConnectionError):
    """Connection or schema-history failure raised during command preflight.

    Commands let it propagate; every ``DBLiftClient`` command method turns
    it into a failed result of its own type. It subclasses ``ConnectionError``, so
    handlers that already catch that type still catch it, and the message
    text is the same text those steps used to raise as ``ConnectionError``.
    """

    def __init__(self, message: str, result: Optional["OperationResult"] = None) -> None:
        """Store *message* and the command result this failure interrupted."""
        super().__init__(message)
        self.result = result


def reported_exception_name(error: BaseException) -> str:
    """Type name published in CLI JSON and MCP error text.

    ``PreflightConnectionError`` is how the two preflight steps are told
    apart in process. Callers still see ``ConnectionError: ...`` for both,
    which is the text those steps produced before the subclass existed.
    """
    if isinstance(error, PreflightConnectionError):
        return "ConnectionError"
    return type(error).__name__


@dataclass
class BaseCommandContext:
    """Groups the shared infrastructure dependencies for BaseCommand subclasses.

    Encapsulates the 13 parameters that every migration command receives,
    reducing constructor arity and making the call sites in migration_executor.py
    more maintainable (build the context once, pass it everywhere).

    Usage::

        ctx = BaseCommandContext(
            config=self.config,
            log=self.log,
            provider=self.provider,
            script_manager=self.script_manager,
            history_manager=self.history_manager,
            validator=self.validator,
            execution_engine=self.execution_engine,
            migration_helpers=self.migration_helpers,
            state_manager=self.state_manager,
            migration_ui=self.migration_ui,
            migration_rules=self.rules,
        )
        command = MigrateCommand(ctx)
    """

    config: DbliftConfig
    log: Log
    provider: BaseProvider
    script_manager: MigrationScriptManager
    history_manager: MigrationHistoryManager
    validator: MigrationValidator
    execution_engine: ExecutionEngine
    migration_helpers: MigrationHelpers
    state_manager: MigrationStateManager
    migration_ui: MigrationUI
    migration_rules: MigrationRules
    journal: Optional["MigrationJournal"] = field(default=None)
    placeholder_service: Optional["PlaceholderService"] = field(default=None)


def _props_text(*lines: str) -> Text:
    """Build a multi-line Text where 'Key: value' lines have bold keys."""
    from dblift.core.migration.ui.command_panels import props_text

    return props_text(*lines)


def _render_main_header_panel(raw_header: str) -> str:
    """Convert a TextFormatter ASCII header string into a Rich panel string.

    Shared by BaseCommand._print_main_header_once and higher-tier command
    modules so they render the same styled banner.
    """
    from dblift.core.migration.ui.command_panels import render_main_header_panel

    return render_main_header_panel(raw_header) if rich_available() else raw_header


# Maps ``_execute_callbacks``' ``event_prefix`` argument to the matching
# ``callback.*`` EventType value (api/events.py). Prefixes with no mapping
# (e.g. validate-command hooks, which no command wires up yet) are simply
# not emitted.
_CALLBACK_LIFECYCLE_EVENTS: Dict[str, str] = {
    "beforeMigrate": "callback.before_migrate",
    "afterMigrate": "callback.after_migrate",
    "afterMigrateError": "callback.after_migrate_error",
    "beforeEach": "callback.before_each",
    "afterEach": "callback.after_each",
    "beforeEachMigrate": "callback.before_each_migrate",
    "afterEachMigrate": "callback.after_each_migrate",
    "beforeRepeatable": "callback.before_repeatable",
    "afterRepeatable": "callback.after_repeatable",
    "beforeVersioned": "callback.before_versioned",
    "afterVersioned": "callback.after_versioned",
    "beforeValidate": "callback.before_validate",
    "afterValidate": "callback.after_validate",
    "beforeClean": "callback.before_clean",
    "afterClean": "callback.after_clean",
    "afterCleanError": "callback.after_clean_error",
    "beforeUndo": "callback.before_undo",
    "afterUndo": "callback.after_undo",
    "afterUndoError": "callback.after_undo_error",
}


@dataclass(frozen=True)
class _CallbackBinding:
    """Directory arguments a command passes to every callback dispatch."""

    scripts_dir: Optional[Path]
    recursive: bool
    additional_dirs: Optional[List[Path]]
    dir_recursive_map: Optional[Dict[Path, bool]]
    result: Optional["OperationResult"]


class BaseCommand:
    """Base class for migration commands with shared helper methods."""

    # Subclasses that render their own rich summary panel set this True
    # to skip the generic console footer and avoid duplication.
    _has_own_console_footer: bool = False

    _callback_binding: Optional[_CallbackBinding] = None

    def __init__(
        self,
        ctx_or_config: Any = None,
        log: Optional[Log] = None,
        provider: Optional[BaseProvider] = None,
        script_manager: Optional[MigrationScriptManager] = None,
        history_manager: Optional[MigrationHistoryManager] = None,
        validator: Optional[MigrationValidator] = None,
        execution_engine: Optional[ExecutionEngine] = None,
        migration_helpers: Optional[MigrationHelpers] = None,
        state_manager: Optional[MigrationStateManager] = None,
        migration_ui: Optional[MigrationUI] = None,
        migration_rules: Optional[MigrationRules] = None,
        journal: Optional["MigrationJournal"] = None,
        placeholder_service: Optional["PlaceholderService"] = None,
        # Legacy alias kept for call sites that pass config= as keyword
        config: Optional[DbliftConfig] = None,
    ):
        """Initialize base command.

        Accepts either a ``BaseCommandContext`` as the first positional argument
        (preferred, new-style) or the individual infrastructure dependencies as
        keyword arguments (legacy, backward-compatible).

        Args:
            ctx_or_config: A :class:`BaseCommandContext` instance **or** the
                application :class:`~config.DbliftConfig` (legacy positional use).
            log: Logger instance (legacy only; ignored when ctx provided)
            provider: Database provider (legacy only)
            script_manager: Script management component (legacy only)
            history_manager: History management component (legacy only)
            validator: Migration validator (legacy only)
            execution_engine: Core execution engine (legacy only)
            migration_helpers: Helper methods (legacy only)
            state_manager: Migration state manager (legacy only)
            migration_ui: Migration UI component (legacy only)
            migration_rules: Migration rules (legacy only)
            journal: Optional migration journal (legacy only)
            placeholder_service: Placeholder service (legacy only)
            config: Alias for ctx_or_config when passed as keyword (legacy only)
        """
        if isinstance(ctx_or_config, BaseCommandContext):
            ctx = ctx_or_config
        else:
            # Legacy path: individual params supplied (ctx_or_config holds config)
            _config = ctx_or_config if ctx_or_config is not None else config
            ctx = BaseCommandContext(
                config=_config,  # type: ignore[arg-type]
                log=log,  # type: ignore[arg-type]
                provider=provider,  # type: ignore[arg-type]
                script_manager=script_manager,  # type: ignore[arg-type]
                history_manager=history_manager,  # type: ignore[arg-type]
                validator=validator,  # type: ignore[arg-type]
                execution_engine=execution_engine,  # type: ignore[arg-type]
                migration_helpers=migration_helpers,  # type: ignore[arg-type]
                state_manager=state_manager,  # type: ignore[arg-type]
                migration_ui=migration_ui,  # type: ignore[arg-type]
                migration_rules=migration_rules,  # type: ignore[arg-type]
                journal=journal,
                placeholder_service=placeholder_service,
            )

        self.config = ctx.config
        self.log = ctx.log if ctx.log is not None else NullLog()
        self.provider = ctx.provider
        self.script_manager = ctx.script_manager
        self.history_manager = ctx.history_manager
        self.validator = ctx.validator
        self.execution_engine = ctx.execution_engine
        self.migration_helpers = ctx.migration_helpers
        self.state_manager = ctx.state_manager
        self.migration_ui = ctx.migration_ui
        self.migration_rules = ctx.migration_rules
        self.journal = ctx.journal
        self.placeholder_service = ctx.placeholder_service
        self._callback_snapshot: Optional[CallbackReadSnapshot] = None

    @property
    def _capture_objects(self) -> bool:
        """Keep legacy journals without a mode flag on the full-analysis path."""
        return getattr(self.journal, "capture_objects", True)

    def _reset_callback_catalog(self) -> None:
        """Discard the snapshot reference and callback binding before a command execution."""
        self._callback_snapshot = None
        self._callback_binding = None

    def _bind_callbacks(
        self,
        scripts_dir: Optional[Path],
        recursive: bool,
        additional_dirs: Optional[List[Path]],
        dir_recursive_map: Optional[Dict[Path, bool]],
        result: Optional["OperationResult"],
    ) -> None:
        """Remember the callback directory arguments for ``_fire``/``_callbacks_for``."""
        self._callback_binding = _CallbackBinding(
            scripts_dir, recursive, additional_dirs, dir_recursive_map, result
        )

    def _bound_callbacks(self) -> _CallbackBinding:
        binding = self._callback_binding
        if binding is None:
            raise RuntimeError("callbacks are not bound")
        return binding

    def _fire(self, event: str) -> None:
        """Run the callbacks of ``event`` with the arguments given to ``_bind_callbacks``.

        Does nothing when the command has no scripts directory.
        """
        binding = self._bound_callbacks()
        if binding.scripts_dir is None:
            return
        self._execute_callbacks(
            binding.scripts_dir,
            event,
            binding.recursive,
            binding.additional_dirs,
            binding.dir_recursive_map,
            result=binding.result,
        )

    def _callbacks_for(self, events: Iterable[str]) -> List[Migration]:
        """List the bound callbacks of ``events``, in event order, from one fresh snapshot."""
        binding = self._bound_callbacks()
        if binding.scripts_dir is None:
            return []
        snapshot = self.state_manager.new_callback_snapshot()
        return [
            callback
            for event in events
            for callback in self.state_manager.get_callbacks_by_event(
                binding.scripts_dir,
                event,
                read_snapshot=snapshot,
                recursive=binding.recursive,
                additional_dirs=binding.additional_dirs,
                dir_recursive_map=binding.dir_recursive_map,
            )
        ]

    def _execute_callbacks(
        self,
        scripts_dir: Path,
        event_prefix: str,
        use_recursive: bool,
        use_additional_dirs: Optional[List[Path]],
        dir_recursive_map: Optional[Dict[Path, bool]] = None,
        result: Optional["OperationResult"] = None,
    ) -> None:
        """Execute callbacks for a specific lifecycle event.

        Args:
            scripts_dir: Directory containing migration scripts
            event_prefix: Callback event prefix (e.g., 'beforeMigrate', 'afterMigrateError')
            use_recursive: Whether to search subdirectories recursively
            use_additional_dirs: Optional list of additional directories to search
            dir_recursive_map: Optional mapping of directory paths to their recursive settings
            result: Optional operation result to attach captured query results to
                (when ``result.show_query_results`` is enabled)

        Raises:
            Exception: If any callback fails (except for error callbacks which only log warnings)
        """
        read_snapshot = getattr(self, "_callback_snapshot", None)
        if read_snapshot is None:
            read_snapshot = self.state_manager.new_callback_snapshot()
            self._callback_snapshot = read_snapshot

        callbacks = self.state_manager.get_callbacks_by_event(
            scripts_dir,
            event_prefix,
            read_snapshot=read_snapshot,
            recursive=use_recursive,
            additional_dirs=use_additional_dirs,
            dir_recursive_map=dir_recursive_map,
        )

        if callbacks:
            # dedupe=False: for each-migration events (beforeEachMigrate,
            # afterEachMigrate, ...), this method is called once per migration
            # in the batch, and the message text is identical every time
            # (same callback set, same script names). The logger's time-window
            # deduplication otherwise silently swallows these lines for every
            # migration but the first, even though the callbacks themselves
            # execute for every migration.
            try:
                callback_count = len(callbacks) if hasattr(callbacks, "__len__") else None
                self.log.info(
                    f"Executing {callback_count if callback_count is not None else 'some'} "
                    f"{event_prefix} callback(s)",
                    dedupe=False,
                )
            except (TypeError, AttributeError):
                callback_count = None
                self.log.info(f"Executing {event_prefix} callback(s)", dedupe=False)

            lifecycle_event = _CALLBACK_LIFECYCLE_EVENTS.get(event_prefix)
            if lifecycle_event:
                _emit_script_event(
                    lifecycle_event, {"count": callback_count} if callback_count is not None else {}
                )

            for callback in callbacks:
                script_name = getattr(callback, "script_name", "")
                description = getattr(callback, "description", "") or ""
                record_name = description or Path(str(script_name)).stem
                record = CallbackExecution(event_prefix, record_name, str(script_name))
                if result is not None:
                    result.callbacks.append(record)
                started = time.perf_counter()
                try:
                    self.log.info(f"Executing callback: {callback.script_name}", dedupe=False)
                    _emit_script_event("callback.started", {"name": callback.script_name})
                    self.execution_engine.execute_callback(callback, result, record=record)
                    _emit_script_event("callback.completed", {"name": callback.script_name})
                    self.log.info(
                        f"Callback {callback.script_name} executed successfully", dedupe=False
                    )
                    record.status = "OK"
                except Exception as e:
                    record.status = "FAILED"
                    reason = redact_driver_error_text(str(e))
                    _emit_script_event(
                        "callback.failed", {"name": callback.script_name, "error": reason}
                    )
                    if isinstance(e, SqlPreflightError) and "Error" not in event_prefix:
                        raise
                    # Error callbacks (afterMigrateError, afterCleanError, afterUndoError) should only log warnings
                    # Regular callbacks should fail the entire operation
                    if "Error" in event_prefix:
                        self.log.warning(f"Error callback {callback.script_name} failed: {reason}")
                        # Don't raise - error callbacks failing should not stop execution
                    else:
                        # Regular callback failure should fail the entire operation
                        self.log.error(f"Callback {callback.script_name} failed: {reason}")
                        raise CallbackExecutionError(
                            f"Callback {callback.script_name} failed: {reason}"
                        ) from e
                finally:
                    record.duration_ms = int((time.perf_counter() - started) * 1000)

    def _log_current_schema_version(self) -> None:
        """Log the current schema version at the beginning of a command.

        Note: This method is deprecated - schema version is now included in the command header.
        Kept for backward compatibility but no longer logs to console (only debug logs).

        Note: This method assumes the schema and history table already exist.
        For commands that don't ensure this, call create_schema_and_history_table first.
        """
        try:
            # Get applied migrations to determine current version
            applied_migrations = self.state_manager.get_applied_migrations()

            # Check if applied_migrations is empty (handle Mock objects in tests)
            try:
                is_empty = not applied_migrations or (
                    hasattr(applied_migrations, "__len__") and len(applied_migrations) == 0
                )
            except (TypeError, AttributeError):
                # If we can't determine, assume it's not empty and continue
                is_empty = False

            if is_empty:
                # Only log to debug, not info (header will show it)
                self.log.debug("Current schema version: <none> (no migrations applied)")
                return

            # Get current version using the same logic as StateManager
            current_version = self.state_manager.get_current_version(applied_migrations)

            if current_version:
                # Only log to debug, not info (header will show it)
                self.log.debug(f"Current schema version: {current_version}")
            else:
                # Only log to debug, not info (header will show it)
                self.log.debug("Current schema version: <none> (no versioned migrations applied)")
        except Exception as e:
            # If we can't determine the version, log a debug message but don't fail
            self.log.debug(f"Could not determine current schema version: {e}")

    def _log_command_completion(self, command_name: str, result: Any) -> None:
        """Log command completion with status and execution time using uniform format.

        Args:
            command_name: Name of the command that completed
            result: OperationResult with execution time and success status
        """
        if result.end_time is None:
            result.complete()
        presenter = presentation_for(getattr(self, "execution_engine", None), self.log)
        if presenter is not None:
            presenter.present_command_result(self, command_name, result)

    def _build_footer_panel(
        self,
        command_name: str,
        success: bool,
        execution_time: str,
        error_message: Optional[str] = None,
        schema_version: Optional[str] = None,
        applied_scripts: Optional[List[Any]] = None,
    ) -> "Panel":
        """Build the footer Rich Panel. Returns (Panel, border_style)."""
        from dblift.core.migration.ui.command_panels import build_footer_panel

        return build_footer_panel(
            command_name, success, execution_time, error_message, schema_version, applied_scripts
        )

    def _format_command_footer(
        self,
        command_name: str,
        success: bool,
        execution_time: str,
        error_message: Optional[str] = None,
        schema_version: Optional[str] = None,
        applied_scripts: Optional[List[Any]] = None,
    ) -> str:
        """Format a uniform command footer for console output.

        Args:
            command_name: Name of the command that completed
            success: Whether the command succeeded
            execution_time: Formatted execution time string
            error_message: Optional ``result.error_message`` to surface on
                the failure path. ADR-0013: the pre-ADR footer
                always dropped this, leaving the operator with
                ``"Command X failed"`` and zero signal even when the
                command layer had captured a precise explanation.
            schema_version: Optional post-operation schema version.
                The header-only Schema Version was a snapshot
                taken *before* the command ran, so after an undo /
                migrate / baseline / clean it showed the stale value.
                Rendering the post-state version in the footer gives
                the operator an accurate view without having to re-run
                ``info``.

        Returns:
            Formatted footer string (plain, for file logs).
        """
        from dblift.core.logger.console import render_panel_to_str

        if not rich_available():
            lines = [
                f"{command_name} {'completed successfully' if success else 'FAILED'}"
                f" in {execution_time}"
            ]
            if schema_version:
                lines.append(f"Schema Version: {schema_version}")
            if error_message and not success:
                lines.append(f"Error: {error_message}")
            return "\n".join(lines)
        return render_panel_to_str(
            self._build_footer_panel(
                command_name,
                success,
                execution_time,
                error_message,
                schema_version,
                applied_scripts,
            ),
            width=80,
        )

    def _log_text_block(self, block: str) -> None:
        """Write a formatted header/footer block to text-based file logs.

        This logs command headers and footers to TEXT format file logs,
        matching the console output format.
        """
        if not block:
            return

        try:
            from dblift.core.logger.log import FileLog, MultiLog
        except (ImportError, AttributeError):
            # Silently ignore if logging modules are not available
            return

        if isinstance(self.log, FileLog):
            if getattr(self.log, "log_format", None) == LogFormat.TEXT:
                # Write the block directly to the file (not as a log event to avoid formatting)
                self.log._write_text_block(block)
            return

        if isinstance(self.log, MultiLog):
            for log in getattr(self.log, "logs", []):
                if isinstance(log, FileLog) and getattr(log, "log_format", None) == LogFormat.TEXT:
                    log._write_text_block(block)

    def _ensure_connected(self) -> None:
        """Ensure the provider has an active connection.

        Call this before any operation that reads connection metadata
        (e.g. _populate_database_info, _log_command_header_update) when
        create_schema_and_history_table may have been skipped (e.g. dry-run).

        Providers may expose ``_ensure_connection`` (connect-if-closed).
        Other providers and stubs fall back to ``connect()`` only
        when ``is_connected()`` reports False, to avoid duplicate connections.

        A failed connection attempt is re-raised through
        ``dblift.db.error.format_connection_error`` — the same formatter
        ``db check-connection`` uses — so every command reports connection
        failures with the identical friendly one-liner instead of a raw
        driver/SQLAlchemy exception.
        """
        try:
            if ensure_provider_connection(self.provider):
                return
            if not self.provider.is_connected():
                self.provider.connect()
        except Exception as exc:
            from dblift.db.error import format_connection_error

            db_type = getattr(self.provider, "canonical_dialect_key", "") or getattr(
                getattr(self.config, "database", None), "type", ""
            )
            message = format_connection_error(exc, str(db_type or ""))
            raise PreflightConnectionError(message) from exc

    def _preflight_connect(self, result: "OperationResult") -> None:
        """Preflight phase 1: ``_ensure_connected()``, attaching *result* on failure.

        ``_run_preflight`` starts with this; a command that must touch the
        connection before the rest of its preflight calls it first, so an
        unusable connection fails the same way.
        """
        # A dialect that needs a schema and derives none would otherwise run
        # against an empty one (e.g. DB2 ``CREATE SCHEMA ""``). Fail before
        # connecting, with the message the CLI refuses the command with.
        if is_required_schema_missing(self.config.database):
            raise PreflightConnectionError(SCHEMA_REQUIRED_ERROR, result)
        try:
            self._ensure_connected()
        except PreflightConnectionError as exc:
            # The command result already has target_schema. Keep this
            # exception object: a plain ConnectionError raised by a
            # replacement for _ensure_connected is not this type and
            # must propagate unchanged.
            exc.result = result
            raise

    def _prepare_required_analysis(self) -> None:
        """Prepare enriched SQL journaling before this command can write."""
        service = getattr(getattr(self, "execution_engine", None), "sql_execution_service", None)
        prepare = getattr(service, "prepare_analysis", None)
        if prepare is not None:
            prepare()

    def _preflight_execution_sql(self, migrations: List[Any]) -> None:
        """Classify selected SQL and run contextual extension checks before writes."""
        if self._capture_objects and not registered_checks("migration.preflight_sql"):
            return
        prepared = []
        for migration in migrations:
            statements = []
            if migration.format == MigrationFormat.SQL:
                statements = self.execution_engine._prepare_sql_statements(
                    migration, placeholder_service=self.placeholder_service
                )
                if not self._capture_objects:
                    self.execution_engine._classify_execution_statements(statements)
            prepared.append((migration, statements))
        prepared_migrations = [item for item in prepared if item[0].type != MigrationType.CALLBACK]
        migration_index = 0
        for migration, statements in prepared:
            is_callback = migration.type == MigrationType.CALLBACK
            index = None if is_callback else migration_index
            if not is_callback:
                migration_index += 1
            if migration.format == MigrationFormat.SQL:
                self.execution_engine.check_sql_preflight(
                    migration,
                    statements,
                    prepared_migrations=[] if is_callback else prepared_migrations,
                    migration_index=index,
                )

    def _prepare_analysis_for_sql_callbacks(
        self,
        scripts_dir: Path,
        events: tuple[str, ...],
        recursive: bool,
        additional_dirs: Optional[List[Path]],
        dir_recursive_map: Optional[Dict[Path, bool]],
    ) -> None:
        """Prepare only when this command's callback catalog contains SQL."""
        snapshot = self.state_manager.new_callback_snapshot()
        self._callback_snapshot = snapshot
        for event in events:
            callbacks = self.state_manager.get_callbacks_by_event(
                scripts_dir,
                event,
                read_snapshot=snapshot,
                recursive=recursive,
                additional_dirs=additional_dirs,
                dir_recursive_map=dir_recursive_map,
            )
            sql_callbacks = [c for c in callbacks if c.format == MigrationFormat.SQL]
            if sql_callbacks:
                self._prepare_required_analysis()
                if self._capture_objects:
                    return
                for callback in sql_callbacks:
                    statements = self.execution_engine._prepare_sql_statements(
                        callback, placeholder_service=self.placeholder_service
                    )
                    self.execution_engine._classify_execution_statements(statements)

    def _run_preflight(
        self,
        result: Any,
        *,
        ensure_history: bool = False,
        dry_run: bool = False,
        create_schema: bool = False,
        ensure_schema: bool = False,
    ) -> None:
        """Run the canonical pre-execute lifecycle for every command.

        Three phases, fixed order (ADR-0011):

          1. ``_ensure_connected()`` — the provider must be live before
             any metadata read or DDL.
          2. ``create_schema_and_history_table()`` when
             ``ensure_history=True`` AND not ``dry_run`` — commands that
             initialize history (``migrate``, ``baseline``, ``validate``,
             ``repair``, ``import-flyway``) call this idempotently; dry-run
             skips it (PR-02 byte-identical contract). A failure here names
             the step (``Could not create the schema-history table: ...``)
             rather than reusing ``_ensure_connected``'s generic
             ``Connection failed: ...``, because the provider is already
             connected at this point — what failed is the DDL, not the
             connection. Both steps raise ``PreflightConnectionError``.
          3. ``_populate_database_info(result)`` — reads live connection
             metadata onto the result. Must come AFTER phases 1 and 2
             because it calls provider methods that require a connection
             (and on first ``migrate`` the history table may need to exist
             for version introspection).

        Call this exactly once at the start of ``execute()`` instead of
        re-ordering the three calls manually. Bugbot PR 160 flagged the
        order-of-operations bug in ``info_command`` that this helper
        prevents by construction.

        Args:
            result: OperationResult to populate with database metadata.
            ensure_history: If True, create the schema history table when
                not in dry-run. ``migrate``, ``baseline``, ``validate``,
                ``repair`` and ``import-flyway`` pass True; ``info`` and
                ``undo`` read missing history as empty.
            dry_run: Skip history-table creation when True, regardless
                of ``ensure_history``. ``_ensure_connected`` and
                ``_populate_database_info`` still run — dry-run must
                still produce accurate output. Pass the command's own
                dry-run flag only when that command must skip the
                history table as a dry-run side effect (``migrate``,
                ``baseline``).
            create_schema: Forwarded to
                ``create_schema_and_history_table(create_schema=...)``.
                ``baseline`` passes True to enable its history safety checks.
            ensure_schema: Create a missing target schema for ``migrate``
                without enabling baseline history safety checks.
        """
        self._preflight_connect(result)
        if ensure_history and not dry_run:
            try:
                if ensure_schema:
                    self.history_manager.create_schema_and_history_table(
                        create_schema=create_schema, ensure_schema=True
                    )
                else:
                    self.history_manager.create_schema_and_history_table(
                        create_schema=create_schema
                    )
            except Exception as exc:
                from dblift.core.migration.sql.sql_execution_service import (
                    _format_execution_error,
                )
                from dblift.db.error import strip_sql_statement_block

                # Strip the generated DDL SQLAlchemy appends to
                # statement-bound errors (see strip_sql_statement_block in
                # dblift.db.error) so a schema/history-table setup failure
                # never leaks the CREATE TABLE text, matching
                # format_connection_error's existing guarantee. The
                # formatted message can itself strip down to empty (e.g. the
                # wrapped exception carried no text of its own, only the SQL
                # block) -- the fallback is then the same SQL-stripped
                # str(exc), never the raw exception, which would still carry
                # the unstripped block; only when even that is empty does
                # the raw text get used as a last resort.
                try:
                    formatted = strip_sql_statement_block(_format_execution_error(exc))
                except Exception:
                    formatted = ""
                if not formatted:
                    formatted = redact_driver_error_text(strip_sql_statement_block(str(exc)))
                raise PreflightConnectionError(
                    f"{SCHEMA_HISTORY_CREATE_ERROR_PREFIX}: {formatted or exc}",
                    result,
                ) from exc
        self._populate_database_info(result)

    @contextmanager
    def _migration_lock(self) -> Iterator[bool]:
        """Hold the cross-process migration lock for the duration of the block.

        Yields whether the lock was acquired; the caller reports a refusal. The
        lock is released on every exit, including exceptions, and only when it
        was acquired.
        """
        acquired = self.provider.acquire_migration_lock(
            self.config.database.schema, wait_timeout_seconds=60
        )
        # The guard starts on the very next statement: a signal turned into
        # SystemExit anywhere after the acquire must still reach the release.
        try:
            if not acquired:
                yield False
                return
            self.log.info("Migration lock acquired successfully")
            yield True
        finally:
            if acquired:
                try:
                    released = self.provider.release_migration_lock(self.config.database.schema)
                    if released is False:
                        self.log.warning(
                            "The migration lock was no longer held by this run "
                            "(lost or already released); nothing to release"
                        )
                    else:
                        self.log.debug("Migration lock released successfully")
                except Exception as release_e:
                    self.log.warning(f"Could not release migration lock: {release_e}")

    def _migration_lock_lost(self) -> bool:
        """Whether the provider reports the migration lock it holds as lost."""
        lock_lost = getattr(self.provider, "migration_lock_lost", None)
        return callable(lock_lost) and lock_lost() is True

    def _run_error_handler(self, command_name: str, handler: Callable[[], None]) -> None:
        """Run an error handler; a failure is logged at debug level, never raised."""
        try:
            handler()
        except Exception as handler_error:
            self.log.debug(f"Error handler for {command_name} failed: {handler_error}")

    def _run_command_lifecycle(
        self,
        command_name: str,
        result: Any,
        body: Callable[[], None],
        *,
        preflight: Optional[Callable[[], None]] = None,
        before_body: Optional[Callable[[], None]] = None,
        error_message_prefix: Optional[str] = None,
        header_kwargs: Optional[Dict[str, Any]] = None,
        on_error: Optional[Callable[[], None]] = None,
    ) -> Any:
        """Run the common command skeleton while preserving legacy semantics.

        This private helper is intentionally small: it sequences preflight,
        command header, optional pre-body work, command body, and completion
        footer without forcing every command into the same shape at once.
        Preflight and header exceptions still propagate, matching existing
        command behavior; only body exceptions are converted to ``result``
        errors for commands that previously did that locally.

        Once preflight has run, the footer is logged exactly once on every exit.
        When the body raises, the error is set, ``on_error`` runs (a failure in
        it is only logged at debug level), then the footer is logged. A
        ``PreflightConnectionError`` raised by the body, such as a second
        connection or history check, propagates without a footer, as one from
        ``preflight`` does.
        """
        if preflight is not None:
            preflight()
        self._log_command_header_update(command_name, **(header_kwargs or {}))
        if before_body is not None:
            before_body()

        try:
            body()
        except PreflightConnectionError:
            raise
        except Exception as e:
            message = f"{error_message_prefix}: {e}" if error_message_prefix else str(e)
            self.log.error(message)
            result.set_error(message)
            if on_error is not None:
                self._run_error_handler(command_name, on_error)

        self._log_command_completion(command_name, result)
        return result

    def _populate_database_info(self, result: Any) -> None:
        """Populate database connection information in the result object.

        Args:
            result: OperationResult to populate with database info
        """
        try:
            # Get database version - ensure connection is available first
            if isinstance(self.provider, SchemaProvider):
                try:
                    # Ensure we have a connection before getting database version
                    ensure_provider_connection(self.provider)
                    result.db_version = self.provider.get_database_version()
                except Exception as version_error:
                    self.log.warning(f"Could not determine database version: {version_error}")
                    result.db_version = "Unknown"

            # Get provider display URL (masked for security)
            display_url = get_provider_display_url(self.provider, self.config)
            if isinstance(display_url, str):
                result.database_url_masked = mask_database_url(display_url)

                # URL is now logged in command header, only log to debug here.
                self.log.debug(f"Database URL: {result.database_url_masked}")

                # Extract server name from URL when it has a network location.
                match = re.search(r"://([^:/]+)", display_url)
                if match:
                    result.server_name = match.group(1)

            # Get driver info from plugin-declared quirks.
            try:
                result.native_driver = get_provider_driver_display(self.provider, self.config)
            except (AttributeError, RuntimeError) as e:
                # Driver info not available - log at debug level if enabled
                if (
                    hasattr(self, "log")
                    and hasattr(self.log, "is_debug_enabled")
                    and self.log.is_debug_enabled()
                ):
                    self.log.debug(f"Could not retrieve native driver info: {e}")
                result.native_driver = None  # Don't set "Unknown Native Driver"

        except Exception as e:
            self.log.debug(f"Could not retrieve database connection info: {e}")

    def _format_command_header(
        self,
        command_name: str,
        filters: List[str],
        schema_version: Optional[str] = None,
        database_url: Optional[str] = None,
        connection_info: Optional[str] = None,
        database_name: Optional[str] = None,
        schema_name: Optional[str] = None,
    ) -> str:
        """Format a uniform command header for console output.

        Args:
            command_name: Name of the command being executed
            filters: List of filter options used
            schema_version: Current schema version (if available)
            database_url: Masked database URL (if available) - kept for backward compatibility
            connection_info: Connection information string (if available)
            database_name: Database name (if available)
            schema_name: Schema name (if available)

        Returns:
            Formatted header string (plain, for file logs). Use
            ``_build_command_header_panel`` for the console-rendered version.
        """
        from dblift.core.logger.console import render_panel_to_str

        if not rich_available():
            lines = [f"Command: {command_name}"]
            lines.extend(filters or [])
            if schema_version:
                lines.append(f"Schema Version: {schema_version}")
            if connection_info:
                lines.append(f"Connection: {connection_info}")
            return "\n".join(lines)
        return render_panel_to_str(
            self._build_command_header_panel(
                command_name,
                filters,
                schema_version,
                database_url,
                connection_info,
                database_name,
                schema_name,
            ),
            width=80,
        )

    def _build_command_header_panel(
        self,
        command_name: str,
        filters: Optional[List[str]] = None,
        schema_version: Optional[str] = None,
        database_url: Optional[str] = None,
        connection_info: Optional[str] = None,
        database_name: Optional[str] = None,
        schema_name: Optional[str] = None,
    ) -> "Panel":
        """Build the command header as a Rich Panel (with bold keys, no color strip)."""
        from dblift.core.migration.ui.command_panels import build_command_header_panel

        return build_command_header_panel(
            command_name,
            filters,
            schema_version,
            database_url,
            connection_info,
            database_name,
            schema_name,
            getattr(getattr(self, "config", None), "database", None),
        )

    def _build_filters_list(
        self,
        dry_run: bool = False,
        target_version: Optional[str] = None,
        tags: Optional[str] = None,
        exclude_tags: Optional[str] = None,
        versions: Optional[str] = None,
        exclude_versions: Optional[str] = None,
        **kwargs: Any,
    ) -> List[str]:
        """Build the CLI filter flags list from command parameters.

        Args:
            dry_run: Whether this is a dry run
            target_version: Target version filter
            tags: Tags filter
            exclude_tags: Exclude tags filter
            versions: Versions filter
            exclude_versions: Exclude versions filter
            **kwargs: Additional command-specific filters

        Returns:
            List of formatted filter strings (e.g. ``["--dry-run", "--tags=foo"]``)
        """
        filters = []
        if dry_run:
            filters.append("--dry-run")
        if target_version and isinstance(target_version, str):
            filters.append(f"--target-version={target_version}")
        if tags and isinstance(tags, str):
            filters.append(f"--tags={tags}")
        if exclude_tags and isinstance(exclude_tags, str):
            filters.append(f"--exclude-tags={exclude_tags}")
        if versions and isinstance(versions, str):
            filters.append(f"--versions={versions}")
        if exclude_versions and isinstance(exclude_versions, str):
            filters.append(f"--exclude-versions={exclude_versions}")

        for key, value in kwargs.items():
            if value is not None and value is not False:
                if isinstance(value, bool):
                    filters.append(f"--{key.replace('_', '-')}")
                elif isinstance(value, (str, int, float)):
                    filters.append(f"--{key.replace('_', '-')}={value}")

        return filters

    def _resolve_current_schema_version(
        self, *, read_snapshot: Optional[MigrationReadSnapshot] = None
    ) -> Optional[str]:
        """Ask the state manager for the current version; unavailable history omits it."""
        try:
            return self.state_manager.resolve_current_schema_version(read_snapshot)
        except Exception as e:
            self.log.debug(f"Could not retrieve schema version: {e}")
            # A failed read aborts PostgreSQL's transaction; roll it back so the
            # command's own history read reports the real error instead of
            # InFailedSqlTransaction. A rollback that fails means the connection
            # itself is unusable, so that error is left to propagate.
            if isinstance(self.provider, TransactionalProvider):
                self.provider.rollback_transaction()
            return None

    def _resolve_database_url_masked(self) -> Optional[str]:
        """Resolve and mask the provider database URL.

        Returns:
            Masked database URL string, or ``None`` if not available.
        """
        try:
            display_url = get_provider_display_url(self.provider, self.config)
            if display_url:
                return mask_database_url(display_url)
        except (AttributeError, RuntimeError, ValueError) as e:
            if (
                hasattr(self, "log")
                and hasattr(self.log, "is_debug_enabled")
                and self.log.is_debug_enabled()
            ):
                self.log.debug(f"Could not retrieve database URL: {e}")
        return None

    def _resolve_connection_info(self) -> Optional[str]:
        """Build a human-readable connection info string for the header.

        Returns:
            Connection info string such as
            ``"Connected to database mydb (PostgreSQL 15.2)"``,
            or ``None`` if not available.
        """
        try:
            db_name = getattr(self.config.database, "database_name", None) or getattr(
                self.config.database, "database", None
            )
            if db_name and isinstance(self.provider, SchemaProvider):
                version_info = self.provider.get_database_version()
                if version_info:
                    return f"Connected to database {db_name} ({version_info})"
        except (AttributeError, RuntimeError, ValueError) as e:
            if (
                hasattr(self, "log")
                and hasattr(self.log, "is_debug_enabled")
                and self.log.is_debug_enabled()
            ):
                self.log.debug(f"Could not retrieve connection info: {e}")
        return None

    def _is_console_output(self) -> bool:
        """Return True if the current logger includes a console (stdout) sink.

        Used to decide whether to ``print()`` formatted headers/footers.
        """
        from dblift.core.logger.log import ConsoleLog, MultiLog

        if isinstance(self.log, MultiLog):
            return any(isinstance(log, ConsoleLog) for log in self.log.logs)
        return isinstance(self.log, ConsoleLog)

    def _print_main_header_once(self) -> None:
        """Print the application-level text header to the console exactly once.

        Uses a module-level flag so that the header is not repeated when
        multiple commands run in the same process.
        """
        from dblift.core.logger.log import TextFormatter

        current_module = sys.modules[__name__]
        if not hasattr(current_module, "_console_main_header_printed"):
            current_module._console_main_header_printed = False  # type: ignore[attr-defined]

        if not current_module._console_main_header_printed:
            database_name = getattr(self.config.database, "database_name", None) or getattr(
                self.config.database, "database", None
            )
            schema_name = getattr(self.config.database, "schema", None)

            formatter = TextFormatter()
            raw = formatter.format_header(schema_name, database_name)
            if raw:
                # Route to stderr so machine-readable formats (--format json)
                # receive clean stdout. Human-format callers going through
                # cli.main already emit the banner via CommandOutput.banner()
                # (which also routes to stderr in machine mode) and set the
                # _console_main_header_printed flag, so this path is only
                # reached in edge cases where it is safe to use stderr.
                print(
                    _render_main_header_panel(raw), file=sys.stderr
                )  # lint: allow-print  banner fallback
            current_module._console_main_header_printed = True  # type: ignore[attr-defined]

    def _log_command_header_update(
        self,
        command_name: str,
        target_version: Optional[str] = None,
        dry_run: bool = False,
        tags: Optional[str] = None,
        exclude_tags: Optional[str] = None,
        versions: Optional[str] = None,
        exclude_versions: Optional[str] = None,
        read_snapshot: Optional[MigrationReadSnapshot] = None,
        **kwargs: Any,
    ) -> None:
        """Update command header with schema version and connection info after connection is established.

        Orchestrates five focused helpers:
        1. :meth:`_build_filters_list` — CLI filter flags
        2. :meth:`_resolve_current_schema_version` — current schema version
        3. :meth:`_resolve_database_url_masked` — masked database URL
        4. :meth:`_resolve_connection_info` — human-readable connection string
        5. :meth:`_print_main_header_once` + :meth:`_is_console_output` — console output

        Args:
            command_name: Name of the command being executed
            target_version: Target version filter
            dry_run: Whether this is a dry run
            tags: Tags filter
            exclude_tags: Exclude tags filter
            versions: Versions filter
            exclude_versions: Exclude versions filter
            **kwargs: Additional command-specific filters
        """
        presenter = presentation_for(getattr(self, "execution_engine", None), self.log)
        if presenter is not None:
            presenter.present_command_start(
                self,
                command_name,
                target_version=target_version,
                dry_run=dry_run,
                tags=tags,
                exclude_tags=exclude_tags,
                versions=versions,
                exclude_versions=exclude_versions,
                read_snapshot=read_snapshot,
                **kwargs,
            )
