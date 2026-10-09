"""Full metadata for the modern installed fixture."""

from dblift.db.plugins.sqlite.provider import SQLiteProvider
from dblift.db.provider_registry import PluginInfo

PLUGIN = PluginInfo(
    name="modern_fixture",
    version="1.0.0",
    description="Installed modern descriptor fixture",
    dialects=["modern_fixture", "modern_alias"],
    provider_class=SQLiteProvider,
)
