"""DBLift logging primitives — Log base, AbstractLog with dedup,
ConsoleLog, FileLog.

This module also re-exports the smaller pieces (LogFormat, LogLevel,
LogEvent, LogFormatter, TextFormatter, MultiLog, NullLog, LogFactory)
so existing imports of the form

    from core.logger.log import LogLevel, FileLog, LogFactory, ...

keep working after the PR-B5 split. The implementations now live in
``_levels.py``, ``_formatters.py``, ``_multi.py``, ``_null.py``,
``_factory.py``. Test patches that target ``core.logger.log.X`` for
``X in {traceback, JINJA_AVAILABLE, TextFormatter, ...}`` keep
resolving here.
"""

import inspect  # noqa: F401  back-compat: imported by callers via core.logger.log.inspect
import logging
import re
import sys
import traceback

_logger = logging.getLogger(__name__)
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional, Union

# Re-exports from the split submodules. Importing here ensures every
# legacy ``from core.logger.log import X`` keeps working and lets test
# patches that target ``core.logger.log.X`` resolve to the same object.
from core.logger._base import Log
from core.logger._factory import LogFactory  # noqa: F401  re-export
from core.logger._formatters import LogFormatter, TextFormatter  # noqa: F401  re-export
from core.logger._levels import (  # noqa: F401  re-export
    _LOG_LEVEL_PRIORITIES,
    LogEvent,
    LogFormat,
    LogLevel,
    _initialize_log_level_priorities,
)
from core.logger._multi import MultiLog  # noqa: F401  re-export
from core.logger._null import NullLog  # noqa: F401  re-export

JINJA_AVAILABLE = True

try:
    from .formatters.jsonformatter import JsonFormatter

    JSON_AVAILABLE = True
except ImportError:
    JSON_AVAILABLE = False


