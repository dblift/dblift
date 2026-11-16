"""Redshift database provider plugin (PostgreSQL-compatible)."""

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .provider import RedshiftProvider


def __getattr__(name: str) -> Any:
    if name != "RedshiftProvider":
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    from .provider import RedshiftProvider

    value = RedshiftProvider
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))


__all__ = ["RedshiftProvider"]
