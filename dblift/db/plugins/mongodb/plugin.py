"""Entry-point declaration for the MongoDB plugin."""

from __future__ import annotations

from dblift.db.plugins.mongodb.config import MongoDbConfig
from dblift.db.plugins.mongodb.provider import MongoDbProvider
from dblift.db.plugins.mongodb.quirks import MongodbQuirks
from dblift.db.provider_registry import PluginInfo

PLUGIN: PluginInfo = PluginInfo(
    name="mongodb",
    version="1.0.0",
    description="MongoDB provider",
    dialects=["mongodb", "mongo"],
    provider_class=MongoDbProvider,
    transport="native",
    quirks_class=MongodbQuirks,
    config_class=MongoDbConfig,
    # ``pymongo`` is what ``mongodb/_sdk.py`` and ``connection_manager.py``
    # import, so its absence is what makes the plugin unusable; ``mongodb``
    # is the pyproject extra that installs it.
    native_driver_module="pymongo",
    install_extra="mongodb",
)
