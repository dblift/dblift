"""Optional command presentation shared by console adapters and legacy sinks."""

from __future__ import annotations

import sys
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any, Dict, Iterator, List, Optional

from dblift.core.logger import Log, NullLog
from dblift.core.logger.console import get_stdout_console, rich_available
from dblift.core.logger.log import ConsoleLog, FileLog, LogFormat, MultiLog
from dblift.core.logger.results import OperationResult
from dblift.core.migration.executor import execution_engine
from dblift.core.migration.ui.migration_ui import MigrationUI
from dblift.core.migration.ui.progress import ProgressSink, migration_progress

if TYPE_CHECKING:
    from dblift.core.migration.commands.base_command import BaseCommand
    from dblift.core.migration.executor.execution_engine import ExecutionEngine
    from dblift.core.migration.state.migration_state import MigrationReadSnapshot


def _render_command_header_update(
    context: "BaseCommand",
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
    """Update command header with schema version and connection info after
    connection is established.

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
    filters = context._build_filters_list(
        dry_run=dry_run,
        target_version=target_version,
        tags=tags,
        exclude_tags=exclude_tags,
        versions=versions,
        exclude_versions=exclude_versions,
        **kwargs,
    )
    schema_version = (
        context._resolve_current_schema_version(read_snapshot=read_snapshot)
        if read_snapshot is not None
        else context._resolve_current_schema_version()
    )
    database_url = context._resolve_database_url_masked()
    connection_info = context._resolve_connection_info()

    if isinstance(context.log, NullLog):
        return

    should_print_header = context._is_console_output()
    if should_print_header:
        context._print_main_header_once()

    if should_print_header:
        if rich_available():
            get_stdout_console().print(
                context._build_command_header_panel(
                    command_name=command_name,
                    filters=filters,
                    schema_version=schema_version,
                    database_url=database_url,
                    connection_info=connection_info,
                )
            )
        else:
            sys.stdout.write(
                context._format_command_header(
                    command_name=command_name,
                    filters=filters,
                    schema_version=schema_version,
                    database_url=database_url,
                    connection_info=connection_info,
                )
                + "\n"
            )
    context._log_text_block(
        context._format_command_header(
            command_name=command_name,
            filters=filters,
            schema_version=schema_version,
            database_url=database_url,
            connection_info=connection_info,
        )
    )


def _render_command_completion(
    context: "BaseCommand", command_name: str, result: OperationResult
) -> None:
    """Log command completion with status and execution time using uniform format.

    Args:
        command_name: Name of the command that completed
        result: OperationResult with execution time and success status
    """
    # Mark as complete if not already done to get execution time
    if result.end_time is None:
        result.complete()

    if isinstance(context.log, NullLog):
        return

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
    # Check if we should print to console
    should_print_footer = False
    has_console_log = False
    has_file_log = False
    if isinstance(context.log, MultiLog):
        # MultiLog - check if any is console or file
        for log in context.log.logs:
            if isinstance(log, ConsoleLog):
                should_print_footer = True
                has_console_log = True
            elif isinstance(log, FileLog):
                has_file_log = True
    elif isinstance(context.log, ConsoleLog):
        # Console log - print footer
        should_print_footer = True
        has_console_log = True
    elif isinstance(context.log, FileLog):
        # File log only
        has_file_log = True

    # Don't log completion message to console - the footer already shows it
    # But still log to file logs (HTML/JSON) for record keeping
    status = "SUCCESS" if result.success else "FAILED"
    if has_file_log and isinstance(context.log, MultiLog):
        # MultiLog with file log - log only to file logs, not console
        for log in context.log.logs:
            if isinstance(log, FileLog) and not isinstance(log, ConsoleLog):
                if getattr(log, "log_format", None) == LogFormat.TEXT:
                    continue
                log.info(f"Command {command_name} completed with status {status} in {time_str}")
    elif has_file_log and not has_console_log:
        # File log only, no console - log the message
        if getattr(context.log, "log_format", None) != LogFormat.TEXT:
            context.log.info(f"Command {command_name} completed with status {status} in {time_str}")

    # Resolve the schema version *after* the operation has run
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
    if hasattr(context, "history_manager") and context.history_manager is not None:
        try:
            post_op_schema_version = context._resolve_current_schema_version()
        except Exception as e:
            try:
                context.log.debug(f"Could not resolve post-operation schema version: {e}")
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
                    applied_scripts = [f"Dry run — {dry_run_count} migration(s) would be applied"]
                else:
                    applied_scripts = ["No pending migrations found"]

    # Print footer to console if applicable
    footer_args: Dict[str, Any] = dict(
        command_name=command_name,
        success=result.success,
        execution_time=time_str,
        error_message=getattr(result, "error_message", None),
        schema_version=post_op_schema_version,
        applied_scripts=applied_scripts,
    )
    if should_print_footer and not context._has_own_console_footer:
        if rich_available():
            get_stdout_console().print(context._build_footer_panel(**footer_args))
        else:
            sys.stdout.write(context._format_command_footer(**footer_args) + "\n")
    context._log_text_block(context._format_command_footer(**footer_args))


class CommandPresentation:
    """Render through the existing command helpers, preserving subclass dispatch."""

    def present_command_start(
        self, context: "BaseCommand", command: str, **parameters: Any
    ) -> None:
        """Present the header after command preflight."""
        _render_command_header_update(context, command, **parameters)

    def present_command_result(
        self, context: "BaseCommand", command: str, result: OperationResult
    ) -> None:
        """Present the completed command with its post-operation schema version."""
        _render_command_completion(context, command, result)

    def present_query_result(
        self, engine: "ExecutionEngine", columns: List[str], rows: List[List[Any]]
    ) -> None:
        """Render one captured result set through the historical renderer export."""
        renderer = getattr(execution_engine, "render_records_table")
        engine.log.info(
            renderer(
                [(column, "left") for column in columns],
                rows,
                title=f"Query result ({len(rows)} rows)",
            )
        )

    def present_migration_info(self, context: "BaseCommand", **parameters: Any) -> None:
        """Construct the optional UI only when human output was requested."""
        ui = context.migration_ui
        if ui is None:
            ui = MigrationUI(context.log)
            ui.script_manager = context.script_manager
        ui.display_migration_info(**parameters)

    @contextmanager
    def migration_loop(self, log: Log, total: int) -> Iterator[ProgressSink]:
        """Select presentation while the loop uses the neutral progress sink.

        Direct updates preserve progress with batched events and nested operations.
        """
        with migration_progress(log, total) as progress:
            yield progress
