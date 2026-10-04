"""Installed test provider backed by the existing SQLite engine."""

from dblift.api.events import EventType
from dblift.db.plugins.sqlite.plugin import PLUGIN as SQLITE
from dblift.extensions.providers import PluginInfo

EVENTS = []

PLUGIN = PluginInfo(
    name="fixture_sqlite",
    version="0.0.1",
    description="Installed test provider",
    dialects=["fixture_sqlite"],
    provider_class=SQLITE.provider_class,
    transport=SQLITE.transport,
    quirks_class=SQLITE.quirks_class,
    config_dialect="sqlite",
    config_class=SQLITE.config_class,
    sqlalchemy_url_builder=SQLITE.sqlalchemy_url_builder,
)


def register(emitter):
    emitter.on(EventType.MIGRATION_COMPLETED, EVENTS.append)
    emitter.on(EventType.MIGRATION_FAILED, EVENTS.append)
