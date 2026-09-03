"""Tests for provider_registry module-level logging (Story 16-8)."""

import inspect
from unittest.mock import MagicMock, patch

import dblift.db.provider_registry as reg_mod
from dblift.db.provider_registry import ProviderRegistry


class TestProviderRegistryLogging:
    """Verify import logging is module-level, not inline."""

    def test_no_inline_import_logging_in_discover_plugins(self):
        """AC#5.1 — 'import logging' must not appear inline in discover_plugins."""
        source = inspect.getsource(ProviderRegistry.discover_plugins)
        lines = source.splitlines()
        assert not any(
            line.strip() == "import logging" for line in lines
        ), "import logging should not appear inline in discover_plugins"

    def test_logger_is_module_level(self):
        """AC#5.2 — _logger exists at module level."""
        assert hasattr(
            reg_mod, "_logger"
        ), "_logger should exist at module level in provider_registry"
        assert reg_mod._logger.name == "dblift.db.provider_registry"

    def test_no_local_logger_variable_in_discover_plugins(self):
        """AC#4 — No local 'logger' variable should remain in discover_plugins."""
        source = inspect.getsource(ProviderRegistry.discover_plugins)
        lines = source.splitlines()
        for line in lines:
            stripped = line.strip()
            assert not stripped.startswith(
                "logger = logging.getLogger"
            ), f"Local logger assignment found in discover_plugins: {line!r}"

    def test_discover_plugins_logs_warning_on_load_failure(self):
        """AC#5.3 — When _load_plugin raises, _logger.warning is called."""
        original_discovered = ProviderRegistry._discovered
        original_plugins = ProviderRegistry._plugins.copy()

        try:
            ProviderRegistry._discovered = False
            ProviderRegistry._plugins = {}

            fake_dir = MagicMock()
            fake_dir.is_dir.return_value = True
            fake_dir.name = "fake_plugin"

            mock_plugins_dir = MagicMock()
            mock_plugins_dir.exists.return_value = True
            mock_plugins_dir.iterdir.return_value = iter([fake_dir])

            with patch.object(ProviderRegistry, "_load_plugin", side_effect=Exception("boom")):
                with patch.object(reg_mod._logger, "warning") as mock_warn:
                    with patch("dblift.db.provider_registry.Path") as mock_path:
                        mock_path_instance = MagicMock()
                        mock_path_instance.parent.__truediv__ = MagicMock(
                            return_value=mock_plugins_dir
                        )
                        mock_path.return_value = mock_path_instance

                        ProviderRegistry.discover_plugins()

            assert mock_warn.called, "_logger.warning should have been called"
            warn_msg = str(mock_warn.call_args)
            assert "Failed to load plugin" in warn_msg
            assert "boom" in warn_msg

        finally:
            ProviderRegistry._discovered = original_discovered
            ProviderRegistry._plugins = original_plugins
