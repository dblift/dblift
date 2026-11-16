"""Tests for provider_registry module-level logging (Story 16-8)."""

import inspect

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
