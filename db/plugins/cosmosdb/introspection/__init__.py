"""CosmosDB plugin-side introspection."""

from typing import Any


def __getattr__(name: str) -> Any:
    if name == "CosmosDbIntrospector":
        from db.plugins.cosmosdb.introspection.cosmosdb_introspector import (
            CosmosDbIntrospector,
        )

        return CosmosDbIntrospector
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = ["CosmosDbIntrospector"]
