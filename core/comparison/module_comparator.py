"""Module Comparator for Drift Detection."""

import logging
from typing import Optional

from core.comparison.comparison_utils import normalize_package_code
from core.comparison.diff_models import ModuleDiff
from core.sql_model.module import Module

logger = logging.getLogger(__name__)


class ModuleComparator:
    """Compares DB2 module objects and generates diff results."""

    def __init__(self, type_normalizer: Optional[object] = None) -> None:
        pass

    def compare_modules(
        self,
        expected: Module,
        actual: Module,
        dialect: str = "",
    ) -> Optional[ModuleDiff]:
        """Compare two module objects.

        Args:
            expected: Expected module from migrations
            actual: Actual module from database
            dialect: SQL dialect (typically db2)

        Returns:
            ModuleDiff if differences found, None otherwise
        """
        module_name = expected.name or actual.name
        diff = ModuleDiff(object_name=module_name, module_name=module_name)

        expected_def = normalize_package_code(expected.definition)
        actual_def = normalize_package_code(actual.definition)

        if expected_def != actual_def:
            diff.definition_changed = True
            logger.info(f"Module '{module_name}': definition changed")

        diff._calculate_diffs()
        return diff if diff.has_diffs else None