# Abstract base implementation with common functionality
class AbstractLog(Log):
    """Abstract base class with shared logging functionality."""

    def __init__(
        self,
        name: str,
        enable_debug: bool = False,
        log_level: Optional[LogLevel] = None,
    ):
        """Initialize logger identity, level threshold, and the per-sink dedup state."""
        self.name = name
        self.enable_debug = enable_debug
        # log_level governs the minimum severity written. DEBUG when enable_debug.
        if log_level is None:
            log_level = LogLevel.DEBUG if enable_debug else LogLevel.INFO
        self.log_level = log_level
        # For message deduplication
        self._dedup_window = 2  # seconds
        self._recent_messages: Dict[str, datetime] = {}
        self._prev_message = ""  # Track previous message for duplicate detection
        self.command_type: Optional[str] = None  # Track current command type

    def is_debug_enabled(self) -> bool:
        """Return ``True`` if this logger was constructed with ``enable_debug=True``."""
        return self.enable_debug

    def _passes_level_filter(self, level: LogLevel) -> bool:
        return LogLevel.priority(level) >= LogLevel.priority(self.log_level)

    def _should_deduplicate(self, level: LogLevel, message: str) -> bool:
        """Check if a message should be deduplicated."""
        # Always log errors
        if level == LogLevel.ERROR:
            return False

        # Never deduplicate empty strings
        if message == "":
            return False

        # Create a unique key for this message
        message_key = f"{level.value}:{message}"

        # Check if we've seen this message recently
        now = datetime.now()
        if message_key in self._recent_messages:
            last_time = self._recent_messages[message_key]
            elapsed = (now - last_time).total_seconds()
            if elapsed < self._dedup_window:
                return True

        # Update the message timestamp
        self._recent_messages[message_key] = now

        # Limit size of recent messages dictionary
        if len(self._recent_messages) > 100:
            # Remove oldest entries
            oldest_keys = sorted(self._recent_messages.items(), key=lambda x: x[1])[:50]
            for key, _ in oldest_keys:
                del self._recent_messages[key]

        return False

    def _log(
        self,
        level: LogLevel,
        message: str,
        console_only: bool = False,
        *,
        dedupe: bool = True,
    ) -> None:
        """Common logging method that handles deduplication."""
        if not self._passes_level_filter(level):
            return

        # Avoid showing tables twice in console output
        if message.strip().startswith("+") and message.strip() == self._prev_message.strip():
            # Don't print to console or log if it's a duplicate table
            return

        # Store this message for deduplication
        self._prev_message = message

        if dedupe and self._should_deduplicate(level, message):
            return

        # Create a log event
        event = LogEvent(level, message, self.name)
        self._write_log_event(event, console_only)

    def _write_log_event(self, event: LogEvent, console_only: bool = False) -> None:
        """Write a log event - to be implemented by subclasses."""

    def debug(self, message: str) -> None:
        """Emit ``message`` at DEBUG level via the shared ``_log`` pipeline."""
        self._log(LogLevel.DEBUG, message)

    def info(self, message: str, console_only: bool = False, *, dedupe: bool = True) -> None:
        """Emit ``message`` at INFO level, honouring console-only and dedup flags."""
        self._log(LogLevel.INFO, message, console_only, dedupe=dedupe)

    def warn(self, message: str) -> None:
        """Emit ``message`` at WARN level via the shared ``_log`` pipeline."""
        self._log(LogLevel.WARN, message)

    def error(self, message: str) -> None:
        """Emit ``message`` at ERROR level via the shared ``_log`` pipeline."""
        self._log(LogLevel.ERROR, message)

    def error_with_exception(self, message: str, e: Exception) -> None:
        """Emit an error annotated with a sanitized exception summary."""
        # Clean up fully qualified exception class names for better user experience.
        error_msg = str(e)

        # B8-BUG-04: strip fully-qualified exception class prefixes
        # (e.g. ``org.postgresql.util.PSQLException: FATAL: ...`` →
        # ``FATAL: ...``).
        error_msg = re.sub(
            r"(?:\b\w+\.){1,}\w+(?:Exception|Error)\b\s*:\s*",
            "",
            error_msg,
        )
        # Also strip bare FQCNs (no message after the class name).
        error_msg = re.sub(r"(?:\b\w+\.){2,}\w+(?:Exception|Error)\b", "", error_msg)

        # Remove the first part of nested exceptions
        if "The above exception was the direct cause of the following exception" in error_msg:
            error_msg = error_msg.split(
                "The above exception was the direct cause of the following exception"
            )[1]

        # Extract just the key error message
        error_details = f"{message}\n       Exception: {error_msg.strip()}"

        # Only include stack trace in log files, not console output
        if "Validation failed" not in message:
            stack_trace = traceback.format_exc()
            self._stack_trace = stack_trace  # Store for file loggers to use

        self._log(LogLevel.ERROR, error_details)

    def notice(self, message: str) -> None:
        """Emit ``message`` at NOTICE level (success / highlight events)."""
        self._log(LogLevel.NOTICE, message)

    def set_command_type(self, command_type: str) -> None:
        """Set the current command type."""
        self.command_type = command_type

        # If we have a formatter with set_current_command, update it too
        if hasattr(self, "formatter") and hasattr(self.formatter, "set_current_command"):
            self.formatter.set_current_command(command_type)

    def set_current_command(self, command_type: str) -> None:
        """Set the current command being executed in a multi-command scenario."""
        self.command_type = command_type
        if hasattr(self, "formatter") and hasattr(self.formatter, "set_current_command"):
            self.formatter.set_current_command(command_type)

    def close(self) -> None:
        """Close the logger and perform cleanup."""


