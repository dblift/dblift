"""Tests for DIP-01: BaseCommand provider type hint → BaseProvider (story 24-5).

Verifies that base_command.py and all child commands use BaseProvider
instead of JdbcProvider in their type hints and imports.
"""

import inspect

import pytest

from core.migration.commands.base_command import BaseCommand

pytestmark = [pytest.mark.unit]

_COMMAND_MODULES = [
    "core.migration.commands.base_command",
    "core.migration.commands.info_command",
    "core.migration.commands.baseline_command",
    "core.migration.commands.repair_command",
    "core.migration.commands.clean_command",
    "core.migration.commands.migrate_command",
    "core.migration.commands.undo_command",
    "core.migration.commands.validate_command",
    "core.migration.commands.diff_command",
]

# Commands that directly reference BaseProvider in their own source (not just
# inherited from BaseCommand). Leaf commands that only extend BaseCommand without
# re-declaring the provider parameter do not need the import.
_MODULES_WITH_BASE_PROVIDER_IMPORT = [
    "core.migration.commands.base_command",
    "core.migration.commands.migrate_command",
    "core.migration.commands.diff_command",
]


class TestNoJdbcProviderImport:
    """No command module should import JdbcProvider."""

    @pytest.mark.parametrize(
        "module_path", _COMMAND_MODULES, ids=[m.split(".")[-1] for m in _COMMAND_MODULES]
    )
    def test_no_jdbc_provider_import(self, module_path):
        import importlib

        mod = importlib.import_module(module_path)
        source = inspect.getsource(mod)
        assert (
            "from db.jdbc_provider import JdbcProvider" not in source
        ), f"{module_path} still imports JdbcProvider"

    @pytest.mark.parametrize(
        "module_path",
        _MODULES_WITH_BASE_PROVIDER_IMPORT,
        ids=[m.split(".")[-1] for m in _MODULES_WITH_BASE_PROVIDER_IMPORT],
    )
    def test_imports_base_provider(self, module_path):
        import importlib

        mod = importlib.import_module(module_path)
        source = inspect.getsource(mod)
        assert (
            "from db.base_provider import BaseProvider" in source
        ), f"{module_path} does not import BaseProvider"


class TestBaseCommandProviderTypeHint:
    """BaseCommand.__init__ must type-hint provider as BaseProvider."""

    def test_provider_param_is_base_provider(self):
        source = inspect.getsource(BaseCommand.__init__)
        # Accept both `provider: BaseProvider` and `provider: Optional[BaseProvider]`
        assert "provider: BaseProvider" in source or "provider: Optional[BaseProvider]" in source
        assert "provider: JdbcProvider" not in source
