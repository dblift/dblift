"""Tests for truncate_sql_for_logging() in core.constants."""

import pytest

import dblift.core.constants as constants_module
from dblift.core.constants import (
    LOG_STATEMENT_PREVIEW_LENGTH,
    truncate_sql_for_logging,
)


@pytest.mark.unit
class TestTruncateSqlForLogging:
    """Tests for the truncate_sql_for_logging utility function."""

    def test_short_string_returned_as_is(self):
        result = truncate_sql_for_logging("SELECT 1", 50)
        assert result == "SELECT 1"

    def test_long_string_truncated_with_ellipsis(self):
        sql = "A" * 100
        result = truncate_sql_for_logging(sql, 50)
        assert result == "A" * 50 + "..."

    def test_exact_length_not_truncated(self):
        sql = "A" * 50
        result = truncate_sql_for_logging(sql, 50)
        assert result == "A" * 50
        assert "..." not in result

    def test_empty_string_returns_empty(self):
        result = truncate_sql_for_logging("", 50)
        assert result == ""

    def test_default_max_length_is_log_statement_preview_length(self):
        sql = "A" * 100
        result = truncate_sql_for_logging(sql)
        assert result == "A" * LOG_STATEMENT_PREVIEW_LENGTH + "..."

    def test_custom_max_length(self):
        sql = "A" * 300
        result = truncate_sql_for_logging(sql, max_length=200)
        assert result == "A" * 200 + "..."

    def test_ellipsis_appended_not_counted_in_max_length(self):
        sql = "A" * 60
        result = truncate_sql_for_logging(sql, 50)
        # Result is sql[:50] + "..." = 53 chars, NOT sql[:47] + "..."
        assert len(result) == 53
        assert result == "A" * 50 + "..."

    def test_function_exported_from_constants_module(self):
        """AC#1 structural: truncate_sql_for_logging must be accessible from core.constants (story 18-12)."""
        assert "truncate_sql_for_logging" in dir(constants_module)
