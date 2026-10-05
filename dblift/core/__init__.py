"""Core DBLift components.

This package contains the core migration engine, SQL model, parsers, generators, and validators.
"""

from importlib import import_module
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from dblift.core.sql_model import (
        DatabaseLink,
        Event,
        Extension,
        ForeignDataWrapper,
        ForeignServer,
        Index,
        LinkedServer,
        Module,
        Package,
        Parameter,
        ParseResult,
        Partition,
        Procedure,
        Sequence,
        SqlColumn,
        SqlConstraint,
        SqlObject,
        SqlObjectType,
        SqlStatementType,
        Synonym,
        Table,
        Trigger,
        UserDefinedType,
        View,
    )

__all__ = [
    "DatabaseLink",
    "Event",
    "Extension",
    "ForeignDataWrapper",
    "ForeignServer",
    "Index",
    "LinkedServer",
    "Module",
    "Package",
    "Parameter",
    "Partition",
    "ParseResult",
    "Procedure",
    "Sequence",
    "SqlColumn",
    "SqlConstraint",
    "SqlObject",
    "SqlObjectType",
    "SqlStatementType",
    "Synonym",
    "Table",
    "Trigger",
    "UserDefinedType",
    "View",
]


def __getattr__(name: str) -> Any:
    if name not in __all__:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(import_module("dblift.core.sql_model"), name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
