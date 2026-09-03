"""Tests for Flyway-compatible CRC32 checksum algorithm (Story 17-1)."""

import zlib
from unittest.mock import MagicMock

import pytest

from dblift.core.migration.migration import (
    Migration,
    calculate_migration_script_checksum,
    dict_to_migration,
    normalize_migration_checksum,
)
from dblift.core.migration.scripting.migration_script_manager import MigrationScriptManager


@pytest.mark.unit
class TestNormalizeMigrationChecksum:
    """JDBC may return CRC32 as unsigned; normalize to signed Java int."""

    def test_unsigned_equals_signed_repr(self):
        signed = -1022714467
        unsigned = signed & 0xFFFFFFFF  # 3272252829
        assert normalize_migration_checksum(unsigned) == signed
        assert normalize_migration_checksum(signed) == signed

    def test_small_positive_unchanged(self):
        assert normalize_migration_checksum(878567270) == 878567270

    def test_none_stays_none(self):
        assert normalize_migration_checksum(None) is None


@pytest.mark.unit
class TestFlywayChecksumAlgorithm:
    """Verify CRC32 line-by-line checksum matches Flyway behavior."""

    def _make_migration(self, content: str) -> Migration:
        return Migration(script_name="V1__test.sql", content=content)

    def test_empty_content_returns_zero(self):
        m = self._make_migration("")
        assert m.checksum == 0

    def test_single_line(self):
        m = self._make_migration("SELECT 1;")
        expected = zlib.crc32("SELECT 1;".encode("utf-8"))
        expected = expected if expected < 2**31 else expected - 2**32
        assert m.checksum == expected
        assert isinstance(m.checksum, int)

    def test_multiline_lf(self):
        content = "line1\nline2\n"
        m = self._make_migration(content)
        crc = 0
        for line in ["line1", "line2"]:
            crc = zlib.crc32(line.encode("utf-8"), crc)
        expected = crc if crc < 2**31 else crc - 2**32
        assert m.checksum == expected

    def test_crlf_equals_lf(self):
        m_lf = self._make_migration("line1\nline2")
        m_crlf = self._make_migration("line1\r\nline2")
        assert m_lf.checksum == m_crlf.checksum

    def test_unicode_content(self):
        content = "INSERT INTO t VALUES ('café', 'über');"
        m = self._make_migration(content)
        expected = zlib.crc32(content.encode("utf-8"))
        expected = expected if expected < 2**31 else expected - 2**32
        assert m.checksum == expected
        assert isinstance(m.checksum, int)

    def test_checksum_is_int_possibly_negative(self):
        # "Hello" produces CRC32 = 4157704578 > 2^31 → signed -137262718
        m = self._make_migration("Hello")
        assert isinstance(m.checksum, int)
        # CRC32 signed 32-bit range
        assert -(2**31) <= m.checksum < 2**31
        # Confirm this specific content actually produces a negative value
        assert m.checksum < 0


@pytest.mark.unit
class TestDictToMigrationChecksum:
    """Verify dict_to_migration() converts checksum to int correctly (AC#4)."""

    def _base_dict(self, checksum):
        return {"script": "V1__test.sql", "checksum": checksum, "type": "SQL"}

    def test_checksum_int_preserved_as_int(self):
        m = dict_to_migration(self._base_dict(12345))
        assert isinstance(m.checksum, int)
        assert m.checksum == 12345

    def test_checksum_string_converted_to_int(self):
        # JDBC drivers may return checksum as str; int() conversion must apply
        m = dict_to_migration(self._base_dict("67890"))
        assert isinstance(m.checksum, int)
        assert m.checksum == 67890

    def test_checksum_none_preserved_as_none(self):
        # BASELINE and DELETE migrations have no checksum (AC#3.2)
        m = dict_to_migration(self._base_dict(None))
        assert m.checksum is None

    def test_checksum_zero_preserved_as_zero(self):
        # Empty file checksum is 0 — must not be lost due to falsy check
        m = dict_to_migration(self._base_dict(0))
        assert isinstance(m.checksum, int)
        assert m.checksum == 0


@pytest.mark.unit
class TestScriptManagerChecksumMatchesMigration:
    """Regression: script_manager must use the same algorithm as Migration (not MD5)."""

    def test_calculate_checksum_equals_shared_crc32(self):
        sm = MigrationScriptManager(MagicMock(), script_encoding="utf-8")
        for content in ("", "SELECT 1;", "a\nb\n", "café"):
            assert sm.calculate_checksum(content) == calculate_migration_script_checksum(content)
            assert isinstance(sm.calculate_checksum(content), int)
