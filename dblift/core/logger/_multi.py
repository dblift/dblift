"""MultiLog — fan-out to multiple Log sinks.

Extracted from ``core/logger/log.py`` in PR-B5. Re-exported from
``dblift.core.logger.log`` for back-compat. ``ConsoleLog`` / ``FileLog``
references are routed through the ``log`` module to avoid a cycle:
``_multi`` is imported by ``log`` (re-export), and ``log`` exposes the
sink classes.
"""

import inspect
from typing import Any, List, Optional

from dblift.core.logger._base import Log
from dblift.core.logger._levels import LogLevel


class MultiLog(Log):
    """A log that delegates to multiple logs."""

    def __init__(self, logs: List[Log]):
        """Store the list of child sinks; fan-out is performed in each method."""
        self.logs = logs

    def is_debug_enabled(self) -> bool:
        """Return ``True`` if any child sink has debug logging enabled."""
        return any(log.is_debug_enabled() for log in self.logs)

    def debug(self, message: str) -> None:
        """Forward a debug message to every child sink."""
        for log in self.logs:
            log.debug(message)

    def info(self, message: str, console_only: bool = False, *, dedupe: bool = True) -> None:
        """Forward an info message, passing through ``console_only`` / ``dedupe`` where supported."""
        for log in self.logs:
            if not hasattr(log, "info"):
                continue
            params = inspect.signature(log.info).parameters
            if "dedupe" in params and "console_only" in params:
                log.info(message, console_only=console_only, dedupe=dedupe)
            elif "console_only" in params:
                log.info(message, console_only)
            else:
                log.info(message)

    def warn(self, message: str) -> None:
        """Forward a warning message to every child sink (each receives ``warning``)."""
        for log in self.logs:
            log.warning(message)

    def error(self, message: str) -> None:
        """Forward an error message to every child sink."""
        for log in self.logs:
            log.error(message)

    def error_with_exception(self, message: str, e: Exception) -> None:
        """Forward an error message together with its exception to every child sink."""
        for log in self.logs:
            log.error_with_exception(message, e)

    def notice(self, message: str) -> None:
        """Log a notice/success message."""
        for log in self.logs:
            log.notice(message)

    def is_html_enabled(self) -> bool:
        """Check if HTML logging is enabled in any of the underlying loggers."""
        return any(hasattr(log, "is_html_enabled") and log.is_html_enabled() for log in self.logs)

    def html(self, html_content: str) -> None:
        """Log HTML content directly to all loggers."""
        for log in self.logs:
            if hasattr(log, "html"):
                log.html(html_content)
            else:
                log.info(html_content)

    def console_print(
        self,
        renderable: Any,
        level: LogLevel = LogLevel.INFO,
        **kwargs: Any,
    ) -> None:
        """Forward Rich renderable only to ConsoleLog children."""
        # Local import to avoid the _multi → log → _multi cycle: ConsoleLog
        # is defined in core.logger.log which imports MultiLog at module
        # load. Resolving ConsoleLog at call time breaks the import order.
        from dblift.core.logger.log import ConsoleLog

        for log in self.logs:
            if isinstance(log, ConsoleLog):
                log.console_print(renderable, level=level, **kwargs)

    def file_only_info(self, message: str) -> None:
        """Forward info to FileLog children only — bypass ConsoleLog."""
        from dblift.core.logger.log import FileLog

        for log in self.logs:
            if isinstance(log, FileLog):
                log.info(message)

    def set_command_completed(
        self,
        success: bool,
        message: Optional[str] = None,
        command_type: Optional[str] = None,
        result: Optional[Any] = None,
    ) -> None:
        """Mark the active command as completed on every child sink."""
        for log in self.logs:
            log.set_command_completed(success, message, command_type, result)

    def set_multi_command_mode(self, enabled: bool = True) -> None:
        """Toggle multi-command mode on every child sink that supports it."""
        for log in self.logs:
            if hasattr(log, "set_multi_command_mode"):
                log.set_multi_command_mode(enabled)

    def set_command_type(self, command_type: str) -> None:
        """Set the command type on all logs."""
        for log in self.logs:
            if hasattr(log, "set_command_type"):
                log.set_command_type(command_type)
            elif hasattr(log, "command_type"):
                log.command_type = command_type

    def set_current_command(self, command_type: str) -> None:
        """Set the currently-executing command name on every child sink."""
        for log in self.logs:
            log.set_current_command(command_type)

    def close(self) -> None:
        """Close every child sink, flushing buffered output."""
        for log in self.logs:
            log.close()
