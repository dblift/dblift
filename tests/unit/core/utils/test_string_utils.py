"""Unit tests for core.utils.string_utils module."""

import pytest

from dblift.core.utils.string_utils import safe_split_first


@pytest.mark.unit
class TestSafeSplitFirst:
    """Test safe_split_first function."""

    def test_split_with_separator(self):
        """Test splitting when separator is found."""
        result = safe_split_first("key=value", "=")
        assert result == "key"

    def test_split_with_separator_multiple_occurrences(self):
        """Test splitting on first occurrence when multiple exist."""
        result = safe_split_first("key=value=more", "=")
        assert result == "key"

    def test_no_separator_returns_default(self):
        """Test that default is returned when separator not found."""
        result = safe_split_first("no_separator", "=")
        assert result == ""

    def test_no_separator_with_custom_default(self):
        """Test that custom default is returned when separator not found."""
        result = safe_split_first("no_separator", "=", default="default_value")
        assert result == "default_value"

    def test_empty_string_returns_default(self):
        """Test that empty string returns default."""
        result = safe_split_first("", "=")
        assert result == ""

    def test_empty_string_with_custom_default(self):
        """Test that empty string returns custom default."""
        result = safe_split_first("", "=", default="default_value")
        assert result == "default_value"

    def test_none_text_returns_default(self):
        """Test that None text returns default."""
        result = safe_split_first(None, "=")
        assert result == ""

    def test_separator_at_start(self):
        """Test splitting when separator is at start."""
        result = safe_split_first("=value", "=")
        assert result == ""

    def test_separator_at_end(self):
        """Test splitting when separator is at end."""
        result = safe_split_first("key=", "=")
        assert result == "key"

    def test_multiple_char_separator(self):
        """Test splitting with multi-character separator."""
        result = safe_split_first("key::value", "::")
        assert result == "key"

    def test_separator_in_middle(self):
        """Test splitting when separator is in middle."""
        result = safe_split_first("before:after", ":")
        assert result == "before"
