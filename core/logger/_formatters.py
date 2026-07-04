"""Plain-text and base log formatters.

Extracted from ``core/logger/log.py`` in PR-B5. Public API is re-exported
from ``core.logger.log`` for back-compat. JSON / HTML formatters live in
``core/logger/formatters/`` and are loaded lazily.
"""

import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from core.logger._levels import LogEvent, LogLevel

_logger = logging.getLogger(__name__)


class LogFormatter:
    """Base class for all log formatters."""

    def format_event(self, event: LogEvent) -> Optional[str]:
        """Format a log event."""
        return None

    def format_header(self, schema: str = None, database_name: str = None) -> Optional[str]:
        """Format a header for the log."""
        return None

    def format_footer(self) -> Optional[str]:
        """Format a footer for the log."""
        return None


class TextFormatter(LogFormatter):
    """Text formatter for log events."""

    #: License banner info, populated only when a higher tier registers a
    #: provider via the ``core.seams.license_info`` seam. ``None`` in a pure
    #: OSS install (no provider), so ``format_header`` renders no banner.
    license_info: Optional[Dict[str, Any]] = None

    def format_event(self, event: LogEvent) -> str:
        """Format a log event as text."""
        # For tables and multi-line content, just return the message
        if (
            event.message.strip().startswith("+")
            or "\n" in event.message
            or event.message.strip().startswith("|")
        ):
            return event.message

        # Format based on level
        if event.level == LogLevel.DEBUG:
            return f"DEBUG: {event.component}: {event.message}"
        elif event.level == LogLevel.INFO:
            return f"{event.message}"
        elif event.level == LogLevel.WARN:
            return f"WARNING: {event.message}"
        elif event.level == LogLevel.ERROR:
            return f"ERROR: {event.message}"
        elif event.level == LogLevel.NOTICE:
            return f"SUCCESS: {event.message}"
        else:
            return f"{event.message}"

    def format_header(self, schema: str = None, database_name: str = None) -> str:
        """Format a header for the text log."""
        lines = []
        lines.append("=" * 80)
        lines.append("DBLIFT DATABASE MIGRATION LOG")
        lines.append("-" * 80)

        # Add timestamp
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        lines.append(f"Timestamp: {current_time}")

        # Add Dblift version if available
        # Try multiple methods to get the version, prioritizing source code
        version = None

        # Method 1: Try to read from source __init__.py file (most reliable for development)
        try:
            # Path from core/logger/_formatters.py to root __init__.py: up 3 levels
            init_file = Path(__file__).parent.parent.parent / "__init__.py"
            if init_file.exists():
                with open(init_file, "r", encoding="utf-8") as f:
                    for line in f:
                        if line.startswith("__version__"):
                            # Extract version from: __version__ = "x.y.z"
                            parts = line.split("=", 1)
                            if len(parts) == 2:
                                version = parts[1].strip().strip('"').strip("'")
                                break
        except Exception as e:
            _logger.debug(f"Could not read version from __init__.py: {e}")

        # Method 2: Try to import directly from package (if source is in path)
        if not version:
            try:
                import dblift  # type: ignore[import-untyped]

                version = getattr(dblift, "__version__", None)
            except (ImportError, AttributeError):
                pass

        # Method 3: Fallback to pkg_resources (for installed packages)
        if not version:
            try:
                import pkg_resources  # type: ignore[import-untyped]

                version = pkg_resources.get_distribution("dblift").version
            except Exception as e:
                _logger.debug(f"Could not get version from pkg_resources: {e}")

        if version:
            lines.append(f"Dblift version: {version}")

        # License banner — inert in a pure OSS install (``license_info`` stays
        # ``None`` because no provider is registered on the
        # ``core.seams.license_info`` seam). A higher tier that registers a
        # provider populates it and the banner renders.
        if self.license_info:
            name = self.license_info.get("customer_name", "")
            email = self.license_info.get("customer_email", "")
            lines.append(f"Licensed to: {name} ({email})")
            expires = self.license_info.get("expires_at", "Never")
            days = self.license_info.get("days_remaining")
            if days is not None:
                lines.append(f"License expires: {expires} ({days} days remaining)")
            else:
                lines.append(f"License expires: {expires}")

        # Database/schema info intentionally omitted — rendered in the
        # per-command header (DBLIFT COMMAND: X) to avoid duplication.

        return "\n".join(lines)

    def format_footer(self) -> str:
        """Format a footer for the text log."""
        return "\n" + "=" * 80 + "\n"