# ConsoleLog implementation
class ConsoleLog(AbstractLog):
    """Simple console-based logger implementation."""

    _LEVEL_STYLES = {
        LogLevel.DEBUG: "log.debug",
        LogLevel.INFO: None,
        LogLevel.WARN: "log.warn",
        LogLevel.ERROR: "log.error",
        LogLevel.NOTICE: "log.notice",
    }

    def __init__(
        self,
        name: str,
        enable_debug: bool = False,
        log_level: Optional[LogLevel] = None,
    ):
        """Initialize a stderr Rich-Console logger with a plain TextFormatter."""
        super().__init__(name, enable_debug, log_level)
        self.formatter = TextFormatter()
        from .console import get_stderr_console

        self._console = get_stderr_console()

    def _write_log_event(self, event: LogEvent, console_only: bool = False) -> None:
        """Write a log event to the console.

        Severity styling is applied here on the Rich Console (stderr) only.
        The TextFormatter output stays plain so file / JSON / HTML sinks
        receive raw text. ADR-0008: stdout is reserved for command payloads.
        """
        formatted_msg = self.formatter.format_event(event)
        style = self._LEVEL_STYLES.get(event.level)
        self._console.print(formatted_msg, style=style, markup=False, highlight=False)

    def console_print(
        self,
        renderable: Any,
        level: LogLevel = LogLevel.INFO,
        **kwargs: Any,
    ) -> None:
        """Render a Rich renderable directly to the stderr Console.

        Honours the same level threshold as ``log.info`` / ``log.debug``
        so ``--quiet`` (or any explicit ``--log-level=warn``) suppresses
        info-tier renderables alongside their textual headers — keeps
        the contextual log line and the styled body in sync.
        """
        if not self._passes_level_filter(level):
            return
        kwargs.setdefault("markup", False)
        kwargs.setdefault("highlight", False)
        self._console.print(renderable, **kwargs)

    def set_command_completed(
        self,
        success: bool,
        message: Optional[str] = None,
        command_type: Optional[str] = None,
        result: Optional[Any] = None,
    ) -> None:
        """Set command completed status in the log."""
        # Get the command type from class attribute if not provided
        if command_type is None:
            command_type = (
                getattr(self, "command_type", "COMMAND")
                if hasattr(self, "command_type")
                else "COMMAND"
            )

        # Ensure command_type is a string
        if not isinstance(command_type, str):
            command_type = "COMMAND"

        # Normalize and store the command type for downstream formatters
        normalized_command_type = command_type.upper()
        self.set_command_type(normalized_command_type)
        command_type = normalized_command_type

        # Don't log completion messages here - they're already logged by _log_command_completion
        # in migration_operations.py. This method is only for storing the result for HTML/JSON reports.
        # If message is provided, it's already been logged, so we skip logging here.
        # Only log if no message is provided (for backward compatibility with other callers)
        if not message:
            # Fallback: generate message without execution time if not provided
            command_label = command_type.lower() if isinstance(command_type, str) else "command"
            if success:
                self.info(f"Command {command_label} completed successfully")
            else:
                self.info(f"Command {command_label} failed")

        # Store the result if provided
        if result is not None:
            self.operation_result = result

            # Display detailed result with journal summary for console output
            self._display_result_summary(result)

    def _display_result_summary(self, result) -> None:
        """Display detailed result summary with journal data if available."""
        has_visible_sql = getattr(result, "show_sql", False) and getattr(result, "sql", None)
        # Only show detailed summaries for successful operations unless
        # --show-sql explicitly collected SQL before the failure.
        if not getattr(result, "success", True) and not has_visible_sql:
            return

        try:
            # Import here to avoid circular imports
            from .formatters.formatter import OutputFormatter

            has_journal = (
                getattr(result, "success", True) and hasattr(result, "journal") and result.journal
            )
            if has_journal or has_visible_sql:
                formatter = OutputFormatter()

                # Get schema name from result if available
                schema_name = getattr(result, "target_schema", None) or "default"

                # Format the result as text and display it
                formatted_result = formatter.format(
                    result, format_type="text", schema_name=schema_name
                )

                # Only display the performance and explicit SQL visibility
                # sections, not the full report.
                lines = formatted_result.split("\n")
                in_performance_section = False
                in_sql_section = False
                performance_lines: list[str] = []

                for line in lines:
                    if has_visible_sql and line.strip() == "SQL Statements:":
                        in_sql_section = True
                        if performance_lines and performance_lines[-1].strip():
                            performance_lines.append("")
                        performance_lines.append(line)
                        continue

                    if in_sql_section:
                        performance_lines.append(line)
                        continue

                    if not has_journal:
                        continue

                    # Start capturing when we hit performance sections
                    if "Performance Summary:" in line or "Performance by Object Type:" in line:
                        in_performance_section = True
                        performance_lines.append("")  # Add spacing
                        performance_lines.append(line)
                    elif in_performance_section:
                        # Stop capturing when we hit warnings or a section after performance
                        if line.strip().startswith("Warnings:") or line.strip().startswith(
                            "Error Details:"
                        ):
                            break
                        # Continue capturing unless we hit two consecutive empty lines
                        performance_lines.append(line)

                        # If we have enough content and hit an empty line followed by non-performance content, stop
                        if (
                            len(performance_lines) > 10
                            and line.strip() == ""
                            and len([ln for ln in performance_lines if ln.strip()]) > 5
                        ):
                            # Look ahead to see if next non-empty line is not performance related
                            break

                # Display the performance summary if we found any. This is
                # human-facing console output, so keep stdout reserved for
                # command payloads.
                if performance_lines:
                    for line in performance_lines:
                        self._console.print(line, markup=False, highlight=False)

        except Exception as e:
            # Don't let journal display errors break the console output
            # Just log debug message if debug is enabled
            if self.is_debug_enabled():
                self.debug(f"Could not display result summary: {e}")


