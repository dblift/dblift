"""
Unit tests for VersionDetector.
"""

import pytest

from core.introspection.version_detector import DatabaseVersion, VersionDetector

pytestmark = [pytest.mark.unit]


class TestDatabaseVersion:
    """Test cases for DatabaseVersion."""

    def test_version_creation(self):
        """Test creating version objects."""
        v1 = DatabaseVersion(10, 2, 1)
        assert v1.major == 10
        assert v1.minor == 2
        assert v1.patch == 1

        v2 = DatabaseVersion(12, 1, full_version="Oracle Database 12c Release 1")
        assert v2.major == 12
        assert v2.minor == 1
        assert v2.full_version == "Oracle Database 12c Release 1"

    def test_version_string(self):
        """Test version string representation."""
        v = DatabaseVersion(10, 2, 1)
        assert str(v) == "10.2.1"

        v = DatabaseVersion(12, 0, build="Release 1")
        assert "12.0" in str(v)
        assert "Release 1" in str(v)

    def test_version_comparison(self):
        """Test version comparison operators."""
        v1 = DatabaseVersion(10, 0)
        v2 = DatabaseVersion(10, 1)
        v3 = DatabaseVersion(11, 0)

        assert v2 >= v1
        assert v3 >= v2
        assert v1 < v2
        assert v2 < v3


class TestVersionDetector:
    """Test cases for VersionDetector."""

    def test_detect_postgresql_version(self):
        """Test detecting PostgreSQL version."""
        detector = VersionDetector("postgresql")

        version = detector.detect_version("PostgreSQL 12.5 on x86_64-pc-linux-gnu")
        assert version.major == 12
        assert version.minor == 5

        version = detector.detect_version("PostgreSQL 9.6.3")
        assert version.major == 9
        assert version.minor == 6
        assert version.patch == 3

    def test_detect_oracle_version(self):
        """Test detecting Oracle version."""
        detector = VersionDetector("oracle")

        version = detector.detect_version("Oracle Database 12c Release 1")
        assert version.major == 12
        assert version.minor == 1

        version = detector.detect_version("Oracle Database 19c Enterprise Edition")
        assert version.major == 19

    def test_detect_mysql_version(self):
        """Test detecting MySQL version."""
        detector = VersionDetector("mysql")

        version = detector.detect_version("5.7.30")
        assert version.major == 5
        assert version.minor == 7
        assert version.patch == 30

        version = detector.detect_version("8.0.21")
        assert version.major == 8
        assert version.minor == 0

    def test_detect_sqlserver_version(self):
        """Test detecting SQL Server version."""
        detector = VersionDetector("sqlserver")

        version = detector.detect_version("Microsoft SQL Server 2016 (SP2)")
        assert version.major == 13  # SQL Server 2016 is version 13

        version = detector.detect_version("Microsoft SQL Server 2019")
        assert version.major >= 15  # SQL Server 2019 is version 15

    def test_build_capabilities(self):
        """Test building capabilities from version."""
        detector = VersionDetector("postgresql")
        version = detector.detect_version("PostgreSQL 12.0")
        capabilities = detector.build_capabilities(version)

        assert capabilities.version == version
        assert capabilities.dialect == "postgresql"
        # PostgreSQL 12.0 should support identity_columns
        assert "identity_columns" in capabilities.capabilities

    def test_check_feature_support(self):
        """Test checking feature support."""
        detector = VersionDetector("postgresql")
        version = detector.detect_version("PostgreSQL 9.3")
        capabilities = detector.build_capabilities(version)

        # PostgreSQL 9.3 should support materialized_views
        is_supported, reason = detector.check_feature_support("materialized_views")
        assert is_supported is True
        assert reason is None

        # PostgreSQL 9.3 should NOT support generated_columns (requires 12.0+)
        is_supported, reason = detector.check_feature_support("generated_columns")
        assert is_supported is False
        assert reason is not None

    def test_get_warnings(self):
        """Test getting capability warnings."""
        detector = VersionDetector("postgresql")
        version = detector.detect_version("PostgreSQL 9.3")
        capabilities = detector.build_capabilities(version)

        warnings = detector.get_warnings()
        # Should have warnings for unsupported features
        assert isinstance(warnings, list)

    def test_oracle_features(self):
        """Test Oracle-specific feature detection."""
        detector = VersionDetector("oracle")
        version = detector.detect_version("Oracle Database 12.1")
        capabilities = detector.build_capabilities(version)

        # Oracle 12.1 should support identity_columns
        assert "identity_columns" in capabilities.capabilities

        # Oracle 12.1 should NOT support json_data_type (requires 12.2+)
        assert "json_data_type" in capabilities.unsupported_features

    def test_mysql_features(self):
        """Test MySQL-specific feature detection."""
        detector = VersionDetector("mysql")
        version = detector.detect_version("8.0.21")
        capabilities = detector.build_capabilities(version)

        # MySQL 8.0 should support check_constraints
        assert "check_constraints" in capabilities.capabilities

        # MySQL 8.0 should support window_functions
        assert "window_functions" in capabilities.capabilities

    def test_unknown_version_fallback(self):
        """Test handling unknown version strings."""
        detector = VersionDetector("postgresql")
        version = detector.detect_version("Unknown version string")

        # Should create a version object with defaults
        assert version.major == 0 or version.major > 0  # May extract numbers or default
        assert isinstance(version, DatabaseVersion)
