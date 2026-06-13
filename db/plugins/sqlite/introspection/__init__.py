"""SQLite plugin-side introspection."""

from typing import Any


def __getattr__(name: str) -> Any:
    if name == "SQLiteIntrospector":
        from db.plugins.sqlite.introspection.sqlite_introspector import (
            SQLiteIntrospector,
        )

        return SQLiteIntrospector
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = ["SQLiteIntrospector"]
