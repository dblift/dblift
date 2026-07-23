"""
Unit tests for DatabaseVersion.
"""

import pytest

from core.introspection.version_detector import (
    DatabaseVersion,
    parse_version,
    version_matches_spec,
)

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


class TestParseVersion:
    """Test cases for the shared parse_version helper."""

    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("9.4", (9, 4, 0)),
            ("8.0.36", (8, 0, 36)),
            ("8.0.36-log", (8, 0, 36)),
            ("PostgreSQL 16.2 on x86_64-pc-linux-gnu", (16, 2, 0)),
            ("15.0.2000.5", (15, 0, 2000)),
            ("Oracle Database 19c Enterprise Edition Release 19.0.0.0.0", (19, 0, 0)),
        ],
    )
    def test_parses_first_dotted_run(self, raw, expected):
        version = parse_version(raw)
        assert version is not None
        assert (version.major, version.minor, version.patch) == expected
        assert version.full_version == raw

    @pytest.mark.parametrize("raw", [None, "", "no digits", "9"])
    def test_unparseable_returns_none(self, raw):
        assert parse_version(raw) is None


class TestVersionMatchesSpec:
    """Test cases for the shared version_matches_spec helper."""

    @pytest.mark.parametrize(
        "version,spec,expected",
        [
            ("9.4", "9.4+", True),
            ("9.5", "9.4+", True),
            ("9.3", "9.4+", False),
            ("10.5.2", "10.5.2+", True),
            ("10.5.1", "10.5.2+", False),
            ("8.0.36-log", "8.0+", True),
            # exact-match spec (no trailing '+')
            ("9.4", "9.4", True),
            ("9.4.0", "9.4", True),
            ("9.5", "9.4", False),
            # unparseable inputs never raise
            ("garbage", "9.4+", False),
            ("9.4", "garbage+", False),
            (None, "9.4+", False),
        ],
    )
    def test_spec_semantics(self, version, spec, expected):
        assert version_matches_spec(version, spec) is expected

    def test_accepts_database_version_instance(self):
        assert version_matches_spec(DatabaseVersion(9, 5), "9.4+") is True
        assert version_matches_spec(DatabaseVersion(9, 3), "9.4+") is False
