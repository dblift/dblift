"""Cosmos DB database provider plugin."""

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .provider import CosmosDbProvider


def __getattr__(name: str) -> Any:
    if name != "CosmosDbProvider":
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    from .provider import CosmosDbProvider

    value = CosmosDbProvider
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))


__all__ = ["CosmosDbProvider"]
