"""Log base class — defines the shared protocol for every logger sink.

Extracted from ``core/logger/log.py`` in PR-B5 so that ``MultiLog`` and
``NullLog`` can keep inheriting from ``Log`` without creating an import
cycle with the concrete ``ConsoleLog`` / ``FileLog`` / ``AbstractLog``
classes that still live in ``log.py``.

Public API re-exported from ``dblift.core.logger.log`` for back-compat.
"""

import traceback
from typing import Any, List, Optional

from dblift.core.logger._levels import LogLevel


class Log:
    """Base implementation for all logging providers."""

    def __init__(self, name: str, enable_debug: bool = False):
        """Initialize a new log instance.

        Args:
            name: The name of the logger (usually component/class name)
            enable_debug: Whether debug messages should be displayed
        """
        self.name = name
        self._enable_debug = enable_debug
        self._dedup_window = 5  # Number of messages to track for deduplication
        self._last_messages: List[str] = []  # Track recent messages for deduplication
        self.logs: List[Any] = []  # Track log entries for formatters

    def debug(self, message: str) -> None:
        """Log a debug message if debug logging is enabled."""
        if self._enable_debug:
            self._log(LogLevel.DEBUG, message)

    def info(self, message: str, console_only: bool = False, *, dedupe: bool = True) -> None:
        """Log an info message."""
        self._log(LogLevel.INFO, message, dedupe=dedupe)

    def warn(self, message: str) -> None:
        """Log a warning message."""
        self._log(LogLevel.WARN, message)

    def warning(self, message: str) -> None:
        """Log a warning message (alias for warn)."""
        self.warn(message)

    def error(self, message: str) -> None:
        """Log an error message."""
        # Track stack trace for error reporting
        self._stack_trace = traceback.format_exc()
        # Errors are never deduplicated, so use _log_direct
        self._log_direct(LogLevel.ERROR, message)

    def error_with_exception(self, message: str, e: Exception) -> None:
        """Log an error message with exception details."""
        error_msg = f"{message}: {str(e)}"
        self.error(error_msg)

    def notice(self, message: str) -> None:
        """Log a notice/success message."""
        self._log(LogLevel.NOTICE, message)

    def set_command_type(self, command_type: str) -> None:
        """Set the current command type for logging."""
        # Base implementation - can be overridden by subclasses

    def set_command_completed(
        self,
        success: bool,
        message: Optional[str] = None,
        command_type: Optional[str] = None,
        result: Optional[Any] = None,
    ) -> None:
        """Mark a command as completed."""
        if success:
            self.notice(message or "Command completed successfully")
        else:
            self.error(message or "Command failed")

    def is_debug_enabled(self) -> bool:
        """Check if debug logging is enabled."""
        return self._enable_debug

    def is_html_enabled(self) -> bool:
        """Check if HTML logging is enabled. Default False; overridden by HTML-aware sinks."""
        return False

    def html(self, html_content: str) -> None:
        """Log HTML content directly. Default falls back to info()."""
        self.info(html_content)

    def _log(self, level: LogLevel, message: str, *, dedupe: bool = True) -> None:
        """Log a message with deduplication."""
        # Skip deduplication for ERROR level messages or if deduplication is disabled
        if level == LogLevel.ERROR or self._dedup_window <= 0 or not dedupe:
            self._log_direct(level, message)
            return

        # Create message key for deduplication tracking (level + message)
        message_key = f"{level.value}:{message}"

        # Check if this message was recently logged
        if message_key in self._last_messages:
            return  # Skip duplicate message

        # Add to recent messages for deduplication
        self._last_messages.append(message_key)

        # Keep deduplication window limited to the specified size
        if len(self._last_messages) > self._dedup_window:
            self._last_messages.pop(0)  # Remove oldest message

        # Log the message
        self._log_direct(level, message)

    def _log_direct(self, level: LogLevel, message: str) -> None:
        """Log a message directly without deduplication."""
        # Skip if trying to log DEBUG and debug is not enabled
        if level == LogLevel.DEBUG and not self._enable_debug:
            return

        # Call the implementation-specific logging
        self._write_log(level, message)

    def _write_log(self, level: LogLevel, message: str) -> None:
        """Write a log message to the underlying log implementation.

        This method should be implemented by concrete loggers.
        """

    def console_print(
        self,
        renderable: Any,
        level: "LogLevel" = LogLevel.INFO,
        **kwargs: Any,
    ) -> None:
        """Render a Rich renderable to the console sink only. Default no-op."""
        # Default no-op for non-console sinks

    def file_only_info(self, message: str) -> None:
        """Emit an info message to file sinks only (skip console). Default no-op."""
        # Default no-op for console-only sinks
