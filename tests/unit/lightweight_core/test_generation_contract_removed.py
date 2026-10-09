"""The OSS extension boundary excludes retired SQL-generation contracts."""

import importlib.util

import pytest

from dblift.core.dialect_boundary import DdlQuirks
from dblift.db.base_quirks import BaseQuirks
from dblift.db.provider_registry import ProviderRegistry


@pytest.mark.parametrize(
    "module",
    [
        "dblift.core.state.sql_statement",
        "dblift.db.generator_protocol",
        "dblift.extensions.sql_generation",
    ],
)
def test_generation_only_modules_are_absent(module):
    try:
        spec = importlib.util.find_spec(module)
    except ModuleNotFoundError as error:
        # The core.state parent package may itself disappear in a clean wheel.
        assert module.startswith(f"{error.name}.")
    else:
        assert spec is None


def test_extension_categories_exclude_sql_generation():
    import dblift.extensions as extensions

    assert extensions.__all__ == ["lint", "logging", "providers", "sql_model"]
    assert "sql_generation" not in dir(extensions)
    with pytest.raises(AttributeError):
        extensions.sql_generation


@pytest.mark.parametrize(
    "dialect",
    [
        None,
        *(
            plugin.name
            for plugin in ProviderRegistry.list_plugins()
            if plugin.quirks_class
            and plugin.quirks_class.__module__.startswith("dblift.db.plugins.")
        ),
    ],
)
def test_bundled_quirks_exclude_generation_hooks(dialect):
    quirks = BaseQuirks() if dialect is None else ProviderRegistry.get_quirks(dialect)
    assert not hasattr(quirks, "ddl_generator_class")
    assert not hasattr(quirks, "alter_generator_class")
    assert isinstance(quirks, DdlQuirks)


def test_ddl_quirks_protocol_only_requires_remaining_fields():
    class MinimalDdlQuirks:
        non_transactional_sql_patterns = ()
        native_driver_display = ""
        requires_credentials = False
        url_optional_when_file_path_given = False

    assert isinstance(MinimalDdlQuirks(), DdlQuirks)
