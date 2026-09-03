"""MongoDB plugin registration and dialect resolution."""

from dblift.db.plugins.mongodb.config import MongoDbConfig
from dblift.db.plugins.mongodb.plugin import PLUGIN
from dblift.db.plugins.mongodb.provider import MongoDbProvider
from dblift.db.plugins.mongodb.quirks import MongodbQuirks
from dblift.db.provider_registry import ProviderRegistry


def test_plugin_metadata():
    assert PLUGIN.name == "mongodb"
    assert PLUGIN.transport == "native"
    assert PLUGIN.provider_class is MongoDbProvider
    assert PLUGIN.quirks_class is MongodbQuirks
    assert PLUGIN.config_class is MongoDbConfig


def test_dialect_aliases():
    assert PLUGIN.dialects == ["mongodb", "mongo"]


def test_driver_and_extra_point_at_pymongo():
    """The named module is what makes the plugin unusable when absent, and
    the extra is what installs it."""
    assert PLUGIN.native_driver_module == "pymongo"
    assert PLUGIN.install_extra == "mongodb"


def test_registry_resolves_the_canonical_name():
    ProviderRegistry.discover_plugins()
    assert ProviderRegistry.canonical_dialect_name("mongodb") == "mongodb"


def test_registry_resolves_the_alias():
    ProviderRegistry.discover_plugins()
    assert ProviderRegistry.canonical_dialect_name("mongo") == "mongodb"


def test_registry_returns_the_quirks():
    ProviderRegistry.discover_plugins()
    assert isinstance(ProviderRegistry.get_quirks("mongodb"), MongodbQuirks)
