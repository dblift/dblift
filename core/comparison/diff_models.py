"""Diff Models for SQL Object Comparison Results.

This module defines structured classes to represent differences between
SQL Model objects, enabling precise tracking of schema drift.

Key Classes:
- DiffResult: Base class for all diff results
- TableDiff: Table-level differences
- ColumnDiff: Column-level differences
- ConstraintDiff: Constraint differences
- SchemaDiff: Schema-level summary

This module is a façade — the actual class definitions live in the
``_diff_*.py`` sibling modules (split in PR-G4). Public consumers continue
to import from ``core.comparison.diff_models`` as before; every name
below is re-exported.
"""

from core.comparison._diff_base import DiffResult, DiffSeverity
from core.comparison._diff_index import IndexDiff
from core.comparison._diff_routine import FunctionDiff, ProcedureDiff, RoutineDiff
from core.comparison._diff_schema import SchemaDiff
from core.comparison._diff_simple import (
    DatabaseLinkDiff,
    EventDiff,
    ExtensionDiff,
    ForeignDataWrapperDiff,
    ForeignServerDiff,
    LinkedServerDiff,
    ModuleDiff,
    PackageDiff,
    SequenceDiff,
    SynonymDiff,
    TriggerDiff,
    UserDefinedTypeDiff,
)
from core.comparison._diff_table import ColumnDiff, ConstraintDiff, TableDiff
from core.comparison._diff_view import ViewDiff

__all__ = [
    "ColumnDiff",
    "ConstraintDiff",
    "DatabaseLinkDiff",
    "DiffResult",
    "DiffSeverity",
    "EventDiff",
    "ExtensionDiff",
    "ForeignDataWrapperDiff",
    "ForeignServerDiff",
    "FunctionDiff",
    "IndexDiff",
    "LinkedServerDiff",
    "ModuleDiff",
    "PackageDiff",
    "ProcedureDiff",
    "RoutineDiff",
    "SchemaDiff",
    "SequenceDiff",
    "SynonymDiff",
    "TableDiff",
    "TriggerDiff",
    "UserDefinedTypeDiff",
    "ViewDiff",
]
