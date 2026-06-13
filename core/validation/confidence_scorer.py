"""
Enhanced confidence scoring for schema introspection quality.

Provides weighted scoring that combines completeness, consistency, accuracy,
and error rate to give a comprehensive quality indicator.
"""

import logging
from typing import Any, Dict, Optional

from core.validation.result import ValidationResult

logger = logging.getLogger(__name__)


class ConfidenceScorer:
    """
    Calculates confidence scores for schema introspection.

    Scoring weights:
    - Completeness: 40% - How many objects/properties were captured
    - Consistency: 30% - How consistent are relationships
    - Accuracy: 20% - How accurate is captured state vs live
    - Error Rate: 10% - How many errors occurred during capture
    """

    # Scoring weights
    WEIGHT_COMPLETENESS = 0.40
    WEIGHT_CONSISTENCY = 0.30
    WEIGHT_ACCURACY = 0.20
    WEIGHT_ERROR_RATE = 0.10

    @classmethod
    def calculate_completeness_score(
        cls,
        completeness_result: Optional[ValidationResult],
        total_objects: int = 0,
    ) -> float:
        """Calculate completeness score (0.0 to 1.0).

        Args:
            completeness_result: Completeness validation result
            total_objects: Total number of objects expected

        Returns:
            Completeness score (0.0 to 1.0)
        """
        if not completeness_result:
            return 0.5  # Default to medium if no result

        if total_objects == 0:
            # If no expected count, use issue count as indicator
            issue_count = len(completeness_result.issues)
            if issue_count == 0:
                return 1.0
            # More issues = lower score
            return max(0.0, 1.0 - (issue_count * 0.1))

        # Calculate based on expected vs actual counts
        error_count = completeness_result.get_error_count()
        if error_count >= total_objects:
            return 0.0

        captured_count = total_objects - error_count
        return captured_count / total_objects if total_objects > 0 else 0.0

    @classmethod
    def calculate_consistency_score(
        cls,
        consistency_result: Optional[ValidationResult],
    ) -> float:
        """Calculate consistency score (0.0 to 1.0).

        Args:
            consistency_result: Consistency validation result

        Returns:
            Consistency score (0.0 to 1.0)
        """
        if not consistency_result:
            return 0.5  # Default to medium if no result

        if consistency_result.passed:
            return 1.0

        # Calculate based on error and warning counts
        error_count = consistency_result.get_error_count()
        warning_count = consistency_result.get_warning_count()
        total_issues = error_count + warning_count

        if total_issues == 0:
            return 1.0

        # Errors are more severe than warnings
        # Score decreases with more issues
        error_penalty = error_count * 0.2
        warning_penalty = warning_count * 0.1
        score = max(0.0, 1.0 - error_penalty - warning_penalty)

        return score

    @classmethod
    def calculate_accuracy_score(
        cls,
        accuracy_result: Optional[ValidationResult],
    ) -> float:
        """Calculate accuracy score (0.0 to 1.0).

        Args:
            accuracy_result: Accuracy validation result

        Returns:
            Accuracy score (0.0 to 1.0)
        """
        if not accuracy_result:
            return 0.5  # Default to medium if no result

        if accuracy_result.passed:
            return 1.0

        # Calculate based on differences found
        error_count = accuracy_result.get_error_count()
        warning_count = accuracy_result.get_warning_count()
        total_issues = error_count + warning_count

        if total_issues == 0:
            return 1.0

        # Get metadata about comparison
        accuracy_result.metadata.get("captured_count", 0)
        accuracy_result.metadata.get("live_count", 0)
        common_count = accuracy_result.metadata.get("common_count", 0)

        if common_count == 0:
            return 0.0

        # Score based on how many objects match vs differ
        match_ratio = (common_count - total_issues) / common_count if common_count > 0 else 0.0
        return max(0.0, match_ratio)

    @classmethod
    def calculate_error_rate_score(
        cls,
        error_count: int,
        warning_count: int,
        total_operations: int = 0,
    ) -> float:
        """Calculate error rate score (0.0 to 1.0).

        Args:
            error_count: Number of errors
            warning_count: Number of warnings
            total_operations: Total number of operations performed

        Returns:
            Error rate score (0.0 to 1.0, higher is better)
        """
        if total_operations == 0:
            # If no operations tracked, use issue counts
            total_issues = error_count + warning_count
            if total_issues == 0:
                return 1.0
            # More issues = lower score
            return max(0.0, 1.0 - (total_issues * 0.1))

        # Calculate error rate
        total_issues = error_count + warning_count
        error_rate = total_issues / total_operations if total_operations > 0 else 0.0

        # Convert error rate to score (lower error rate = higher score)
        return max(0.0, 1.0 - error_rate)

    @classmethod
    def calculate_overall_confidence(
        cls,
        completeness_result: Optional[ValidationResult] = None,
        consistency_result: Optional[ValidationResult] = None,
        accuracy_result: Optional[ValidationResult] = None,
        error_count: int = 0,
        warning_count: int = 0,
        total_objects: int = 0,
        total_operations: int = 0,
    ) -> Dict[str, Any]:
        """Calculate overall confidence score.

        Args:
            completeness_result: Completeness validation result
            consistency_result: Consistency validation result
            accuracy_result: Accuracy validation result
            error_count: Total error count
            warning_count: Total warning count
            total_objects: Total number of objects
            total_operations: Total number of operations

        Returns:
            Dictionary with confidence score and breakdown
        """
        # Calculate individual scores
        completeness_score = cls.calculate_completeness_score(completeness_result, total_objects)
        consistency_score = cls.calculate_consistency_score(consistency_result)
        accuracy_score = cls.calculate_accuracy_score(accuracy_result)
        error_rate_score = cls.calculate_error_rate_score(
            error_count, warning_count, total_operations
        )

        # Calculate weighted overall score
        overall_score = (
            completeness_score * cls.WEIGHT_COMPLETENESS
            + consistency_score * cls.WEIGHT_CONSISTENCY
            + accuracy_score * cls.WEIGHT_ACCURACY
            + error_rate_score * cls.WEIGHT_ERROR_RATE
        )

        # Determine confidence level
        if overall_score >= 0.95:
            confidence_level = "HIGH"
        elif overall_score >= 0.80:
            confidence_level = "MEDIUM"
        elif overall_score >= 0.60:
            confidence_level = "LOW"
        else:
            confidence_level = "VERY_LOW"

        return {
            "overall_score": overall_score,
            "confidence_level": confidence_level,
            "breakdown": {
                "completeness": {
                    "score": completeness_score,
                    "weight": cls.WEIGHT_COMPLETENESS,
                    "weighted": completeness_score * cls.WEIGHT_COMPLETENESS,
                },
                "consistency": {
                    "score": consistency_score,
                    "weight": cls.WEIGHT_CONSISTENCY,
                    "weighted": consistency_score * cls.WEIGHT_CONSISTENCY,
                },
                "accuracy": {
                    "score": accuracy_score,
                    "weight": cls.WEIGHT_ACCURACY,
                    "weighted": accuracy_score * cls.WEIGHT_ACCURACY,
                },
                "error_rate": {
                    "score": error_rate_score,
                    "weight": cls.WEIGHT_ERROR_RATE,
                    "weighted": error_rate_score * cls.WEIGHT_ERROR_RATE,
                },
            },
        }

    @classmethod
    def get_confidence_level(cls, score: float) -> str:
        """Get confidence level string from score.

        Args:
            score: Confidence score (0.0 to 1.0)

        Returns:
            Confidence level string
        """
        if score >= 0.95:
            return "HIGH"
        elif score >= 0.80:
            return "MEDIUM"
        elif score >= 0.60:
            return "LOW"
        else:
            return "VERY_LOW"
