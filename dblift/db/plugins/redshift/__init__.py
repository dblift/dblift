"""Redshift database provider plugin (PostgreSQL-compatible)."""

from .descriptor import DESCRIPTOR

__plugin_name__ = DESCRIPTOR.name
__plugin_version__ = "1.0.0"
__plugin_description__ = "Redshift database provider"
__plugin_dialects__ = list(DESCRIPTOR.dialects)
__plugin_transport__ = "native"
__plugin_class__ = "RedshiftProvider"

from importlib import import_module
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .provider import RedshiftProvider


def __getattr__(name: str) -> Any:
    if name != "RedshiftProvider":
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(import_module(f"{__name__}.provider"), "RedshiftProvider")
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))


__all__ = ["RedshiftProvider"]
