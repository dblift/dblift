"""
Base command class with shared functionality for migration commands.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional

from config import DbliftConfig

if TYPE_CHECKING:
    from core.migration.journals.migration_journal import MigrationJournal
    from core.migration.placeholders.placeholder_service import PlaceholderService
    from rich.panel import Panel
    from rich.text import Text

from core.exceptions import CallbackExecutionError
from core.logger import Log, NullLog
from core.logger.log import LogFormat
from core.migration.executor.execution_engine import ExecutionEngine
from core.migration.executor.migration_helpers import MigrationHelpers
from core.migration.history.migration_history_manager import MigrationHistoryManager
from core.migration.migration import VERSIONED_SCRIPT_TYPES
from core.migration.rules.migration_rules import MigrationRules
from core.migration.scripting.migration_script_manager import MigrationScriptManager
from core.migration.state.migration_state_manager import MigrationStateManager
from core.migration.ui.migration_ui import MigrationUI
from core.sql_validator.migration_validator import MigrationValidator
from core.utils.url_masking import mask_database_url
from db.base_provider import BaseProvider
from db.provider_capabilities import (
    ensure_provider_connection,
    get_provider_display_url,
    get_provider_driver_display,
)
from db.provider_interfaces import SchemaProvider


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
        command = MigrateCommand(ctx, snapshot_service=self.snapshot_service)
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
    from rich.text import Text

    body = Text()
    for i, line in enumerate(lines):
        line = str(line) if line is not None else ""
        if ": " in line:
            key, _, val = line.partition(": ")
            body.append(key + ": ", style="bold")
            body.append(val)
        else:
            body.append(line)
        if i < len(lines) - 1:
            body.append("\n")
    return body


def _render_main_header_panel(raw_header: str) -> str:
    """Convert a TextFormatter ASCII header string into a Rich panel string.

    Shared by BaseCommand._print_main_header_once, snapshot_command, and
    export_schema_command so all three render the same styled banner.
    """
    from rich import box
    from rich.panel import Panel

    from core.logger.console import render_panel_to_str

    _skip = {"DBLIFT DATABASE MIGRATION LOG"}
    body_lines = [
        line
        for line in raw_header.splitlines()
        if line and not line.startswith("=") and not line.startswith("-") and line not in _skip
    ]
    return render_panel_to_str(
        Panel(
            "\n".join(body_lines), title="DBLIFT DATABASE MIGRATION LOG", box=box.HEAVY, expand=True
        ),
        width=80,
    )


class BaseCommand:
    """Base class for migration commands with shared helper methods."""

    # Subclasses that render their own rich summary panel set this True
    # to skip the generic console footer and avoid duplication.
    _has_own_console_footer: bool = False

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

    def _execute_callbacks(
        self,
        scripts_dir: Path,
        event_prefix: str,
        use_recursive: bool,
        use_additional_dirs: Optional[List[Path]],
        dir_recursive_map: Optional[Dict[Path, bool]] = None,
    ) -> None:
        """Execute callbacks for a specific lifecycle event.

        Args:
            scripts_dir: Directory containing migration scripts
            event_prefix: Callback event prefix (e.g., 'beforeMigrate', 'afterMigrateError')
            use_recursive: Whether to search subdirectories recursively
            use_additional_dirs: Optional list of additional directories to search
            dir_recursive_map: Optional mapping of directory paths to their recursive settings

        Raises:
            Exception: If any callback fails (except for error callbacks which only log warnings)
        """
        callbacks = self.script_manager.get_callbacks_by_event(
            scripts_dir,
            event_prefix,
            recursive=use_recursive,
            additional_dirs=use_additional_dirs,
            dir_recursive_map=dir_recursive_map,
        )

        if callbacks:
            try:
                callback_count = len(callbacks) if hasattr(callbacks, "__len__") else "some"
                self.log.info(f"Executing {callback_count} {event_prefix} callback(s)")
            except (TypeError, AttributeError):
                self.log.info(f"Executing {event_prefix} callback(s)")
            for callback in callbacks:
                try:
                    self.log.info(f"Executing callback: {callback.script_name}")
                    self.execution_engine.execute_callback(callback)
                    self.log.info(f"Callback {callback.script_name} executed successfully")
                except Exception as e:
                    # Error callbacks (afterMigrateError, afterCleanError, afterUndoError) should only log warnings
                    # Regular callbacks should fail the entire operation
                    if "Error" in event_prefix:
                        self.log.warning(f"Error callback {callback.script_name} failed: {e}")
                        # Don't raise - error callbacks failing should not stop execution
                    else:
                        # Regular callback failure should fail the entire operation
                        self.log.error(f"Callback {callback.script_name} failed: {e}")
                        raise CallbackExecutionError(
                            f"Callback {callback.script_name} failed: {e}"
                        ) from e

    def _log_current_schema_version(self) -> None:
        """Log the current schema version at the beginning of a command.

        Note: This method is deprecated - schema version is now included in the command header.
        Kept for backward compatibility but no longer logs to console (only debug logs).

        Note: This method assumes the schema and history table already exist.
        For commands that don't ensure this, call create_schema_and_history_table first.
        """
        try:
            # Get applied migrations to determine current version
            applied_migrations = self.history_manager.get_applied_migrations()

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
        # Mark as complete if not already done to get execution time
        if result.end_time is None:
            result.complete()

        execution_time_ms = result.execution_time()

        # Format execution time appropriately
        if execution_time_ms < 1000:
            time_str = f"{execution_time_ms} ms"
        elif execution_time_ms < 60000:
            time_seconds = execution_time_ms / 1000.0
            time_str = f"{time_seconds:.2f} s"
        else:
            time_minutes = execution_time_ms / 60000.0
            time_str = f"{time_minutes:.2f} min"

        # Format and log footer (only for text-based console output)
        from core.logger.log import ConsoleLog, FileLog, MultiLog

        # Check if we should print to console
        should_print_footer = False
        has_console_log = False
        has_file_log = False
        if isinstance(self.log, MultiLog):
            # MultiLog - check if any is console or file
            for log in self.log.logs:
                if isinstance(log, ConsoleLog):
                    should_print_footer = True
                    has_console_log = True
                elif isinstance(log, FileLog):
                    has_file_log = True
        elif isinstance(self.log, ConsoleLog):
            # Console log - print footer
            should_print_footer = True
            has_console_log = True
        elif isinstance(self.log, FileLog):
            # File log only
            has_file_log = True

        # Don't log completion message to console - the footer already shows it
        # But still log to file logs (HTML/JSON) for record keeping
        status = "SUCCESS" if result.success else "FAILED"
        if has_file_log and isinstance(self.log, MultiLog):
            # MultiLog with file log - log only to file logs, not console
            for log in self.log.logs:
                if isinstance(log, FileLog) and not isinstance(log, ConsoleLog):
                    if getattr(log, "log_format", None) == LogFormat.TEXT:
                        continue
                    log.info(f"Command {command_name} completed with status {status} in {time_str}")
        elif has_file_log and not has_console_log:
            # File log only, no console - log the message
            if getattr(self.log, "log_format", None) != LogFormat.TEXT:
                self.log.info(
                    f"Command {command_name} completed with status {status} in {time_str}"
                )

        # BUG-11: resolve the schema version *after* the operation has run
        # so the footer reflects the post-state (undo rolling back V3 now
        # shows "Schema Version: 3" in the footer, not the pre-op "4" that
        # the header emitted at command start). Resolution can fail for
        # legitimate reasons (clean just dropped the history table, commands
        # that never initialised a history_manager, stub providers in
        # tests) — any failure means the footer cleanly omits the line
        # rather than interrupting the status line. The debug log itself
        # is also wrapped defensively because stubbed logs in unit tests
        # may lack the expected attributes.
        post_op_schema_version: Optional[str] = None
        if hasattr(self, "history_manager") and self.history_manager is not None:
            try:
                post_op_schema_version = self._resolve_current_schema_version()
            except Exception as e:
                try:
                    self.log.debug(f"Could not resolve post-operation schema version: {e}")
                except Exception:
                    pass

        # Only collect applied script names for the migrate command.
        # Other commands (info, clean, repair, baseline, …) may also have a
        # `migrations` attribute but those entries are historical records, not
        # scripts applied in the current run — listing them in the footer would
        # be misleading.
        # Script names are already logged line-by-line during execution.
        # Footer only surfaces "nothing to apply" as a note.
        applied_scripts = None
        if command_name.lower() == "migrate":
            raw_migrations = getattr(result, "migrations", None)
            if raw_migrations is not None and result.success:
                has_applied = any(
                    getattr(m, "status", "") in ("SUCCESS", "Success") for m in raw_migrations
                )
                if not has_applied:
                    dry_run_count = getattr(result, "dry_run_count", 0)
                    if dry_run_count:
                        applied_scripts = [
                            f"Dry run — {dry_run_count} migration(s) would be applied"
                        ]
                    else:
                        applied_scripts = ["No pending migrations found"]

        # Print footer to console if applicable
        footer_args = dict(
            command_name=command_name,
            success=result.success,
            execution_time=time_str,
            error_message=getattr(result, "error_message", None),
            schema_version=post_op_schema_version,
            applied_scripts=applied_scripts,
        )
        if should_print_footer and not self._has_own_console_footer:
            from core.logger.console import get_stdout_console

            get_stdout_console().print(self._build_footer_panel(**footer_args))
        self._log_text_block(self._format_command_footer(**footer_args))

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
        from rich import box
        from rich.panel import Panel
        from rich.text import Text

        _STATUS_STYLE = {"SUCCESS": "bold green", "WARNING": "yellow", "FAILED": "bold red"}

        title = "SUCCESS" if success else "FAILED"
        border_style = _STATUS_STYLE.get(title, "default")

        status_msg = (
            f"Command {command_name.upper()} completed successfully (Execution time: {execution_time})"
            if success
            else f"Command {command_name.upper()} failed (Execution time: {execution_time})"
        )

        body = Text()
        if applied_scripts:
            for script in applied_scripts:
                body.append(f"  - {script}\n")
        body.append(str(status_msg))
        if not success and error_message:
            body.append("\n")
            body.append("Error: ", style="bold")
            fmt = str(error_message).rstrip()
            if "\n" in fmt:
                body.append("\n" + "\n".join("  " + ln for ln in fmt.splitlines()))
            else:
                body.append(fmt)
        if schema_version:
            body.append("\n")
            body.append("Schema Version: ", style="bold")
            body.append(str(schema_version))

        return Panel(body, title=title, box=box.HEAVY, border_style=border_style, expand=True)

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
                the failure path. BUG-01 (ADR-0013): the pre-ADR footer
                always dropped this, leaving the operator with
                ``"Command X failed"`` and zero signal even when the
                command layer had captured a precise explanation.
            schema_version: Optional post-operation schema version.
                BUG-11: the header-only Schema Version was a snapshot
                taken *before* the command ran, so after an undo /
                migrate / baseline / clean it showed the stale value.
                Rendering the post-state version in the footer gives
                the operator an accurate view without having to re-run
                ``info``.

        Returns:
            Formatted footer string (plain, for file logs).
        """
        from core.logger.console import render_panel_to_str

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
            from core.logger.log import FileLog, LogFormat, MultiLog
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
        """
        if ensure_provider_connection(self.provider):
            return
        if not self.provider.is_connected():
            self.provider.connect()

    def _run_preflight(
        self,
        result: Any,
        *,
        ensure_history: bool = False,
        dry_run: bool = False,
    ) -> None:
        """Run the canonical pre-execute lifecycle for every command.

        Three phases, fixed order (ADR-0011):

          1. ``_ensure_connected()`` — the provider must be live before
             any metadata read or DDL.
          2. ``create_schema_and_history_table()`` when
             ``ensure_history=True`` AND not ``dry_run`` — commands that
             require the history table (``migrate``, ``info``) call this
             idempotently; dry-run skips it (PR-02 byte-identical
             contract).
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
                not in dry-run. ``migrate`` and ``info`` pass True;
                ``clean`` passes False (it doesn't need history).
            dry_run: Skip history-table creation when True, regardless
                of ``ensure_history``. ``_ensure_connected`` and
                ``_populate_database_info`` still run — dry-run must
                still produce accurate output.
        """
        self._ensure_connected()
        if ensure_history and not dry_run:
            self.history_manager.create_schema_and_history_table(create_schema=False)
        self._populate_database_info(result)

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
    ) -> Any:
        """Run the common command skeleton while preserving legacy semantics.

        This private helper is intentionally small: it sequences preflight,
        command header, optional pre-body work, command body, and completion
        footer without forcing every command into the same shape at once.
        Preflight and header exceptions still propagate, matching existing
        command behavior; only body exceptions are converted to ``result``
        errors for commands that previously did that locally.
        """
        if preflight is not None:
            preflight()
        self._log_command_header_update(command_name, **(header_kwargs or {}))
        if before_body is not None:
            before_body()

        try:
            body()
        except Exception as e:
            message = f"{error_message_prefix}: {e}" if error_message_prefix else str(e)
            self.log.error(message)
            result.set_error(message)

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
        from core.logger.console import render_panel_to_str

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
        from rich import box
        from rich.panel import Panel

        lines: List[str] = []

        if connection_info:
            lines.append(connection_info)

        if database_name:
            lines.append(f"Database: {database_name}")
        elif hasattr(self, "config") and hasattr(self.config, "database"):
            db_name = getattr(self.config.database, "database_name", None) or getattr(
                self.config.database, "database", None
            )
            if db_name:
                lines.append(f"Database: {db_name}")

        if schema_name:
            lines.append(f"Schema: {schema_name}")
        elif hasattr(self, "config") and hasattr(self.config, "database"):
            schema = getattr(self.config.database, "schema", None)
            if schema:
                lines.append(f"Schema: {schema}")

        lines.append(f"Schema Version: {schema_version or '<none>'}")
        lines.append(f"Database URL: {database_url or '<not available>'}")

        if filters:
            lines.append(f"Filtering Options: {' '.join(filters)}")

        return Panel(
            _props_text(*lines),
            title=f"DBLIFT COMMAND: {command_name.upper()}",
            box=box.HEAVY,
            expand=True,
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

    def _resolve_current_schema_version(self) -> Optional[str]:
        """Resolve the current schema version from applied migration history.

        Filters out undone (but not reapplied) migrations before determining
        the current version.

        Returns:
            Current schema version string, or ``None`` if not determinable.
        """
        try:
            applied_migrations = self.history_manager.get_applied_migrations()
            if not applied_migrations:
                self.log.debug("No applied migrations found, schema version will be <none>")
                return None

            from core.migration.state.migration_data_service import MigrationDataService

            data_service = MigrationDataService(self.log, scripts_dir=None)
            analysis_context = data_service._build_analysis_context(applied_migrations)
            history = self.state_manager._analyse_history(applied_migrations, analysis_context)

            undone_but_not_reapplied = history.undone_versions - history.reapplied_versions
            applied_migrations_filtered = [
                m
                for m in applied_migrations
                if (
                    # Keep non-versioned migrations (repeatable, callback, etc.)
                    self.state_manager._get_type_name(m) not in VERSIONED_SCRIPT_TYPES
                    # Keep versioned migrations that haven't been undone
                    or str(getattr(m, "version", "")) not in undone_but_not_reapplied
                )
            ]
            current_version = self.state_manager.get_current_version(applied_migrations_filtered)
            schema_version = current_version if current_version else None

            try:
                applied_count = (
                    len(applied_migrations) if hasattr(applied_migrations, "__len__") else "unknown"
                )
                filtered_count = (
                    len(applied_migrations_filtered)
                    if hasattr(applied_migrations_filtered, "__len__")
                    else "unknown"
                )
                self.log.debug(
                    f"Retrieved schema version: {schema_version} from {applied_count} applied migrations (filtered: {filtered_count})"
                )
            except (TypeError, AttributeError):
                pass

            return schema_version
        except Exception as e:
            self.log.debug(f"Could not retrieve schema version: {e}")
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
        from core.logger.log import ConsoleLog, MultiLog

        if isinstance(self.log, MultiLog):
            return any(isinstance(log, ConsoleLog) for log in self.log.logs)
        return isinstance(self.log, ConsoleLog)

    def _print_main_header_once(self) -> None:
        """Print the application-level text header to the console exactly once.

        Uses a module-level flag so that the header is not repeated when
        multiple commands run in the same process.
        """
        from core.logger.log import TextFormatter

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
        filters = self._build_filters_list(
            dry_run=dry_run,
            target_version=target_version,
            tags=tags,
            exclude_tags=exclude_tags,
            versions=versions,
            exclude_versions=exclude_versions,
            **kwargs,
        )
        schema_version = self._resolve_current_schema_version()
        database_url = self._resolve_database_url_masked()
        connection_info = self._resolve_connection_info()

        should_print_header = self._is_console_output()
        if should_print_header:
            self._print_main_header_once()

        if should_print_header:
            from core.logger.console import get_stdout_console

            get_stdout_console().print(
                self._build_command_header_panel(
                    command_name=command_name,
                    filters=filters,
                    schema_version=schema_version,
                    database_url=database_url,
                    connection_info=connection_info,
                )
            )
        self._log_text_block(
            self._format_command_header(
                command_name=command_name,
                filters=filters,
                schema_version=schema_version,
                database_url=database_url,
                connection_info=connection_info,
            )
        )
