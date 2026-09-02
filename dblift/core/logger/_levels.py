"""Log severity levels, format enums, and the event dataclass.

Extracted from ``core/logger/log.py`` in PR-B5. Public API is re-exported
from ``dblift.core.logger.log`` for back-compat.
"""

from datetime import datetime
from enum import Enum
from typing import Any, Dict, Optional


class LogFormat(Enum):
    """Log format options for Dblift."""

    TEXT = "text"
    JSON = "json"
    HTML = "html"

    def __str__(self) -> str:
        return self.value

    @classmethod
    def from_string(cls, value: str) -> "LogFormat":
        """Convert a string to a LogFormat enum value.

        Args:
            value: The string value to convert

        Returns:
            The corresponding LogFormat enum value

        Raises:
            ValueError: If the string is not a valid log format
        """
        try:
            return cls(value.lower())
        except ValueError:
            raise ValueError(
                f"Invalid log format: {value}. Valid formats are: {', '.join(f.value for f in cls)}"
            )


class LogLevel(Enum):
    """Log levels for Dblift."""

    DEBUG = "DEBUG"
    INFO = "INFO"
    WARN = "WARN"
    ERROR = "ERROR"
    NOTICE = "NOTICE"  # Used for success messages

    @classmethod
    def priority(cls, level: "LogLevel") -> int:
        """Numeric priority for level filtering (higher = more severe)."""
        return _LOG_LEVEL_PRIORITIES.get(level, 0)

    @classmethod
    def from_string(cls, value: str) -> "LogLevel":
        """Convert a string to a LogLevel enum value.

        Args:
            value: The string value to convert

        Returns:
            The corresponding LogLevel enum value

        Raises:
            ValueError: If the string is not a valid log level
        """
        try:
            return cls(value.upper())
        except ValueError:
            raise ValueError(
                f"Invalid log level: {value}. Valid levels are: {', '.join(l.name for l in cls)}"
            )


_LOG_LEVEL_PRIORITIES: Dict["LogLevel", int] = {}


def _initialize_log_level_priorities() -> None:
    _LOG_LEVEL_PRIORITIES.update(
        {
            LogLevel.DEBUG: 10,
            LogLevel.INFO: 20,
            LogLevel.NOTICE: 25,
            LogLevel.WARN: 30,
            LogLevel.ERROR: 40,
        }
    )


_initialize_log_level_priorities()


class LogEvent:
    """Represents a log event with all necessary information."""

    def __init__(
        self,
        level: LogLevel,
        message: str,
        component: str,
        timestamp: Optional[datetime] = None,
        context: Optional[Dict[str, Any]] = None,
    ):
        """Construct an event with the given level/message/component and optional timestamp/context."""
        self.level = level
        self.message = message
        self.component = component
        self.timestamp = timestamp or datetime.now()
        self.context = context or {}
