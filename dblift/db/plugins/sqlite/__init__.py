"""SQLite database provider plugin."""

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .provider import SQLiteProvider


def __getattr__(name: str) -> Any:
    if name != "SQLiteProvider":
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    from .provider import SQLiteProvider

    value = SQLiteProvider
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))


__all__ = ["SQLiteProvider"]
