"""
Unit tests for DatabaseVersion.
"""

import pytest

from core.introspection.version_detector import DatabaseVersion

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
