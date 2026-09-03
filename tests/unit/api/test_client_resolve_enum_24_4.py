"""Tests for SIMP-75: _resolve_enum_value extraction (story 24-4).

Verifies the helper correctly resolves None, enum, and string values
to the appropriate enum instance.
"""

import pytest

from dblift.api._client_factory import _resolve_enum_value
from dblift.core.logger import LogFormat, LogLevel

pytestmark = [pytest.mark.unit]


class TestResolveEnumValue:
    """Tests for _resolve_enum_value helper."""

    def test_none_returns_default(self):
        assert _resolve_enum_value(None, LogFormat, LogFormat.TEXT) is LogFormat.TEXT

    def test_enum_instance_passthrough(self):
        assert _resolve_enum_value(LogFormat.JSON, LogFormat, LogFormat.TEXT) is LogFormat.JSON

    def test_string_converted_via_from_string(self):
        result = _resolve_enum_value("json", LogFormat, LogFormat.TEXT)
        assert result is LogFormat.JSON

    def test_string_case_insensitive(self):
        result = _resolve_enum_value("Json", LogFormat, LogFormat.TEXT)
        assert result is LogFormat.JSON

    def test_log_level_none_returns_default(self):
        assert _resolve_enum_value(None, LogLevel, LogLevel.INFO) is LogLevel.INFO

    def test_log_level_string_converted(self):
        result = _resolve_enum_value("debug", LogLevel, LogLevel.INFO)
        assert result is LogLevel.DEBUG

    def test_log_level_enum_passthrough(self):
        assert _resolve_enum_value(LogLevel.ERROR, LogLevel, LogLevel.INFO) is LogLevel.ERROR
