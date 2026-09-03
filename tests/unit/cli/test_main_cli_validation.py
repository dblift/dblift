"""Unit tests for CLI validation logic.

These tests verify that _validate_migrate_options correctly detects
conflicting options and calls parser.error() as expected.
"""

import argparse
from unittest.mock import MagicMock, patch

import pytest

from dblift.cli.main import _validate_migrate_options, create_parser

pytestmark = [pytest.mark.unit]


class TestCommandValidation:
    """Test _validate_migrate_options production validation logic."""

    def _make_args(self, **kwargs):
        """Build a namespace with default None values for version/tag filters."""
        defaults = {
            "target_version": None,
            "versions": None,
            "exclude_versions": None,
            "tags": None,
            "exclude_tags": None,
        }
        defaults.update(kwargs)
        return argparse.Namespace(**defaults)

    def test_target_version_and_versions_conflict(self):
        """_validate_migrate_options raises on --target-version + --versions."""
        args = self._make_args(target_version="1.0.0", versions="1.0.0,2.0.0")
        parser = MagicMock()
        _validate_migrate_options(args, parser)
        parser.error.assert_called_once()
        assert "target-version" in parser.error.call_args[0][0].lower()

    def test_target_version_and_exclude_versions_allowed(self):
        """_validate_migrate_options allows --target-version + --exclude-versions together."""
        args = self._make_args(target_version="1.0.0", exclude_versions="3.0.0")
        parser = MagicMock()
        _validate_migrate_options(args, parser)
        parser.error.assert_not_called()

    def test_conflicting_tags_detected(self):
        """_validate_migrate_options detects overlapping tags and exclude_tags."""
        args = self._make_args(tags="tag1,tag2", exclude_tags="tag1")
        parser = MagicMock()
        _validate_migrate_options(args, parser)
        parser.error.assert_called_once()
        assert "tag" in parser.error.call_args[0][0].lower()

    def test_no_conflicting_tags_passes(self):
        """_validate_migrate_options does not call parser.error with non-overlapping tags."""
        args = self._make_args(tags="tag1,tag2", exclude_tags="tag3")
        parser = MagicMock()
        _validate_migrate_options(args, parser)
        parser.error.assert_not_called()

    def test_conflicting_versions_detected(self):
        """_validate_migrate_options detects overlapping versions and exclude_versions."""
        args = self._make_args(versions="1.0.0,2.0.0", exclude_versions="2.0.0")
        parser = MagicMock()
        _validate_migrate_options(args, parser)
        parser.error.assert_called_once()
        assert "version" in parser.error.call_args[0][0].lower()

    def test_no_conflicts_passes(self):
        """_validate_migrate_options does not call parser.error when no conflicts exist."""
        args = self._make_args(versions="1.0.0", exclude_versions="2.0.0")
        parser = MagicMock()
        _validate_migrate_options(args, parser)
        parser.error.assert_not_called()

    def test_all_none_passes(self):
        """_validate_migrate_options does not call parser.error when all filters are None."""
        args = self._make_args()
        parser = MagicMock()
        _validate_migrate_options(args, parser)
        parser.error.assert_not_called()
