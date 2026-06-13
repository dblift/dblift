"""Validation helper that wraps StateValidator for introspection results.

Lives in ``core/validation/`` (not ``db/introspection/``) so the
upward db→core layering boundary stays clean. The caller —
``core.migration.snapshots.schema_snapshot_service`` — passes an
introspector instance, and this module bridges its
``IntrospectionResult`` to the validators in ``core/validation/``.
"""

import logging
from typing import Any, Dict, List, Optional, Union

from core.introspection.result import IntrospectionResult
from core.sql_model.index import Index
from core.sql_model.table import Table
from core.sql_model.view import View
from core.validation.state_validator import StateValidator

logger = logging.getLogger(__name__)


class IntrospectionValidator:
    """
    Validates introspection results using the validation framework.

    This class provides a convenient interface to validate introspection
    results and get comprehensive quality metrics.
    """

    def __init__(self, introspector: Any = None) -> None:
        """Initialize the introspection validator.

        Args:
            introspector: Optional introspector for accuracy validation
        """
        self.state_validator = StateValidator(introspector)  # type: ignore[no-untyped-call]

    def validate_introspection(
        self,
        tables: List[Table],
        indexes: Optional[List[Index]] = None,
        views: Optional[List[View]] = None,
        schema: str = "public",
        introspection_result: Optional[IntrospectionResult] = None,
        live_objects: Optional[Dict[str, List[Any]]] = None,
    ) -> Dict[str, Any]:
        """Validate introspection results.

        Args:
            tables: List of introspected tables
            indexes: Optional list of introspected indexes
            views: Optional list of introspected views
            schema: Schema name
            introspection_result: Optional IntrospectionResult for error counting
            live_objects: Optional live objects dict for accuracy validation.
                Keys: 'tables', 'indexes', 'views'. When provided, accuracy
                comparison between captured and live objects is included.

        Returns:
            Dictionary with validation results and overall status
        """
        # Get error/warning counts from introspection result if provided
        error_count = 0
        warning_count = 0
        if introspection_result:
            error_count = len(introspection_result.errors)
            warning_count = len(introspection_result.warnings)

        # Run validation
        validation_results = self.state_validator.validate_schema(
            tables=tables,
            indexes=indexes,
            views=views,
            schema=schema,
            live_objects=live_objects,
        )

        # Get overall status with confidence scoring
        overall_status = self.state_validator.get_overall_status(validation_results)

        # Add introspection result metadata if available
        if introspection_result:
            overall_status["introspection"] = {
                "completeness_score": introspection_result.get_completeness_score(),
                "confidence_level": introspection_result.get_confidence_level(),
                "error_count": error_count,
                "warning_count": warning_count,
            }

        return {
            "validation_results": validation_results,
            "overall_status": overall_status,
        }

    def log_validation_summary(
        self,
        validation_output: Dict[str, Any],
        log: Optional[Union[logging.Logger, Any]] = None,
    ) -> None:
        """Log validation summary.

        Args:
            validation_output: Output from validate_introspection
            log: Optional logger instance
        """
        if not log:
            log = logger

        overall_status = validation_output["overall_status"]
        confidence = overall_status.get("confidence", {})

        log.info("Introspection Validation Summary:")
        log.info(f"  Overall Status: {'PASSED' if overall_status['passed'] else 'FAILED'}")
        confidence_level = confidence.get("confidence_level", "UNKNOWN")
        confidence_score = confidence.get("overall_score", 0)
        log.info(f"  Confidence: {confidence_level} ({confidence_score:.1%})")
        log.info(f"  Errors: {overall_status['total_errors']}")
        log.info(f"  Warnings: {overall_status['total_warnings']}")

        # Log per-validator results
        for validator_name, result in validation_output["validation_results"].items():
            if result.has_issues():
                errors = result.get_error_count()
                warnings = result.get_warning_count()
                log.warning(f"  {validator_name}: {errors} errors, {warnings} warnings")
            else:
                log.debug(f"  {validator_name}: PASSED")
