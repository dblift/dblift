"""Diff base: ``DiffSeverity`` enum and ``DiffResult`` dataclass.

Extracted from ``diff_models.py`` (PR-G4) to keep the façade thin. All
concrete ``*Diff`` subclasses inherit ``DiffResult`` from here.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, ClassVar, Dict, List, Optional, Tuple


class DiffSeverity(Enum):
    """Severity levels for differences."""

    ERROR = "error"  # Breaking changes (column removed, type incompatible)
    WARNING = "warning"  # Non-breaking but important (nullable changed)
    INFO = "info"  # Cosmetic differences (comments, formatting)


@dataclass
class DiffResult:
    """Base class for comparison results.

    Attributes:
        object_name: Name of the object being compared
        object_type: Type of object (table, view, procedure, etc.)
        severity: Highest severity of differences found
        has_diffs: Whether any differences were found
    """

    _name_field: ClassVar[str] = ""
    _object_type_label: ClassVar[str] = ""

    object_name: str
    object_type: str = ""
    severity: DiffSeverity = DiffSeverity.INFO
    has_diffs: bool = False
    # Tier-3 plugin-isolation scaffold. Plugins introducing NEW
    # comparison-relevant fields write here under their plugin namespace via
    # :meth:`mark_dialect_change` instead of adding flat ``<attr>_changed``
    # fields to ``*Diff`` subclasses; reads via :meth:`has_dialect_change`.
    dialect_options_changed: Dict[str, Dict[str, bool]] = field(default_factory=dict)

    def mark_dialect_change(self, plugin: str, key: str, changed: bool = True) -> None:
        """Record that *plugin*'s ``key`` differs between expected/actual.

        Setting ``changed=False`` clears the entry so :meth:`has_dialect_change`
        stays accurate.
        """
        bucket = self.dialect_options_changed.setdefault(plugin, {})
        if changed:
            bucket[key] = True
        else:
            bucket.pop(key, None)
            if not bucket:
                self.dialect_options_changed.pop(plugin, None)

    def has_dialect_change(self, plugin: str, key: str) -> bool:
        """Return whether *plugin*'s ``key`` was recorded as changed."""
        return bool(self.dialect_options_changed.get(plugin, {}).get(key, False))

    def __post_init__(self) -> None:
        """Set name field fallback, object_type, and calculate diffs."""
        if self._name_field and not getattr(self, self._name_field, None):
            setattr(self, self._name_field, self.object_name)
        if self._object_type_label:
            self.object_type = self._object_type_label
        self._calculate_diffs()

    def _calculate_diffs(self) -> None:
        """No-op base implementation — overridden by subclasses."""

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization.

        Returns:
            Dictionary representation of the diff result
        """
        return {
            "object_name": self.object_name,
            "object_type": self.object_type,
            "severity": self.severity.value,
            "has_diffs": self.has_diffs,
        }

    def __str__(self) -> str:
        """Human-readable string representation.

        Returns:
            Formatted string describing the diff
        """
        if not self.has_diffs:
            return f"{self.object_type} '{self.object_name}': No differences"

        return f"{self.object_type} '{self.object_name}': {self.severity.value.upper()} - Differences found"

    def get_summary(self) -> str:
        """Get a brief summary of differences.

        Returns:
            Brief summary string
        """
        status = "MATCH" if not self.has_diffs else f"DIFF ({self.severity.value})"
        return f"{self.object_type} '{self.object_name}': {status}"

    @staticmethod
    def _add_tuple_diffs(
        result_dict: Dict[str, Any],
        diff_fields: Dict[str, Optional[Tuple[Any, Any]]],
    ) -> None:
        """Add tuple diff fields to a 'differences' sub-dict for serialization.

        Args:
            result_dict: The dict being built (must already contain a 'differences' key)
            diff_fields: Mapping of field name to Optional (expected, actual) tuple
        """
        for name, value in diff_fields.items():
            if value is not None:
                result_dict["differences"][name] = {
                    "expected": value[0],
                    "actual": value[1],
                }

    @staticmethod
    def _format_tuple_diffs(diff_fields: Dict[str, Optional[Tuple[Any, Any]]]) -> List[str]:
        """Format tuple diff fields into human-readable 'name: expected -> actual' strings.

        Args:
            diff_fields: Mapping of field label to Optional (expected, actual) tuple

        Returns:
            List of formatted diff strings
        """
        parts = []
        for label, value in diff_fields.items():
            if value is not None:
                parts.append(f"{label}: {value[0]} → {value[1]}")
        return parts

    def _set_severity_from_pairs(
        self,
        pairs: List[Tuple[Any, DiffSeverity]],
    ) -> None:
        """Set ``has_diffs`` and ``severity`` from ``(is_set, severity)`` pairs.

        Each pair is ``(value, severity)`` where ``value`` is treated as
        truthy/falsy (``None``, ``False``, empty string, empty tuple
        are all "not set"). ``has_diffs`` becomes True if any pair has
        a truthy value; ``severity`` is the highest rank present (ERROR
        > WARNING > INFO).

        Args:
            pairs: list of ``(value, DiffSeverity)`` describing each
                diff-field's contribution. ``value`` may be a tuple,
                a bool, or any truthy/falsy expression.

        Notes:
            Centralises the pattern that 12+ ``*Diff`` subclasses
            previously inlined: ``self.has_diffs = any([...]); if
            <error_field>: self.severity = ERROR; elif <warning_field>:
            ...``. Subclasses with bespoke severity logic (TableDiff,
            ConstraintDiff, IndexDiff, ProcedureDiff, FunctionDiff,
            ViewDiff) keep their custom ``_calculate_diffs`` overrides;
            this helper is for the homogeneous "field-set ⇒ fixed
            severity" pattern.
        """
        any_set = False
        max_rank = DiffSeverity.INFO
        # Severity rank order (low → high): INFO, WARNING, ERROR.
        rank_value = {
            DiffSeverity.INFO: 0,
            DiffSeverity.WARNING: 1,
            DiffSeverity.ERROR: 2,
        }
        for value, severity in pairs:
            if not value:
                continue
            any_set = True
            if rank_value[severity] > rank_value[max_rank]:
                max_rank = severity
        self.has_diffs = any_set
        if any_set:
            self.severity = max_rank
