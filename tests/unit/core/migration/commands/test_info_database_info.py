"""``info`` gets its database info from the preflight, not from a second read.

The preflight (``BaseCommand._populate_database_info``) only asks a provider for
its version when the provider is a ``SchemaProvider``. ``info`` used to repeat
the read for any provider exposing ``get_database_version``. The two agree only
while no provider has that method without being a ``SchemaProvider``.
"""

from importlib.metadata import entry_points

import pytest

from dblift.api import DBLiftClient
from dblift.config import DbliftConfig
from dblift.db.provider_interfaces import SchemaProvider
from dblift.db.provider_registry import ProviderRegistry

pytestmark = pytest.mark.unit

_PLUGIN_NAMES = sorted(
    entry.name for entry in entry_points(group=ProviderRegistry.ENTRY_POINT_GROUP)
)


def test_registry_lists_the_declared_plugins():
    """The parametrised guard below must not run over an empty list."""
    assert _PLUGIN_NAMES, "no dblift.providers entry points are installed in this environment"


@pytest.mark.parametrize("plugin_name", _PLUGIN_NAMES)
def test_every_provider_with_database_version_is_a_schema_provider(plugin_name):
    provider_class = ProviderRegistry.get_provider_class(plugin_name)
    if provider_class is None:
        pytest.skip(f"plugin {plugin_name!r} could not be loaded in this environment")

    if hasattr(provider_class, "get_database_version"):
        assert issubclass(
            provider_class, SchemaProvider
        ), f"{provider_class.__name__} has get_database_version but is not a SchemaProvider"


def test_info_reports_database_info_on_sqlite(tmp_path):
    scripts = tmp_path / "migrations"
    scripts.mkdir()
    (scripts / "V1__create_items.sql").write_text("CREATE TABLE items (id INTEGER);")
    config = DbliftConfig.from_dict(
        {
            "database": {"type": "sqlite", "url": f"sqlite:///{tmp_path / 'info.db'}"},
            "migrations": {"directory": str(scripts)},
        }
    )

    with DBLiftClient.from_config(config) as client:
        result = client.info()

    assert result.success, result.error_message
    assert result.db_version
    assert result.database_url_masked
    assert result.native_driver
