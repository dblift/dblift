"""CockroachDB database provider plugin (PostgreSQL-compatible)."""

from typing import TYPE_CHECKING, Any

from .sqlalchemy_dialect import register_cockroach_dialect

# Preserve registration on a plain package import, before any provider is loaded.
register_cockroach_dialect()


if TYPE_CHECKING:
    from .provider import CockroachdbProvider


def __getattr__(name: str) -> Any:
    if name != "CockroachdbProvider":
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    from .provider import CockroachdbProvider

    value = CockroachdbProvider
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))


__all__ = ["CockroachdbProvider"]
