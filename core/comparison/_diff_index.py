"""Index diffs: ``IndexDiff``.

Extracted from ``diff_models.py`` (PR-G4).
"""

from dataclasses import dataclass
from typing import Any, ClassVar, List, Optional, Tuple

from core.comparison._diff_base import DiffResult, DiffSeverity


@dataclass
class IndexDiff(DiffResult):
    """Represents differences in an index definition.

    Attributes:
        index_name: Name of the index
        table_name: Table the index belongs to
        columns_changed: Whether indexed columns changed
        uniqueness_changed: Whether uniqueness constraint changed
        type_changed: Whether index type changed (btree, hash, fulltext, spatial, etc.)
        online_changed: Whether ONLINE/OFFLINE status changed (MySQL grammar-based)
        concurrently_changed: Whether CONCURRENTLY status changed (PostgreSQL grammar-based)
        tablespace_changed: Whether TABLESPACE changed (Oracle grammar-based)
        expected_columns: Expected indexed columns
        actual_columns: Actual indexed columns
    """

    _name_field: ClassVar[str] = "index_name"
    _object_type_label: ClassVar[str] = "index"

    index_name: str = ""
    table_name: str = ""
    columns_changed: bool = False
    uniqueness_changed: Optional[Tuple[Any, Any]] = None  # (expected, actual)
    type_changed: Optional[Tuple[Any, Any]] = (
        None  # (expected, actual) - Supports FULLTEXT, SPATIAL (MySQL grammar-based)
    )
    online_changed: Optional[Tuple[Any, Any]] = (
        None  # (expected, actual) - Grammar-based: MySQL ONLINE/OFFLINE
    )
    concurrently_changed: Optional[Tuple[Any, Any]] = (
        None  # (expected, actual) - Grammar-based: PostgreSQL CONCURRENTLY
    )
    tablespace_changed: Optional[Tuple[Any, Any]] = (
        None  # (expected, actual) - Grammar-based: Oracle TABLESPACE
    )
    include_columns_changed: Optional[Tuple[Any, Any]] = (
        None  # (expected, actual) - SQL Server INCLUDE columns
    )
    expected_columns: Optional[List[str]] = None
    actual_columns: Optional[List[str]] = None

    def _calculate_diffs(self) -> None:
        """Calculate whether differences exist and their severity."""
        self.has_diffs = (
            self.columns_changed
            or self.uniqueness_changed is not None
            or self.type_changed is not None
            or self.online_changed is not None  # Grammar-based: Track MySQL ONLINE/OFFLINE changes
            or self.concurrently_changed
            is not None  # Grammar-based: Track PostgreSQL CONCURRENTLY changes
            or self.tablespace_changed is not None  # Grammar-based: Track Oracle TABLESPACE changes
            or self.include_columns_changed is not None
            or any(any(opts.values()) for opts in self.dialect_options_changed.values())
        )

        if self.has_diffs:
            if self.columns_changed or self.uniqueness_changed is not None:
                self.severity = DiffSeverity.ERROR
            else:
                self.severity = DiffSeverity.WARNING
