"""
Main state validator that coordinates all validation checks.
"""

import logging
from typing import Any, Dict, List, Optional

from core.sql_model.index import Index
from core.sql_model.table import Table
from core.sql_model.view import View
from core.validation.accuracy_validator import AccuracyValidator
from core.validation.completeness_validator import CompletenessValidator
from core.validation.confidence_scorer import ConfidenceScorer
from core.validation.consistency_validator import ConsistencyValidator
from core.validation.result import ValidationResult, ValidationSeverity

logger = logging.getLogger(__name__)


class StateValidator:
    """
    Main validator that coordinates completeness, consistency, and accuracy checks.

    This is the primary interface for validating schema introspection results.
    """

    def __init__(self, introspector=None):
        """Initialize the state validator.

        Args:
            introspector: Optional introspector for accuracy validation
        """
        self.completeness_validator = CompletenessValidator()
        self.consistency_validator = ConsistencyValidator()
        self.accuracy_validator = AccuracyValidator(introspector)

    def validate_schema(
        self,
        tables: List[Table],
        indexes: Optional[List[Index]] = None,
        views: Optional[List[View]] = None,
        schema: str = "public",
        expected_counts: Optional[Dict[str, int]] = None,
        live_objects: Optional[Dict[str, List]] = None,
    ) -> Dict[str, ValidationResult]:
        """Validate a complete schema.

        Args:
            tables: List of introspected tables
            indexes: Optional list of introspected indexes
            views: Optional list of introspected views
            schema: Schema name
            expected_counts: Optional dictionary of expected object counts
            live_objects: Optional dictionary of live objects for accuracy validation

        Returns:
            Dictionary of validation results by validator name
        """
        results = {}

        # Completeness validation
        from core.sql_model.base import SqlObject

        # Tables, indexes, and views are all SqlObject subclasses, so this is safe
        objects: Dict[str, List[SqlObject]] = {
            "tables": [t for t in tables]  # type: ignore[list-item]
        }
        if indexes:
            objects["indexes"] = [idx for idx in indexes]  # type: ignore[list-item]
        if views:
            objects["views"] = [v for v in views]  # type: ignore[list-item]

        completeness_result = self.completeness_validator.validate_objects(objects, expected_counts)
        results["completeness"] = completeness_result

        # Consistency validation
        consistency_result = self.consistency_validator.validate_all(tables, indexes, views, schema)
        results["consistency"] = consistency_result

        # Accuracy validation (if live objects provided)
        if live_objects:
            accuracy_result = self.accuracy_validator.validate_all(objects, live_objects, schema)
            results["accuracy"] = accuracy_result

        return results

    def get_overall_status(self, results: Dict[str, ValidationResult]) -> Dict[str, Any]:
        """Get overall validation status from multiple results.

        Args:
            results: Dictionary of validation results

        Returns:
            Dictionary with overall status information
        """
        all_passed = all(result.passed for result in results.values())
        total_errors = sum(result.get_error_count() for result in results.values())
        total_warnings = sum(result.get_warning_count() for result in results.values())

        # Determine overall severity
        if total_errors > 0:
            overall_severity = ValidationSeverity.ERROR
        elif total_warnings > 0:
            overall_severity = ValidationSeverity.WARNING
        else:
            overall_severity = ValidationSeverity.INFO

        # Calculate enhanced confidence score
        completeness_result = results.get("completeness")
        consistency_result = results.get("consistency")
        accuracy_result = results.get("accuracy")

        # Get total objects from metadata
        total_objects = 0
        if completeness_result:
            total_objects = completeness_result.metadata.get("object_counts", {}).get("tables", 0)

        confidence = ConfidenceScorer.calculate_overall_confidence(
            completeness_result=completeness_result,
            consistency_result=consistency_result,
            accuracy_result=accuracy_result,
            error_count=total_errors,
            warning_count=total_warnings,
            total_objects=total_objects,
        )

        return {
            "passed": all_passed,
            "overall_severity": overall_severity.value,
            "total_errors": total_errors,
            "total_warnings": total_warnings,
            "confidence": confidence,
            "validator_results": {name: result.to_dict() for name, result in results.items()},
        }
