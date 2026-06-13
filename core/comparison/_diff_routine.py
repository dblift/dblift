"""Routine diffs: ``RoutineDiff`` base, ``ProcedureDiff``, ``FunctionDiff``.

Extracted from ``diff_models.py`` (PR-G4).
"""

from dataclasses import dataclass
from typing import Any, ClassVar, List, Optional, Tuple

from core.comparison._diff_base import DiffResult, DiffSeverity


@dataclass
class RoutineDiff(DiffResult):
    """Base class for procedure and function diffs.

    Attributes:
        definition_changed: Whether routine body changed
        parameters_changed: Whether parameters changed
        volatility_changed: (expected, actual) volatility tuple if changed
        security_definer_changed: (expected, actual) security definer tuple if changed
        definer_changed: (expected, actual) MySQL user@host definer tuple if changed
        comment_changed: (expected, actual) MySQL COMMENT clause tuple if changed
        data_access_changed: (expected, actual) MySQL data access tuple if changed
        expected_parameters: Expected parameter list
        actual_parameters: Actual parameter list
    """

    definition_changed: bool = False
    parameters_changed: bool = False
    volatility_changed: Optional[Tuple[Any, Any]] = None  # (expected, actual)
    security_definer_changed: Optional[Tuple[Any, Any]] = None  # (expected, actual)
    definer_changed: Optional[Tuple[Any, Any]] = None  # (expected, actual) - MySQL: user@host
    comment_changed: Optional[Tuple[Any, Any]] = None  # (expected, actual) - MySQL: COMMENT clause
    data_access_changed: Optional[Tuple[Any, Any]] = (
        None  # (expected, actual) - MySQL: NO SQL, CONTAINS SQL, etc.
    )
    expected_parameters: Optional[List[str]] = None
    actual_parameters: Optional[List[str]] = None

    def _has_base_diffs(self) -> bool:
        """Check common routine fields for differences."""
        return (
            self.definition_changed
            or self.parameters_changed
            or self.volatility_changed is not None
            or self.security_definer_changed is not None
            or self.definer_changed is not None
            or self.comment_changed is not None
            or self.data_access_changed is not None
            or any(any(opts.values()) for opts in self.dialect_options_changed.values())
        )


@dataclass
class ProcedureDiff(RoutineDiff):
    """Represents differences in a stored procedure definition."""

    _name_field: ClassVar[str] = "procedure_name"
    _object_type_label: ClassVar[str] = "procedure"

    procedure_name: str = ""

    def _calculate_diffs(self) -> None:
        """Calculate whether differences exist and their severity."""
        self.has_diffs = self._has_base_diffs()

        if self.has_diffs:
            if self.parameters_changed:
                # Parameter changes are errors (breaking change)
                self.severity = DiffSeverity.ERROR
            else:
                # Body changes are warnings (can be reapplied)
                self.severity = DiffSeverity.WARNING


@dataclass
class FunctionDiff(RoutineDiff):
    """Represents differences in a function definition."""

    _name_field: ClassVar[str] = "function_name"
    _object_type_label: ClassVar[str] = "function"

    function_name: str = ""
    return_type_changed: Optional[Tuple[Any, Any]] = None  # (expected, actual)

    def _calculate_diffs(self) -> None:
        """Calculate whether differences exist and their severity."""
        self.has_diffs = self._has_base_diffs() or self.return_type_changed is not None

        if self.has_diffs:
            if self.parameters_changed or self.return_type_changed:
                # Parameter/return type changes are errors (breaking change)
                self.severity = DiffSeverity.ERROR
            else:
                # Body changes are warnings (can be reapplied)
                self.severity = DiffSeverity.WARNING
