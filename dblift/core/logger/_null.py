"""NullLog — no-op default for optional log parameters.

Extracted from ``core/logger/log.py`` in PR-B5. Re-exported from
``dblift.core.logger.log`` for back-compat. Inherits ``Log`` so it satisfies
``Optional[Log]`` annotations at every callsite.
"""

from typing import Any, Optional

from dblift.core.logger._base import Log


class NullLog(Log):
    """No-op logger used as the default value for optional ``log`` arguments.

    Replaces the ``if self.log: self.log.method(...)`` pattern across the
    codebase: callers can call methods unconditionally on a NullLog and
    every call silently no-ops. Inherits ``Log`` so static type checkers
    accept it wherever ``Optional[Log]`` is expected.
    """

    def __init__(self) -> None:
        pass  # No super().__init__() — no state needed.

    def debug(self, message: str, exc_info: bool = False) -> None:
        pass

    def info(self, message: str, console_only: bool = False, *, dedupe: bool = True) -> None:
        pass

    def warn(self, message: str) -> None:
        pass

    def warning(self, message: str) -> None:
        pass

    def error(self, message: str) -> None:
        pass

    def error_with_exception(self, message: str, e: Exception) -> None:
        pass

    def notice(self, message: str) -> None:
        pass

    def set_command_type(self, command_type: str) -> None:
        pass

    def set_command_completed(
        self,
        success: bool,
        message: Optional[str] = None,
        command_type: Optional[str] = None,
        result: Optional[Any] = None,
    ) -> None:
        pass

    def set_current_command(self, command_type: str) -> None:
        pass

    def close(self) -> None:
        pass

    def is_debug_enabled(self) -> bool:
        """Always return False — the null log never emits debug output."""
        return False
