"""SQL parser package."""

from importlib import import_module
from typing import TYPE_CHECKING, Any

from dblift.core.sql_parser.statement import Statement, StatementKind

if TYPE_CHECKING:
    from dblift.core.sql_parser.parser_factory import SqlParserFactory

__all__ = ["SqlParserFactory", "Statement", "StatementKind"]


def __getattr__(name: str) -> Any:
    if name not in __all__:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(import_module(f"{__name__}.parser_factory"), name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
