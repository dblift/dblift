"""View diffs: ``ViewDiff``.

Extracted from ``diff_models.py`` (PR-G4).
"""

from dataclasses import dataclass
from typing import Any, ClassVar, Dict, Optional, Tuple

from core.comparison._diff_base import DiffResult, DiffSeverity


@dataclass
class ViewDiff(DiffResult):
    """Represents differences in a view definition.

    Attributes:
        view_name: Name of the view
        definition_changed: Whether the view definition changed
        expected_definition: Expected view definition SQL
        actual_definition: Actual view definition SQL
        materialized_changed: Whether materialized status changed (PostgreSQL)
        unlogged_changed: Whether UNLOGGED status changed (PostgreSQL materialized views, grammar-based)
        algorithm_changed: Whether algorithm changed (MySQL grammar-based: MERGE, TEMPTABLE, UNDEFINED)
        sql_security_changed: Whether SQL SECURITY changed (MySQL grammar-based: DEFINER, INVOKER)
        definer_changed: Whether definer changed (MySQL grammar-based: user@host)
        force_changed: Whether FORCE/NOFORCE changed (Oracle grammar-based)
        security_definer_changed: Whether SECURITY DEFINER changed (PostgreSQL) - Diff-relevant
        security_invoker_changed: Whether SECURITY INVOKER changed (PostgreSQL) - Diff-relevant
        is_populated_changed: Whether populated status changed (materialized views)
        refresh_method_changed: Whether refresh method changed (Oracle, DB2)
        refresh_mode_changed: Whether refresh mode changed (Oracle)
        fast_refreshable_changed: Whether fast refresh capability changed (Oracle)
    """

    _name_field: ClassVar[str] = "view_name"
    _object_type_label: ClassVar[str] = "view"

    view_name: str = ""
    definition_changed: bool = False
    expected_definition: Optional[str] = None
    actual_definition: Optional[str] = None
    materialized_changed: Optional[Tuple[Any, Any]] = None  # (expected, actual)
    unlogged_changed: Optional[Tuple[Any, Any]] = (
        None  # (expected, actual) - Grammar-based: PostgreSQL UNLOGGED materialized views
    )
    algorithm_changed: Optional[Tuple[Any, Any]] = (
        None  # (expected, actual) - Grammar-based: MySQL view algorithm
    )
    sql_security_changed: Optional[Tuple[Any, Any]] = (
        None  # (expected, actual) - Grammar-based: MySQL SQL SECURITY
    )
    definer_changed: Optional[Tuple[Any, Any]] = (
        None  # (expected, actual) - Grammar-based: MySQL definer
    )
    force_changed: Optional[Tuple[Any, Any]] = (
        None  # (expected, actual) - Grammar-based: Oracle FORCE/NOFORCE
    )
    security_definer_changed: Optional[Tuple[Any, Any]] = (
        None  # (expected, actual) - Diff-relevant: PostgreSQL SECURITY DEFINER
    )
    security_invoker_changed: Optional[Tuple[Any, Any]] = (
        None  # (expected, actual) - Diff-relevant: PostgreSQL SECURITY INVOKER
    )
    is_populated_changed: Optional[Tuple[Any, Any]] = None  # (expected, actual)
    refresh_method_changed: Optional[Tuple[Any, Any]] = None  # (expected, actual)
    refresh_mode_changed: Optional[Tuple[Any, Any]] = None  # (expected, actual)
    fast_refreshable_changed: Optional[Tuple[Any, Any]] = None  # (expected, actual)

    def _calculate_diffs(self) -> None:
        """Calculate whether differences exist and their severity."""
        self.has_diffs = any(
            [
                self.definition_changed,
                self.materialized_changed is not None,
                self.unlogged_changed is not None,  # Grammar-based: Track UNLOGGED status changes
                self.algorithm_changed is not None,  # Grammar-based: Track MySQL algorithm changes
                self.sql_security_changed
                is not None,  # Grammar-based: Track MySQL SQL SECURITY changes
                self.definer_changed is not None,  # Grammar-based: Track MySQL definer changes
                self.force_changed is not None,  # Grammar-based: Track Oracle FORCE/NOFORCE changes
                self.security_definer_changed
                is not None,  # Diff-relevant: Track PostgreSQL SECURITY DEFINER changes
                self.security_invoker_changed
                is not None,  # Diff-relevant: Track PostgreSQL SECURITY INVOKER changes
                self.is_populated_changed is not None,
                self.refresh_method_changed is not None,
                self.refresh_mode_changed is not None,
                self.fast_refreshable_changed is not None,
                any(any(opts.values()) for opts in self.dialect_options_changed.values()),
            ]
        )

        if self.has_diffs:
            # Security context changes are errors (affect behavior)
            if (
                self.security_definer_changed is not None
                or self.security_invoker_changed is not None
            ):
                self.severity = DiffSeverity.ERROR
            else:
                # View definition changes are warnings (can be reapplied)
                self.severity = DiffSeverity.WARNING

    def _serialize_tuple(self, val: Optional[Tuple[Any, Any]]) -> Any:
        """Serialize an Optional[Tuple[Any, Any]] field as {'expected': ..., 'actual': ...} or None."""
        if val is None:
            return None
        return {"expected": val[0], "actual": val[1]}

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        result = super().to_dict()
        result.update(
            {
                "view_name": self.view_name,
                "definition_changed": self.definition_changed,
                "expected_definition": self.expected_definition,
                "actual_definition": self.actual_definition,
                "materialized_changed": self._serialize_tuple(self.materialized_changed),
                "unlogged_changed": self._serialize_tuple(self.unlogged_changed),
                "algorithm_changed": self._serialize_tuple(self.algorithm_changed),
                "sql_security_changed": self._serialize_tuple(self.sql_security_changed),
                "definer_changed": self._serialize_tuple(self.definer_changed),
                "force_changed": self._serialize_tuple(self.force_changed),
                "is_populated_changed": self._serialize_tuple(self.is_populated_changed),
                "refresh_method_changed": self._serialize_tuple(self.refresh_method_changed),
                "refresh_mode_changed": self._serialize_tuple(self.refresh_mode_changed),
                "fast_refreshable_changed": self._serialize_tuple(self.fast_refreshable_changed),
                "security_definer_changed": self._serialize_tuple(self.security_definer_changed),
                "security_invoker_changed": self._serialize_tuple(self.security_invoker_changed),
                "differences": {},
            }
        )
        if self.security_definer_changed is not None:
            result["differences"]["security_definer"] = {
                "expected": self.security_definer_changed[0],
                "actual": self.security_definer_changed[1],
            }
        if self.security_invoker_changed is not None:
            result["differences"]["security_invoker"] = {
                "expected": self.security_invoker_changed[0],
                "actual": self.security_invoker_changed[1],
            }
        return result
