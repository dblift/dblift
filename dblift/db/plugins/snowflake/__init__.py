"""Snowflake database provider plugin."""

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .provider import SnowflakeProvider


def __getattr__(name: str) -> Any:
    if name != "SnowflakeProvider":
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    from .provider import SnowflakeProvider

    value = SnowflakeProvider
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))


__all__ = ["SnowflakeProvider"]