def _safe_name(value: str) -> str:
    """Collapse anything that isn't a safe filename char to ``_``.

    Used for the schema/database-name components of a log filename so a
    path-like identifier (e.g. a SQLite file path) cannot inject directory
    separators and point the log at a nonexistent nested directory.
    """
    return re.sub(r"[^\w.-]+", "_", value)


# File log implementation
class FileLog(AbstractLog):
    """File-based log implementation."""

    def __init__(
        self,
        name: str,
        log_dir: Path,
        log_format: Union[LogFormat, str] = LogFormat.TEXT,
        schema: str = None,
        database_name: str = None,
        log_file_pattern: str = None,
        enable_debug: bool = False,
        max_bytes: int = None,
        backup_count: int = None,
        log_level: Optional[LogLevel] = None,
    ):
        """Initialize a new file log.

        Args:
            name: The name of the logger
            log_dir: Directory where log files will be stored
            log_format: Format for log files (TEXT, JSON, HTML)
            schema: Optional schema name for log file naming
            database_name: Optional database name for log file naming
            log_file_pattern: Optional custom log file naming pattern
            enable_debug: Whether debug messages should be displayed
            max_bytes: Maximum size of each log file before rotation
            backup_count: Number of backup files to keep
        """
        super().__init__(name, enable_debug, log_level)
        self.log_dir = Path(log_dir)
        self.log_format = LogFormat(log_format) if isinstance(log_format, str) else log_format
        self.schema = schema
        self.database_name = database_name
        self.log_file_pattern = log_file_pattern
        self.max_bytes = max_bytes
        self.backup_count = backup_count
        self.current_size = 0

        # Create log directory if it doesn't exist
        self._ensure_log_dir()

        # Get initial log file path
        self.log_file = self._get_log_file()
        # Defense-in-depth: a custom pattern may legitimately nest directories;
        # ensure the file's parent exists so the header write never crashes.
        self.log_file.parent.mkdir(parents=True, exist_ok=True)

        # Create formatter based on format
        from typing import Union

        from core.logger.formatters.htmlformatter import HtmlFormatter
        from core.logger.formatters.jsonformatter import JsonFormatter

        self.formatter: Union[TextFormatter, "HtmlFormatter", "JsonFormatter"]
        if self.log_format == LogFormat.JSON and JSON_AVAILABLE:
            self.formatter = JsonFormatter()
        elif self.log_format == LogFormat.HTML and JINJA_AVAILABLE:
            self.formatter = HtmlFormatter()
        else:
            self.formatter = TextFormatter()

        # Write header if this is a new file (skip for JSON format - will write complete JSON on close)
        if self.log_format != LogFormat.JSON:
            if not self.log_file.exists() or self.log_file.stat().st_size == 0:
                self._write_header()

        self._prev_message = ""  # Track previous message for context

    def _ensure_log_dir(self) -> None:
        """Ensure the log directory exists."""
        self.log_dir.mkdir(parents=True, exist_ok=True)

    def _get_log_file(self) -> Path:
        """Get the log file path using the specified naming pattern."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        # Get the appropriate file extension based on the log format enum
        extension = self._get_extension_for_format()

        if self.log_file_pattern:
            # Replace placeholders in the custom pattern
            log_file_name = self.log_file_pattern
            log_file_name = log_file_name.replace("<schema>", _safe_name(str(self.schema or "")))
            log_file_name = log_file_name.replace(
                "<database_name>", _safe_name(str(self.database_name or ""))
            )
            log_file_name = log_file_name.replace("<timestamp>", timestamp)

            # Check if we need to replace <format> placeholder
            if "<format>" in log_file_name:
                log_file_name = log_file_name.replace("<format>", extension)
            # If no extension in the pattern and no format placeholder, add the extension
            elif "." not in log_file_name.split("/")[-1]:
                log_file_name += f".{extension}"
        else:
            # Use default naming convention
            log_file_name = (
                f"Dblift_{_safe_name(str(self.schema))}_"
                f"{_safe_name(str(self.database_name))}_{timestamp}.{extension}"
            )

        return self.log_dir / log_file_name

    def _get_extension_for_format(self) -> str:
        """Get the appropriate file extension for the current log format."""
        if hasattr(self, "log_format_enum"):
            if self.log_format_enum == LogFormat.HTML:
                return "html"
            elif self.log_format_enum == LogFormat.JSON:
                return "json"
            else:  # LogFormat.TEXT
                return "log"
        else:
            # Fallback to string-based format
            format_str = self.log_format.value.lower()
            if format_str == "html":
                return "html"
            elif format_str == "json":
                return "json"
            else:
                return "log"

    def _write_header(self) -> None:
        """Write a header to the log file."""
        # Ensure the log directory exists before writing
        self._ensure_log_dir()

        header = self.formatter.format_header(self.schema, self.database_name)
        if header:
            with open(self.log_file, "a", encoding="utf-8") as f:
                f.write(header + "\n")

    def file_only_info(self, message: str) -> None:
        """Emit an info message to this file sink (no console fan-out)."""
        self.info(message)

    def _write_log_event(self, event: LogEvent, console_only: bool = False) -> None:
        """Write a log event to the file.

        Args:
            event: The log event to write
            console_only: Whether to only write to console
        """
        if console_only:
            return

        # Filter events below the configured log level
        if not self._passes_level_filter(event.level):
            return

        # For JSON format, we don't write individual events to the file
        # Instead, we collect them and write a complete JSON object on close
        if self.log_format == LogFormat.JSON:
            # Just format the event to collect it in the formatter
            formatted_event = self.formatter.format_event(event)
            if not formatted_event:
                return
            # Don't write to file yet - will be written as complete JSON on close
            return

        # For other formats (TEXT, HTML), write events as they come
        formatted_event = self.formatter.format_event(event)
        if not formatted_event:
            return

        try:
            # Ensure the log directory exists before writing
            self._ensure_log_dir()

            # Check if we need to rotate
            if self.max_bytes and self.backup_count:
                current_size = self.log_file.stat().st_size
                if current_size + len(formatted_event) > self.max_bytes:
                    self._rotate_log()

            # Write the event
            with open(self.log_file, "a", encoding="utf-8") as f:
                f.write(formatted_event + "\n")

        except Exception as e:
            print(
                f"[dblift] Warning: could not write to log file {self.log_file}: {e}",
                file=sys.stderr,
            )

    def _write_text_block(self, block: str) -> None:
        """Write a text block directly to the log file (for headers/footers).

        This bypasses the formatter to write raw text blocks like command headers
        and footers that should match console output exactly.

        Args:
            block: The text block to write
        """
        if not block:
            return

        try:
            # Ensure the log directory exists before writing
            self._ensure_log_dir()

            # Write the block directly to the file
            with open(self.log_file, "a", encoding="utf-8") as f:
                f.write(block + "\n")
        except Exception as e:
            print(
                f"[dblift] Warning: could not write to log file {self.log_file}: {e}",
                file=sys.stderr,
            )

    def _rotate_log(self) -> None:
        """Rotate log files if size limit is reached."""
        if not (self.max_bytes and self.backup_count):
            return

        # Close current file if open
        self.close()

        # Rotate existing backup files
        for i in range(self.backup_count - 1, 0, -1):
            old_file = self.log_file.with_suffix(f".log.{i}")
            new_file = self.log_file.with_suffix(f".log.{i + 1}")
            if old_file.exists():
                old_file.rename(new_file)

        # Rename current log file
        if self.log_file.exists():
            self.log_file.rename(self.log_file.with_suffix(".log.1"))

        # Create new log file
        self.log_file = self._get_log_file()
        self._write_header()

    def close(self) -> None:
        """Close the log file properly."""
        # For JSON format, skip footer (complete JSON is written below)
        if self.log_format != LogFormat.JSON:
            # Write footer for non-JSON formats
            with open(self.log_file, "a", encoding="utf-8") as f:
                footer = self.formatter.format_footer()
                if footer:
                    f.write(footer)

        # For JSON logs, write the complete log with all entries
        if self.log_format == LogFormat.JSON and isinstance(self.formatter, JsonFormatter):
            # Ensure we have a result - create a minimal one if not available
            if hasattr(self, "operation_result") and self.operation_result is not None:
                result = self.operation_result
            else:
                # Create a minimal result if none was provided
                from core.logger.results import OperationResult

                result = OperationResult(success=True)
                result.complete()

            # Write complete JSON document with all log entries and result.
            # format_result writes to file directly; the return value is unused.
            self.formatter.format_result(
                result,
                self.schema or "default",
                self.database_name or "default",
                self.command_type or "operation",
                self.log_file,
            )

        # For HTML logs, render the complete template with Jinja
        elif self.log_format == LogFormat.HTML and JINJA_AVAILABLE:
            from .results import OperationResult

            # Get the operation result from attached object if available
            result = None
            if hasattr(self, "operation_result") and self.operation_result:
                result = self.operation_result
            else:
                # Create a dummy result
                result = OperationResult()
                result.complete()

            # Set command type if not already set
            if hasattr(self.formatter, "command_type"):
                if not getattr(self.formatter, "command_type", None):
                    self.formatter.command_type = self.command_type or "INFO"

            # Make sure to use format_result from the HtmlFormatter
            if hasattr(self.formatter, "format_result"):
                # Render the complete HTML report using the Jinja template
                html = self.formatter.format_result(
                    result,
                    self.schema or "default",
                    self.database_name or "default",
                    self.command_type or "INFO",
                    self.log_file,
                )

                # Write the complete HTML to the log file
                with open(self.log_file, "w", encoding="utf-8") as f:
                    f.write(html)

    def is_html_enabled(self) -> bool:
        """Check if HTML logging is enabled.

        Returns:
            True if HTML logging is enabled, False otherwise
        """
        return self.log_format == LogFormat.HTML

    def html(self, html_content: str) -> None:
        """Log HTML content directly.

        Args:
            html_content: The HTML content to log
        """
        if self.is_html_enabled():
            # When using HTML format, write the content directly to the log file
            try:
                with open(self.log_file, "a", encoding="utf-8") as f:
                    f.write(html_content + "\n")
            except Exception as e:
                print(f"Error writing HTML to log file: {str(e)}")
        else:
            # For non-HTML formats, just log as info
            self.info(html_content)

    def set_command_completed(
        self,
        success: bool,
        message: Optional[str] = None,
        command_type: Optional[str] = None,
        result: Optional[Any] = None,
    ) -> None:
        """Set command completed status in the log."""
        # Get the command type from class attribute if not provided
        if command_type is None:
            command_type = (
                getattr(self, "command_type", "COMMAND")
                if hasattr(self, "command_type")
                else "COMMAND"
            )

        # Ensure command_type is a string
        if not isinstance(command_type, str):
            command_type = "COMMAND"

        normalized_command_type = command_type.upper()
        self.set_command_type(normalized_command_type)
        command_type = normalized_command_type

        # Don't log completion messages to TEXT file logs - the footer is already logged by _log_command_completion
        # via _log_text_block. This method is only for storing the result for HTML/JSON reports.
        # For TEXT format, skip logging the message to avoid duplicate footers
        if self.log_format == LogFormat.TEXT:
            # For TEXT format, don't log completion messages - footer is handled by _log_command_completion
            # via _log_text_block which writes the footer directly
            pass
        elif message:
            # For HTML/JSON formats, log the message if provided
            self.info(message)
        else:
            # Fallback: generate message without execution time if not provided (only for non-TEXT formats)
            command_label = command_type.lower() if isinstance(command_type, str) else "command"
            if success:
                self.info(f"Command {command_label} completed successfully")
            else:
                self.info(f"Command {command_label} failed")

        # Store the result if provided
        if result is not None:
            self.operation_result = result

            # If we have a formatter and are in multi-command mode, add this command result
            if (
                hasattr(self, "formatter")
                and hasattr(self.formatter, "using_multi_command")
                and self.formatter.using_multi_command
                and hasattr(self.formatter, "add_command_result")
            ):
                # Type ignore because we've checked that add_command_result exists
                self.formatter.add_command_result(command_type, result)  # type: ignore

    def set_multi_command_mode(self, enabled: bool = True):
        """Enable or disable multi-command mode for logging."""
        if hasattr(self, "formatter"):
            if hasattr(self.formatter, "using_multi_command"):
                self.formatter.using_multi_command = enabled

    def set_current_command(self, command_type: str) -> None:
        """Update the active-command name and propagate to the formatter."""
        super().set_current_command(command_type)
