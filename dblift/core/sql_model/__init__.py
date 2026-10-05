"""SQL object model — dialect-agnostic representations of tables, views, indexes, etc."""

from importlib import import_module
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from dblift.core.sql_model.base import (
        ParseResult,
        SqlColumn,
        SqlConstraint,
        SqlObject,
        SqlObjectType,
        SqlStatementType,
        get_constraint_type_name,
        get_object_type_name,
    )
    from dblift.core.sql_model.database_link import DatabaseLink
    from dblift.core.sql_model.dialect import quote_identifier, quote_qualified
    from dblift.core.sql_model.event import Event
    from dblift.core.sql_model.extension import Extension
    from dblift.core.sql_model.foreign_data_wrapper import ForeignDataWrapper
    from dblift.core.sql_model.foreign_server import ForeignServer
    from dblift.core.sql_model.index import Index
    from dblift.core.sql_model.linked_server import LinkedServer
    from dblift.core.sql_model.module import Module
    from dblift.core.sql_model.package import Package
    from dblift.core.sql_model.partition import Partition
    from dblift.core.sql_model.procedure import Parameter, Procedure
    from dblift.core.sql_model.sequence import Sequence
    from dblift.core.sql_model.synonym import Synonym
    from dblift.core.sql_model.table import Table
    from dblift.core.sql_model.trigger import Trigger
    from dblift.core.sql_model.user_defined_type import UserDefinedType
    from dblift.core.sql_model.view import View

__all__ = [
    "SqlObject",
    "SqlObjectType",
    "SqlStatementType",
    "SqlColumn",
    "SqlConstraint",
    "ParseResult",
    "get_constraint_type_name",
    "get_object_type_name",
    "quote_identifier",
    "quote_qualified",
    "Table",
    "View",
    "Sequence",
    "Procedure",
    "Parameter",
    "Index",
    "Trigger",
    "Synonym",
    "UserDefinedType",
    "Extension",
    "Package",
    "Module",
    "DatabaseLink",
    "LinkedServer",
    "ForeignDataWrapper",
    "ForeignServer",
    "Event",
    "Partition",
]

_EXPORT_MODULES = {
    **dict.fromkeys(
        (
            "SqlObject",
            "SqlObjectType",
            "SqlStatementType",
            "SqlColumn",
            "SqlConstraint",
            "ParseResult",
            "get_constraint_type_name",
            "get_object_type_name",
        ),
        "base",
    ),
    **dict.fromkeys(("quote_identifier", "quote_qualified"), "dialect"),
    "Table": "table",
    "View": "view",
    "Sequence": "sequence",
    "Procedure": "procedure",
    "Parameter": "procedure",
    "Index": "index",
    "Trigger": "trigger",
    "Synonym": "synonym",
    "UserDefinedType": "user_defined_type",
    "Extension": "extension",
    "Package": "package",
    "Module": "module",
    "DatabaseLink": "database_link",
    "LinkedServer": "linked_server",
    "ForeignDataWrapper": "foreign_data_wrapper",
    "ForeignServer": "foreign_server",
    "Event": "event",
    "Partition": "partition",
}


def __getattr__(name: str) -> Any:
    if name not in _EXPORT_MODULES:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(import_module(f"{__name__}.{_EXPORT_MODULES[name]}"), name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
