"""Tests for _info_result_to_dict installed_on serialization (BUG-02 fix)."""

from datetime import datetime
from unittest.mock import MagicMock

import pytest

from dblift.cli._command_handlers import _info_result_to_dict


def _make_migration(installed_on=None):
    m = MagicMock()
    m.script = "V1__init.sql"
    m.version = "1"
    m.description = "init"
    m.type = "SQL"
    m.status = "Success"
    m.checksum = 123456
    m.installed_on = installed_on
    m.installed_by = "dblift_test"
    m.execution_time = 42
    m.error = None
    return m


def _make_result(migration):
    result = MagicMock()
    result.migrations = [migration]
    result.current_schema_version = "1"
    result.target_schema = "public"
    result.applied_count = 1
    result.pending_count = 0
    result.failed_count = 0
    result.total_count = 1
    return result


@pytest.mark.unit
class TestInfoResultToDictInstalledOn:
    """BUG-02: _info_result_to_dict must not crash when installed_on is a string."""

    def test_string_installed_on_passes_through(self):
        """DB returns timestamp as string → serialized as-is, no crash."""
        migration = _make_migration(installed_on="2026-04-15 18:22:35")
        result = _make_result(migration)

        data = _info_result_to_dict(result)

        assert data["migrations"][0]["installed_on"] == "2026-04-15 18:22:35"

    def test_datetime_installed_on_uses_isoformat(self):
        """DB returns a datetime object → .isoformat() is called."""
        dt = datetime(2026, 4, 15, 18, 22, 35)
        migration = _make_migration(installed_on=dt)
        result = _make_result(migration)

        data = _info_result_to_dict(result)

        assert data["migrations"][0]["installed_on"] == dt.isoformat()

    def test_none_installed_on_returns_none(self):
        """installed_on=None → serialized as None (not a crash)."""
        migration = _make_migration(installed_on=None)
        result = _make_result(migration)

        data = _info_result_to_dict(result)

        assert data["migrations"][0]["installed_on"] is None
