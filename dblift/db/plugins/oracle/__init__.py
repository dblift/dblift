"""Oracle database provider plugin."""

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .provider import OracleProvider


def __getattr__(name: str) -> Any:
    if name != "OracleProvider":
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    from .provider import OracleProvider

    value = OracleProvider
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))


__all__ = ["OracleProvider"]
