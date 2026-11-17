"""SQL Server database provider plugin."""

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .provider import SqlServerProvider


def __getattr__(name: str) -> Any:
    if name != "SqlServerProvider":
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    from .provider import SqlServerProvider

    value = SqlServerProvider
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))


__all__ = ["SqlServerProvider"]
