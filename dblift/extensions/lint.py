"""Stable SQL-check imports for extensions: the checks ``validate-sql`` runs.

Importing this module does not need sqlglot. The rule names (``Finding``,
``find_issues``, ``SEVERITY`` and the severities) come from a module that does,
so they are resolved on first access; checking a script needs sqlglot as well.
"""

from importlib import import_module
from typing import TYPE_CHECKING, Any

from dblift.core.migration.sql.lint import (
    REVIEW,
    SAFE,
    UNSAFE,
    ScriptLint,
    allowed_codes,
    lint_analysis,
    lint_files,
    lint_pending_scripts,
    lint_script,
    lint_targets,
    verdict_of,
)
from dblift.core.migration.sql.script_analysis import ScriptAnalysis, analyse_script

if TYPE_CHECKING:
    from dblift.core.migration.sql.lint_rules import (
        ERROR,
        INFO,
        SEVERITY,
        WARNING,
        Finding,
        find_issues,
    )

_RULE_NAMES = frozenset({"ERROR", "Finding", "INFO", "SEVERITY", "WARNING", "find_issues"})

__all__ = [
    "ERROR",
    "Finding",
    "INFO",
    "REVIEW",
    "SAFE",
    "SEVERITY",
    "ScriptAnalysis",
    "ScriptLint",
    "UNSAFE",
    "WARNING",
    "allowed_codes",
    "analyse_script",
    "find_issues",
    "lint_analysis",
    "lint_files",
    "lint_pending_scripts",
    "lint_script",
    "lint_targets",
    "verdict_of",
]


def __getattr__(name: str) -> Any:
    if name not in _RULE_NAMES:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(import_module("dblift.core.migration.sql.lint_rules"), name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
