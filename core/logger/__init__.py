"""dblift logger package — log levels, sinks, formatters, and result aggregates."""

from core.logger.formatters import OutputFormatter, OutputFormatterFactory
from core.logger.log import (
    AbstractLog,
    ConsoleLog,
    FileLog,
    JsonFormatter,
    Log,
    LogEvent,
    LogFactory,
    LogFormat,
    LogLevel,
    MultiLog,
    NullLog,
)
from core.logger.results import (
    BaselineResult,
    CleanResult,
    DiffResult,
    InfoResult,
    MigrateResult,
    MigrationInfo,
    OperationResult,
    RepairResult,
    ValidateResult,
)
from core.utils.url_masking import mask_database_url

# Import HtmlFormatter conditionally
try:
    from .formatters.htmlformatter import HtmlFormatter

    JINJA_AVAILABLE = True
except ImportError:

    class DummyHtmlFormatter:
        """Placeholder stand-in for HtmlFormatter when Jinja2 is not installed."""

        def __init__(self, *args, **kwargs):
            pass

    HtmlFormatter = DummyHtmlFormatter  # type: ignore
    JINJA_AVAILABLE = False
import os
import traceback
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Dict, Generator, List, Optional


class DbliftLogger(Log):
    """Enhanced logger for DBLift operations with filtering for internal operations.

    This logger filters out internal operation messages at the INFO level,
    only showing user-relevant operations by default. Debug mode shows all messages.
    """

    logs: List[Log]
    command_type: Optional[str]
    current_section: Optional[str]
    config: Optional[Any]
    level: LogLevel
    format: LogFormat
    _custom_fields: Dict[str, Any]
    _filters: List[Callable[[Dict[str, Any]], bool]]
    _context_stack: List[Dict[str, Any]]
    logfile_dir: Optional[Path]
    current_log_file: Optional[Path]
    operation_result: Optional[OperationResult]
    log: Optional[Log]

    def __init__(
        self,
        name: str = "DBLift",
        level: LogLevel = LogLevel.INFO,
        format: LogFormat = LogFormat.TEXT,
        logfile_dir: Optional[Path] = None,
        config: Optional[Any] = None,
        log_file_pattern: Optional[str] = None,
    ):
        """Initialize the logger.

        Args:
            name: The name of the logger (usually component/class name)
            level: The log level to use
            format: Format for log files (TEXT, JSON, HTML)
            logfile_dir: Directory where log files will be stored (defaults to "./logs" if None)
            config: Optional configuration with database information
            log_file_pattern: Optional custom log file naming pattern
        """
        super().__init__(name, level == LogLevel.DEBUG)
        self.logs = []
        self.command_type = None
        self.current_section = None
        self.config = config
        self.level = level
        self.format = format
        self._custom_fields = {}
        self._filters = []
        self._context_stack = []
        self.logfile_dir = logfile_dir
        self.current_log_file = None
        self.operation_result = None

        # Avoid circular imports - create our own internal logger
        console_log = ConsoleLog(name=name, enable_debug=level == LogLevel.DEBUG)
        self.log = console_log

        # Default to "./logs" if no logfile_dir is provided
        if logfile_dir is None:
            logfile_dir = Path("./logs")
            # Create the directory if it doesn't exist
            if not logfile_dir.exists():
                os.makedirs(logfile_dir, exist_ok=True)

        self.logfile_dir = logfile_dir
        self.current_log_file = None

        # Set up console log
        console_log = ConsoleLog(name, enable_debug=level == LogLevel.DEBUG)
        self.logs.append(console_log)

        # Set up file log if directory is provided
        if logfile_dir:
            schema = (
                config.database.schema if config and hasattr(config.database, "schema") else None
            )
            database_name = (
                config.database.database_name
                if config and hasattr(config.database, "database_name")
                else None
            )
            if not database_name and config and hasattr(config.database, "server"):
                database_name = config.database.server

            file_log = FileLog(
                name,
                logfile_dir,
                format,
                schema=schema,
                database_name=database_name,
                log_file_pattern=log_file_pattern,
                enable_debug=level == LogLevel.DEBUG,
            )
            self.logs.append(file_log)
            self.current_log_file = file_log.log_file if hasattr(file_log, "log_file") else None

            # Add database URL and database type to log header
            if config and hasattr(config.database, "type"):
                # Add database type
                file_log.info(f"Database type: {config.database.type.upper()}")

            # Add database URL to log header if possible
            if config and hasattr(config.database, "build_database_url"):
                try:
                    database_url = config.database.build_database_url()
                    file_log.info(f"Database URL: {mask_database_url(str(database_url))}")
                except Exception as e:
                    file_log.debug(f"Could not build database URL for log header: {e}")

            # Add a separator line at the end of the header
            if format == LogFormat.TEXT:
                file_log.info("=" * 80)

        # Create a multi-log to handle all logs
        self.log = MultiLog(self.logs)

    def cleanup(self) -> None:
        """Clean up the logger by closing all handlers."""
        for log in self.logs:
            if hasattr(log, "close"):
                log.close()
        self.logs = []
        self.log = None

    def set_command_type(self, command_type: str) -> None:
        """Set the command type for the current operation.

        Args:
            command_type: The type of command being executed (e.g., 'MIGRATE', 'BASELINE')
        """
        if not command_type:
            return

        self.command_type = command_type.upper()

        # Set command type on all file logs
        for log in self.logs:
            if isinstance(log, FileLog):
                log.command_type = self.command_type if self.command_type is not None else None

                # Set command type on any formatters that support it
                if hasattr(log, "formatter") and hasattr(log.formatter, "set_current_command"):
                    log.formatter.set_current_command(self.command_type)

    def set_command_completed(
        self,
        success: bool = True,
        message: Optional[str] = None,
        command_type: Optional[str] = None,
        result: Optional[Any] = None,
    ) -> None:
        """Log a command completion message.

        Args:
            success: Whether the command completed successfully
            message: Optional details about the completion (should include execution time)
            command_type: The type of command (e.g., MIGRATE, VALIDATE)
        """
        if not command_type:
            command_type = getattr(self, "command_type", None)
        if not command_type:
            command_type = "COMMAND"
        command_type = command_type.upper()

        # If message is provided, use it directly (it should already include execution time)
        # Otherwise, delegate to the underlying log's set_command_completed
        if self.log is not None:
            if message:
                # Use the provided message directly
                self.log.info(message)
                if hasattr(self.log, "set_command_completed"):
                    # Propagate result/command metadata without duplicating message content
                    self.log.set_command_completed(success, None, command_type, result)
            else:
                # Fallback: delegate to underlying log's set_command_completed
                if hasattr(self.log, "set_command_completed"):
                    self.log.set_command_completed(success, message, command_type, result)
                else:
                    # Generate fallback message
                    if success:
                        self.log.info(f"Command {command_type.lower()} completed successfully")
                    else:
                        self.log.error(f"Command {command_type.lower()} failed")

        # Close any file logs if they're HTML format to ensure proper HTML rendering
        for log in self.logs:
            if (
                isinstance(log, FileLog)
                and hasattr(log, "format")
                and (
                    log.format == "html"
                    or (hasattr(log.format, "lower") and log.format.lower() == "html")
                )
            ):
                if hasattr(log, "command_type"):
                    log.command_type = command_type
                if result is not None:
                    log.operation_result = result
                if (
                    result is not None
                    and hasattr(log, "formatter")
                    and hasattr(log.formatter, "command_type")
                ):
                    log.formatter.command_type = command_type
                if hasattr(log, "formatter") and hasattr(log.formatter, "using_multi_command"):
                    log.formatter.using_multi_command = False
                if hasattr(log, "formatter") and hasattr(log.formatter, "command_results"):
                    log.formatter.command_results = []
                if hasattr(log, "migrations") and hasattr(self, "migrations"):
                    log.migrations = getattr(self, "migrations", [])
                if hasattr(log, "close"):
                    log.close()

        self.command_type = None

    def use_existing_log_file(self, log_file_path: Optional[Path] = None) -> None:
        """Configure the logger to use an existing log file instead of creating a new one.

        This is useful in testing scenarios where you want to continue logging to the same file
        across multiple test phases.

        Args:
            log_file_path: Path to an existing log file. If None, will use the most recent log file.
        """
        if log_file_path is None:
            if self.logfile_dir is not None:
                log_files = list(self.logfile_dir.glob("*.log"))
                if not log_files:
                    return
                log_file_path = max(log_files, key=lambda p: p.stat().st_mtime)
            else:
                return
        LogFactory.use_existing_log_file(log_file_path)
        self.log: Log = LogFactory.get_log(self.__class__)

    def debug(self, message: str) -> None:
        """Log a debug message."""
        if self.log is not None:
            self.log.debug(message)

    def info(self, message: str, console_only: bool = False, **kwargs) -> None:
        """Log an info message.

        Args:
            message: The message to log
            console_only: Whether to only log to console
            **kwargs: Additional fields to include in the log (e.g. dedupe=False)
        """
        if self.log is not None:
            dedupe = kwargs.pop("dedupe", True)
            self.log.info(message, console_only=console_only, dedupe=dedupe)

    def warn(self, message: str) -> None:
        """Log a warning message."""
        if self.log is not None:
            self.log.warning(message)

    def error(self, message: str, **kwargs) -> None:
        """Log an error message.

        Args:
            message: The message to log
            **kwargs: Additional fields to include in the log
        """
        if self.log is not None:
            self.log.error(message)

    def error_with_exception(self, message: str, e: Exception) -> None:
        """Log an error message with exception details."""
        error_msg = f"{message}: {str(e)}"
        if self.log is not None:
            self.log.error(error_msg)

    def notice(self, message: str) -> None:
        """Log a notice message."""
        if self.log is not None:
            self.log.notice(message)

    def close(self) -> None:
        """Close all log files properly.

        This is particularly important for HTML logs to ensure proper HTML rendering.
        """
        for log in self.logs:
            if hasattr(log, "close"):
                log.close()

    # Additional specialized logging methods used by migration_executor.py

    def is_debug_enabled(self) -> bool:
        """Check if debug logging is enabled.

        Returns:
            True if debug is enabled, False otherwise
        """
        return self.level == LogLevel.DEBUG

    def warning(self, message: str, **kwargs) -> None:
        """Log a warning message.

        Args:
            message: The message to log
            **kwargs: Additional fields to include in the log
        """
        if self.log is not None:
            self.log.warning(message)

    def exception(self, message: str, exc_info: bool = True, **kwargs) -> None:
        """Log an exception with traceback.

        Args:
            message: The message to log
            exc_info: Whether to include exception info
            **kwargs: Additional fields to include in the log
        """
        self._write_log(LogLevel.ERROR, message, **kwargs)
        if exc_info:
            self._write_log(LogLevel.ERROR, traceback.format_exc(), **kwargs)

    @contextmanager
    def context(self, **kwargs) -> Generator[None, None, None]:
        """Create a logging context with additional fields.

        Args:
            **kwargs: Fields to add to the context
        """
        self._context_stack.append(kwargs)
        try:
            yield
        finally:
            self._context_stack.pop()

    def _write_log(self, level: LogLevel, message: str, **kwargs) -> None:
        """Write a log message with additional fields.

        Args:
            level: The log level
            message: The message to log
            **kwargs: Additional fields to include in the log
        """
        # Merge custom fields, context stack, and kwargs
        fields = {}
        fields.update(self._custom_fields)
        for context in self._context_stack:
            fields.update(context)
        fields.update(kwargs)

        # Create log event
        event = LogEvent(level, message, self.name, context=fields)

        # Apply filters
        if self._filters:
            for filter_func in self._filters:
                if not filter_func(fields):
                    return

        # Write to all logs
        for log in self.logs:
            if hasattr(log, "_write_log_event"):
                if isinstance(log, FileLog):
                    log._write_log_event(event)
                else:
                    log._write_log_event(event, console_only=True)


# This is a wrapper implementation of the FileLog from log.py to avoid redefinition issues

__all__ = [
    "Log",
    "LogFactory",
    "LogFormat",
    "LogLevel",
    "AbstractLog",
    "FileLog",
    "ConsoleLog",
    "MultiLog",
    "OperationResult",
    "MigrateResult",
    "MigrationInfo",
    "InfoResult",
    "CleanResult",
    "ValidateResult",
    "BaselineResult",
    "RepairResult",
    "NullLog",
    "DbliftLogger",
    "DiffResult",
    # Formatters
    "OutputFormatter",
    "OutputFormatterFactory",
    # Moved to formatters package
    "HtmlFormatter",
    "JsonFormatter",
]
