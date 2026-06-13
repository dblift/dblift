"""
Unit tests for CapabilityMatrix.
"""

import pytest

from core.introspection.capability_matrix import CapabilityMatrix, FeatureRequirement
from core.introspection.version_detector import DatabaseVersion

pytestmark = [pytest.mark.unit]


class TestCapabilityMatrix:
    """Test cases for CapabilityMatrix."""

    def test_get_feature_requirement(self):
        """Test getting feature requirement."""
        req = CapabilityMatrix.get_feature_requirement("postgresql", "materialized_views")
        assert req is not None
        assert req.min_version is not None
        assert req.min_version.major == 9
        assert req.min_version.minor == 3

    def test_get_feature_requirement_not_found(self):
        """Test getting non-existent feature requirement."""
        req = CapabilityMatrix.get_feature_requirement("postgresql", "nonexistent_feature")
        assert req is None

    def test_check_feature_availability_supported(self):
        """Test checking available feature."""
        version = DatabaseVersion(12, 0)
        is_available, reason = CapabilityMatrix.check_feature_availability(
            "postgresql",
            "identity_columns",
            version,
        )
        assert is_available is True
        assert reason is None

    def test_check_feature_availability_unsupported_version(self):
        """Test checking feature with insufficient version."""
        version = DatabaseVersion(9, 3)
        is_available, reason = CapabilityMatrix.check_feature_availability(
            "postgresql",
            "generated_columns",
            version,
        )
        assert is_available is False
        assert "12.0" in reason or "requires" in reason.lower()

    def test_check_feature_availability_edition_restriction(self):
        """Test checking feature with edition restrictions."""
        version = DatabaseVersion(13, 0)  # SQL Server 2016
        is_available, reason = CapabilityMatrix.check_feature_availability(
            "sqlserver",
            "columnstore_indexes",
            version,
            edition="Standard",  # Standard edition doesn't support this
        )
        # Should fail due to edition restriction
        assert is_available is False or "Enterprise" in reason

    def test_get_available_features(self):
        """Test getting list of available features."""
        version = DatabaseVersion(12, 0)
        features = CapabilityMatrix.get_available_features("postgresql", version)

        assert isinstance(features, list)
        assert "identity_columns" in features
        assert "partitioning" in features
        # PostgreSQL 12.0 should include generated_columns (requires 12.0)
        assert "generated_columns" in features

    def test_get_unsupported_features(self):
        """Test getting list of unsupported features."""
        version = DatabaseVersion(9, 3)
        unsupported = CapabilityMatrix.get_unsupported_features("postgresql", version)

        assert isinstance(unsupported, list)
        # Should include features requiring higher versions
        unsupported_names = [name for name, _ in unsupported]
        assert "generated_columns" in unsupported_names or any(
            "generated" in name for name, _ in unsupported
        )

    def test_oracle_edition_features(self):
        """Test Oracle edition-specific features."""
        version = DatabaseVersion(12, 1)
        is_available, reason = CapabilityMatrix.check_feature_availability(
            "oracle",
            "adaptive_plans",
            version,
            edition="Standard",
        )
        # Adaptive plans require Enterprise edition
        assert is_available is False or "Enterprise" in reason

    def test_sqlserver_temporal_tables(self):
        """Test SQL Server temporal tables feature."""
        version = DatabaseVersion(13, 0)  # SQL Server 2016
        is_available, reason = CapabilityMatrix.check_feature_availability(
            "sqlserver",
            "temporal_tables",
            version,
        )
        assert is_available is True

    def test_mysql_json_support(self):
        """Test MySQL JSON data type support."""
        version = DatabaseVersion(5, 7)
        is_available, reason = CapabilityMatrix.check_feature_availability(
            "mysql",
            "json_data_type",
            version,
        )
        assert is_available is True

    def test_mysql_check_constraints(self):
        """Test MySQL CHECK constraints (8.0+)."""
        version = DatabaseVersion(8, 0)
        is_available, reason = CapabilityMatrix.check_feature_availability(
            "mysql",
            "check_constraints",
            version,
        )
        assert is_available is True

        # MySQL 5.7 should not support CHECK constraints
        version_57 = DatabaseVersion(5, 7)
        is_available, reason = CapabilityMatrix.check_feature_availability(
            "mysql",
            "check_constraints",
            version_57,
        )
        assert is_available is False
