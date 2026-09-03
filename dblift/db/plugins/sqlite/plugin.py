"""Entry-point declaration for the SQLite plugin (Epic 26 story 26-12)."""

from __future__ import annotations

from dblift.db.plugins.sqlite.config import SQLiteConfig
from dblift.db.plugins.sqlite.provider import SQLiteProvider
from dblift.db.plugins.sqlite.quirks import SqliteQuirks
from dblift.db.plugins.sqlite.sqlalchemy_url import build_sqlalchemy_url
from dblift.db.provider_registry import PluginInfo

PLUGIN: PluginInfo = PluginInfo(
    name="sqlite",
    version="1.0.0",
    description="SQLite database provider (native Python sqlite3)",
    dialects=["sqlite", "sqlite3"],
    provider_class=SQLiteProvider,
    transport="native",
    quirks_class=SqliteQuirks,
    config_class=SQLiteConfig,
    sqlalchemy_url_builder=build_sqlalchemy_url,
)
