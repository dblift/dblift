"""Formatters for log messages."""

from typing import TYPE_CHECKING, Any

from dblift.core.logger.formatters.factory import OutputFormatterFactory
from dblift.core.logger.formatters.formatter import OutputFormatter
from dblift.core.logger.formatters.jsonformatter import JsonFormatter

if TYPE_CHECKING:
    from dblift.core.logger.formatters.htmlformatter import HtmlFormatter

__all__ = [
    "OutputFormatter",
    "OutputFormatterFactory",
    "HtmlFormatter",
    "JsonFormatter",
]


def __getattr__(name: str) -> Any:
    if name == "HtmlFormatter":
        from dblift.core.logger.formatters.htmlformatter import HtmlFormatter

        globals()[name] = HtmlFormatter
        return HtmlFormatter
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
