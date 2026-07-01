"""Tests for _extract_version_filters() and available_commands derivation (Story 14-4, DEDUP-11/DEDUP-12)."""

import argparse
import unittest

import pytest

pytestmark = [pytest.mark.unit]

from cli.extensions import load_terminal_commands
from cli.main import (
    _AVAILABLE_COMMANDS,
    _COMMAND_HANDLERS,
    _extract_version_filters,
    _validate_migrate_options,
)


class TestExtractVersionFilters(unittest.TestCase):
    """AC#9 — Tests for the _extract_version_filters() helper."""

    def test_args_without_any_attr_returns_five_none(self):
        """Args with no version/tag attributes → all 5 values are None."""
        args = argparse.Namespace()
        result = _extract_version_filters(args)
        self.assertEqual(result, (None, None, None, None, None))
        self.assertEqual(len(result), 5)

    def test_args_with_all_attrs_returns_correct_values(self):
        """Args with all 5 attributes → values extracted correctly."""
        args = argparse.Namespace(
            target_version="2.0",
            versions="1.0,2.0",
            exclude_versions="0.1",
            tags="hotfix",
            exclude_tags="wip",
        )
        result = _extract_version_filters(args)
        self.assertEqual(result, ("2.0", "1.0,2.0", "0.1", "hotfix", "wip"))

    def test_args_with_partial_attrs_defaults_none(self):
        """Args with only some attributes → missing ones default to None."""
        args = argparse.Namespace(tags="release", versions="3.0")
        target_version, versions, exclude_versions, tags, exclude_tags = _extract_version_filters(
            args
        )
        self.assertIsNone(target_version)
        self.assertEqual(versions, "3.0")
        self.assertIsNone(exclude_versions)
        self.assertEqual(tags, "release")
        self.assertIsNone(exclude_tags)

    def test_consistent_with_validate_migrate_options(self):
        """_validate_migrate_options detects conflicts using the same values as _extract_version_filters."""
        parser = argparse.ArgumentParser()
        # Conflicting args: target_version AND versions both set → _validate_migrate_options raises SystemExit
        conflict_args = argparse.Namespace(
            target_version="1.0",
            versions="1.0,2.0",
            exclude_versions=None,
            tags=None,
            exclude_tags=None,
        )
        # Verify _extract_version_filters returns the conflicting values
        target_version, versions, exclude_versions, tags, exclude_tags = _extract_version_filters(
            conflict_args
        )
        self.assertEqual(target_version, "1.0")
        self.assertEqual(versions, "1.0,2.0")
        # Verify _validate_migrate_options uses the same extracted values (detects the conflict)
        with self.assertRaises(SystemExit):
            _validate_migrate_options(conflict_args, parser)

    def test_return_type_is_tuple_of_five(self):
        """Return value is always a tuple of exactly 5 elements."""
        args = argparse.Namespace()
        result = _extract_version_filters(args)
        self.assertIsInstance(result, tuple)
        self.assertEqual(len(result), 5)


class TestAvailableCommandsDerivation(unittest.TestCase):
    """AC#12 — Tests for available_commands derived from _COMMAND_HANDLERS via _AVAILABLE_COMMANDS."""

    def test_db_is_in_available_commands(self):
        """'db' must be present in _AVAILABLE_COMMANDS."""
        self.assertIn("db", _AVAILABLE_COMMANDS)

    def test_all_handler_keys_in_available_commands(self):
        """Every key in _COMMAND_HANDLERS must be in _AVAILABLE_COMMANDS."""
        for key in _COMMAND_HANDLERS:
            self.assertIn(key, _AVAILABLE_COMMANDS)

    def test_length_is_handlers_plus_extra(self):
        """_AVAILABLE_COMMANDS has handlers + offline subparser groups + terminal extension commands.

        ``db`` and ``config`` are offline commands that short-circuit in
        cli.main before any client is built, so they are listed in
        _AVAILABLE_COMMANDS but are not client-backed _COMMAND_HANDLERS.
        """
        extra_commands = {"db", "config"} | set(load_terminal_commands())
        self.assertEqual(len(_AVAILABLE_COMMANDS), len(_COMMAND_HANDLERS) + len(extra_commands))

    def test_subparser_groups_not_in_command_handlers(self):
        """'db' and 'config' are offline subparser groups, not client-backed handlers."""
        self.assertNotIn("db", _COMMAND_HANDLERS)
        self.assertNotIn("config", _COMMAND_HANDLERS)


if __name__ == "__main__":
    unittest.main()
