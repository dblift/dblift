"""Unit tests for AlterGeneratorFactory's population latch.

Focus: ``_ensure_populated`` must not cache an empty registry as "done".

CLAUDE.md documents the failure this pins: ``entry_points(group='dblift.
features')`` is empty in some environments (paid packages installed without
their entry points reaching the process), and under those conditions
``ProviderRegistry.list_plugins()`` can come back empty too on a call that
races ahead of whatever registers the plugins. The factory used to set
``_populated = True`` unconditionally at the end of ``_ensure_populated``,
even when the loop registered nothing -- caching an empty registry for the
life of the process. A later call, even one that would have found real
plugins, short-circuited on the stale "already populated" flag and never
tried again.
"""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from dblift.core.sql_generator.alter.alter_generator_factory import AlterGeneratorFactory


def _make_plugin_info(name: str, dialects: list) -> MagicMock:
    info = MagicMock()
    info.name = name
    info.dialects = dialects
    return info


class TestEnsurePopulatedLatch(unittest.TestCase):
    def setUp(self):
        AlterGeneratorFactory.reset()

    def tearDown(self):
        AlterGeneratorFactory.reset()

    @patch(
        "dblift.core.sql_generator.alter.alter_generator_factory.attach_registered_sql_generators"
    )
    @patch("dblift.core.sql_generator.alter.alter_generator_factory.load_feature_extensions")
    @patch("dblift.db.provider_registry.ProviderRegistry")
    def test_empty_plugin_list_does_not_latch_populated(
        self, mock_registry, mock_load_features, mock_attach
    ):
        """No plugins found this call -> a later call must be allowed to retry."""
        mock_registry.list_plugins.return_value = []

        AlterGeneratorFactory._ensure_populated()

        self.assertEqual({}, AlterGeneratorFactory._generators)
        self.assertFalse(
            AlterGeneratorFactory._populated,
            "an empty registry must not be latched as populated, or a later "
            "call that WOULD find plugins never retries",
        )

    @patch(
        "dblift.core.sql_generator.alter.alter_generator_factory.attach_registered_sql_generators"
    )
    @patch("dblift.core.sql_generator.alter.alter_generator_factory.load_feature_extensions")
    @patch("dblift.db.provider_registry.ProviderRegistry")
    def test_a_later_call_with_plugins_available_succeeds_after_an_earlier_empty_call(
        self, mock_registry, mock_load_features, mock_attach
    ):
        """Reproduces the race directly: first call sees nothing, second call
        (as if a plugin registered in between) must actually populate --
        not stay empty because the first call already latched ``_populated``.
        """
        alter_class = MagicMock()
        alter_class.__name__ = "FakeAlterGenerator"
        quirks = MagicMock()
        quirks.alter_generator_class.return_value = alter_class

        mock_registry.list_plugins.return_value = []
        AlterGeneratorFactory._ensure_populated()
        self.assertEqual({}, AlterGeneratorFactory._generators)

        mock_registry.list_plugins.return_value = [_make_plugin_info("postgresql", ["postgresql"])]
        mock_registry.get_quirks.return_value = quirks
        AlterGeneratorFactory._ensure_populated()

        self.assertEqual({"postgresql": alter_class}, AlterGeneratorFactory._generators)
        self.assertTrue(AlterGeneratorFactory._populated)

    @patch(
        "dblift.core.sql_generator.alter.alter_generator_factory.attach_registered_sql_generators"
    )
    @patch("dblift.core.sql_generator.alter.alter_generator_factory.load_feature_extensions")
    @patch("dblift.db.provider_registry.ProviderRegistry")
    def test_non_empty_plugin_list_still_latches_as_before(
        self, mock_registry, mock_load_features, mock_attach
    ):
        """Regression guard: a normal, successful populate must still latch --
        this fix only targets the empty-registry case, not every call.
        """
        alter_class = MagicMock()
        alter_class.__name__ = "FakeAlterGenerator"
        quirks = MagicMock()
        quirks.alter_generator_class.return_value = alter_class
        mock_registry.list_plugins.return_value = [_make_plugin_info("postgresql", ["postgresql"])]
        mock_registry.get_quirks.return_value = quirks

        AlterGeneratorFactory._ensure_populated()

        self.assertEqual({"postgresql": alter_class}, AlterGeneratorFactory._generators)
        self.assertTrue(AlterGeneratorFactory._populated)

        # A second call must NOT re-run discovery -- list_plugins should not
        # be called again once genuinely populated.
        mock_registry.list_plugins.reset_mock()
        AlterGeneratorFactory._ensure_populated()
        mock_registry.list_plugins.assert_not_called()

    @patch(
        "dblift.core.sql_generator.alter.alter_generator_factory.attach_registered_sql_generators"
    )
    @patch("dblift.core.sql_generator.alter.alter_generator_factory.load_feature_extensions")
    @patch("dblift.db.provider_registry.ProviderRegistry")
    def test_plugins_found_but_none_contribute_a_generator_still_latches(
        self, mock_registry, mock_load_features, mock_attach
    ):
        """Pins the deliberate choice this fix makes: the latch is keyed on
        whether ``list_plugins()`` itself found anything, NOT on whether
        ``cls._generators`` ended up non-empty. Discovery genuinely
        completing and finding real plugins, none of which contribute an
        ALTER generator (e.g. every quirks class returns
        ``alter_generator_class() is None``, which is every OSS-shipped
        dialect's actual, permanent, correct default), is a stable fact
        about this plugin set -- not a race -- and must latch rather than
        re-running full discovery on every subsequent call for the rest of
        the process's life.
        """
        quirks = MagicMock()
        quirks.alter_generator_class.return_value = None
        mock_registry.list_plugins.return_value = [
            _make_plugin_info("postgresql", ["postgresql"]),
            _make_plugin_info("mysql", ["mysql"]),
        ]
        mock_registry.get_quirks.return_value = quirks

        AlterGeneratorFactory._ensure_populated()

        self.assertEqual({}, AlterGeneratorFactory._generators)
        self.assertTrue(
            AlterGeneratorFactory._populated,
            "plugins were genuinely found, so this is a stable empty "
            "result, not the race the fix targets -- it must latch",
        )

        mock_registry.list_plugins.reset_mock()
        AlterGeneratorFactory._ensure_populated()
        mock_registry.list_plugins.assert_not_called()


if __name__ == "__main__":
    unittest.main()
