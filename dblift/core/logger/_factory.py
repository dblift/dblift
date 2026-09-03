"""LogFactory — central entry-point for obtaining configured loggers.

Extracted from ``core/logger/log.py`` in PR-B5. Re-exported from
``dblift.core.logger.log`` for back-compat. References to ``ConsoleLog`` /
``FileLog`` / ``MultiLog`` are resolved at call time through the
``log`` module to keep the import graph acyclic.
"""

import logging
from pathlib import Path
from typing import Any, List, Optional, Union

from dblift.core.logger._base import Log
from dblift.core.logger._levels import LogFormat, LogLevel


class LogFactory:
    """Factory for obtaining loggers."""

    _debug_enabled: bool = False
    _schema: Optional[str] = None
    _database_name: Optional[str] = None
    _log_format: LogFormat = LogFormat.TEXT
    _log_formats: List[LogFormat] = []  # Additional log formats
    _log_file_pattern: Optional[str] = None
    _existing_log_file: Optional[Path] = None
    _log_dir: Optional[Path] = None
    _use_console: bool = True
    _use_file: bool = True
    _log_level: LogLevel = LogLevel.INFO
    _console_log_level: Optional[LogLevel] = None

    @classmethod
    def enable_debug(cls, enable: bool = True) -> None:
        """Enable or disable debug logging."""
        cls._debug_enabled = enable

    @classmethod
    def set_schema(cls, schema: str) -> None:
        """Set schema name for logging."""
        cls._schema = schema

    @classmethod
    def set_database_name(cls, database_name: str) -> None:
        """Set database name for logging."""
        cls._database_name = database_name

    @classmethod
    def set_log_file_pattern(cls, pattern: str) -> None:
        """Set log file naming pattern."""
        cls._log_file_pattern = pattern

    @classmethod
    def use_existing_log_file(cls, log_file_path: Path) -> None:
        """Configure the logger to use an existing log file."""
        if not log_file_path.exists():
            raise ValueError(f"Log file {log_file_path} does not exist")

        cls._existing_log_file = log_file_path

    @classmethod
    def configure(
        cls,
        log_dir: Path,
        log_format: Union[LogFormat, List[LogFormat]] = LogFormat.TEXT,
        schema: Optional[str] = None,
        database_name: Optional[str] = None,
        log_file_pattern: Optional[str] = None,
        log_level: LogLevel = LogLevel.INFO,
        enable_debug: bool = False,  # Kept for backward compatibility
        use_console: bool = True,
        use_file: bool = True,
        additional_formats: Optional[List[LogFormat]] = None,
        log_file: Optional[str] = None,
        console_log_level: Optional[LogLevel] = None,
    ) -> None:
        """Configure the log factory.

        Args:
            log_dir: Directory for log files
            log_format: Primary log format or list of formats
            schema: Database schema name
            database_name: Database name
            log_file_pattern: Log file naming pattern
            log_level: The log level to use (DEBUG, INFO, WARN, ERROR)
            enable_debug: Whether to enable debug logging (deprecated, use log_level instead)
            use_console: Whether to log to console
            use_file: Whether to log to file
            additional_formats: Additional log formats to use (deprecated, use log_format as list)
            log_file: Optional specific log file name
        """
        # Suppress sqlglot warnings (they clutter the output with parser warnings)
        logging.getLogger("sqlglot").setLevel(logging.ERROR)

        # Clear any existing log file path
        cls._existing_log_file = None

        cls._log_dir = log_dir

        # Handle log_format as either a single format or a list of formats
        if isinstance(log_format, list):
            if log_format:  # If the list is not empty
                cls._log_format = log_format[0]  # First format is primary
                cls._log_formats = (
                    log_format[1:] if len(log_format) > 1 else []
                )  # Rest are additional
            else:
                cls._log_format = LogFormat.TEXT  # Default if empty list
                cls._log_formats = []
        else:
            cls._log_format = log_format
            cls._log_formats = additional_formats or []

        cls._schema = schema
        cls._database_name = database_name
        cls._log_file_pattern = log_file_pattern

        # Set custom log file if provided
        if log_file:
            log_file_path = Path(log_file)
            if not log_file_path.is_absolute():
                # Make sure path is absolute by combining with log_dir
                log_file_path = Path(log_dir) / log_file_path
            cls._existing_log_file = log_file_path

        # For backward compatibility, if enable_debug is True, set log_level to DEBUG
        if enable_debug:
            cls._log_level = LogLevel.DEBUG
            cls._debug_enabled = True
        else:
            cls._log_level = log_level
            # Set debug_enabled flag based on log_level
            cls._debug_enabled = log_level == LogLevel.DEBUG

        # Console-specific level override (e.g. ``--quiet`` raises the
        # console threshold to WARN while leaving file/JSON/HTML logs at
        # the user's chosen log_level so the audit trail stays complete).
        cls._console_log_level = console_log_level

        cls._use_console = use_console
        cls._use_file = use_file

    @classmethod
    def _effective_console_level(cls) -> "LogLevel":
        """Return the level threshold to apply to console sinks."""
        return cls._console_log_level if cls._console_log_level is not None else cls._log_level

    @classmethod
    def get_log(cls, clazz: Any) -> Log:
        """Get a logger for the specified class."""
        # Resolve at call time to avoid import-order issues with the
        # sink classes that live in core.logger.log.
        from dblift.core.logger._multi import MultiLog
        from dblift.core.logger.log import ConsoleLog, FileLog

        class_name = clazz.__name__ if hasattr(clazz, "__name__") else str(clazz)

        # Avoid recursion if the class is DbliftLogger
        if class_name == "DbliftLogger":
            return ConsoleLog(
                name=class_name,
                enable_debug=cls._debug_enabled,
                log_level=cls._effective_console_level(),
            )

        logs: List[Log] = []

        # Add console logger if enabled
        if cls._use_console:
            console_level = cls._effective_console_level()
            logs.append(
                ConsoleLog(
                    name=class_name,
                    enable_debug=cls._debug_enabled,
                    log_level=console_level,
                )
            )

        # Add file logger for primary format if enabled
        if cls._use_file and cls._log_dir:
            if cls._existing_log_file:
                # Create a FileLog that points to the existing file
                file_log = FileLog(
                    name=class_name,
                    log_dir=cls._existing_log_file.parent,
                    log_format=cls._log_format,
                    schema=cls._schema,
                    database_name=cls._database_name,
                    enable_debug=cls._debug_enabled,
                    log_level=cls._log_level,
                )
                # Override the auto-generated log file path with our specified one
                file_log.log_file = cls._existing_log_file
                logs.append(file_log)
            else:
                # Create a file logger for the primary format
                logs.append(
                    FileLog(
                        name=class_name,
                        log_dir=cls._log_dir,
                        log_format=cls._log_format,
                        schema=cls._schema,
                        database_name=cls._database_name,
                        log_file_pattern=cls._log_file_pattern,
                        enable_debug=cls._debug_enabled,
                        log_level=cls._log_level,
                    )
                )

                # Create file loggers for additional formats if specified
                for additional_format in cls._log_formats:
                    logs.append(
                        FileLog(
                            name=class_name,
                            log_dir=cls._log_dir,
                            log_format=additional_format,
                            schema=cls._schema,
                            database_name=cls._database_name,
                            log_file_pattern=cls._log_file_pattern,
                            enable_debug=cls._debug_enabled,
                            log_level=cls._log_level,
                        )
                    )

        # If no loggers are configured, default to console
        if not logs:
            logs.append(
                ConsoleLog(
                    name=class_name,
                    enable_debug=cls._debug_enabled,
                    log_level=cls._log_level,
                )
            )

        # Return a MultiLog if we have multiple loggers, otherwise return the single logger
        if len(logs) == 1:
            return logs[0]
        else:
            return MultiLog(logs)
