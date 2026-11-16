"""MariaDB database provider plugin."""

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .provider import MariadbProvider


def __getattr__(name: str) -> Any:
    if name != "MariadbProvider":
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    from .provider import MariadbProvider

    value = MariadbProvider
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))


__all__ = ["MariadbProvider"]
