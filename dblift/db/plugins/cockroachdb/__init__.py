"""CockroachDB database provider plugin (PostgreSQL-compatible)."""

from importlib import import_module
from typing import TYPE_CHECKING, Any

from .descriptor import DESCRIPTOR
from .sqlalchemy_dialect import register_cockroach_dialect

# Preserve registration on a plain package import, before any provider is loaded.
register_cockroach_dialect()

__plugin_name__ = DESCRIPTOR.name
__plugin_version__ = "1.0.0"
__plugin_description__ = "CockroachDB database provider"
__plugin_dialects__ = list(DESCRIPTOR.dialects)
__plugin_transport__ = "native"
__plugin_class__ = "CockroachdbProvider"

if TYPE_CHECKING:
    from .provider import CockroachdbProvider


def __getattr__(name: str) -> Any:
    if name != "CockroachdbProvider":
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(import_module(f"{__name__}.provider"), "CockroachdbProvider")
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))


__all__ = ["CockroachdbProvider"]
