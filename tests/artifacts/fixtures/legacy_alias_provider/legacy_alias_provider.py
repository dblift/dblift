"""Legacy provider whose dialect alias differs from its entry-point name."""

from dblift.db.plugins.sqlite.provider import SQLiteProvider
from dblift.db.provider_registry import PluginInfo

PLUGIN = PluginInfo(
    name="legacy_fixture",
    version="1.0.0",
    description="Installed legacy alias fixture",
    dialects=["legacy_fixture", "legacy_alias"],
    provider_class=SQLiteProvider,
)
