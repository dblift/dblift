"""Compatibility guards for provider contracts exposed to extensions."""

import pickle
from typing import get_type_hints
from unittest.mock import patch


def test_provider_metadata_keeps_resolvable_annotations_and_pickle_path():
    from dblift.extensions.providers import PluginInfo

    assert "provider_class" in get_type_hints(PluginInfo)

    plugin = PluginInfo("fixture", "1", "fixture", ["fixture"], dict)
    restored = pickle.loads(pickle.dumps(plugin))
    assert type(restored) is PluginInfo
    assert restored == plugin


def test_patching_original_registry_method_affects_extension_export():
    from dblift.db.provider_registry import ProviderRegistry as OriginalRegistry
    from dblift.extensions.providers import ProviderRegistry

    with patch.object(OriginalRegistry, "list_plugins", return_value=[]) as mocked:
        assert ProviderRegistry.list_plugins() == []
        mocked.assert_called_once_with()


def test_remaining_logging_and_sql_model_exports_keep_identity_and_pickle_paths():
    from dblift.core.logger import LogLevel as OriginalLogLevel
    from dblift.core.sql_model import SqlStatementType as OriginalStatementType
    from dblift.extensions.logging import LogLevel
    from dblift.extensions.sql_model import SqlStatementType

    assert LogLevel is OriginalLogLevel
    assert SqlStatementType is OriginalStatementType
    for value in (LogLevel.INFO, SqlStatementType.SELECT):
        assert pickle.loads(pickle.dumps(value)) is value
