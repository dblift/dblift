"""Schema comparison components."""

from core.comparison.comparator import ObjectComparator
from core.comparison.diff_models import DiffResult
from core.comparison.type_normalizer import DataTypeNormalizer

__all__ = [
    "ObjectComparator",
    "DiffResult",
    "DataTypeNormalizer",
    "DiffReporter",
    "TableDiff",
    "ColumnDiff",
    "ConstraintDiff",
    "SchemaDiff",
]
