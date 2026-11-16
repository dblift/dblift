"""DuckDB database provider plugin."""

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .provider import DuckDBProvider


def __getattr__(name: str) -> Any:
    if name != "DuckDBProvider":
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    from .provider import DuckDBProvider

    value = DuckDBProvider
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))


__all__ = ["DuckDBProvider"]
