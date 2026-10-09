"""PostgreSQL database provider plugin."""

from .descriptor import DESCRIPTOR

__plugin_name__ = DESCRIPTOR.name
__plugin_version__ = "1.0.0"
__plugin_description__ = "PostgreSQL database provider"
__plugin_dialects__ = list(DESCRIPTOR.dialects)
__plugin_transport__ = "native"
__plugin_class__ = "PostgreSqlProvider"

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .provider import PostgreSqlProvider


def __getattr__(name: str) -> Any:
    if name != "PostgreSqlProvider":
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    from .provider import PostgreSqlProvider

    value = PostgreSqlProvider
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))


__all__ = ["PostgreSqlProvider"]
