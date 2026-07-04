"""Entry-point declaration for the DuckDB plugin."""

from __future__ import annotations

from db.plugins.duckdb.config import DuckDBConfig
from db.plugins.duckdb.provider import DuckDBProvider
from db.plugins.duckdb.quirks import DuckDBQuirks
from db.plugins.duckdb.sqlalchemy_url import build_sqlalchemy_url
from db.provider_registry import PluginInfo

PLUGIN: PluginInfo = PluginInfo(
    name="duckdb",
    version="1.0.0",
    description="DuckDB database provider (SQLAlchemy via duckdb_engine)",
    dialects=["duckdb"],
    provider_class=DuckDBProvider,
    transport="native",
    quirks_class=DuckDBQuirks,
    config_class=DuckDBConfig,
    sqlalchemy_url_builder=build_sqlalchemy_url,
    native_driver_module="duckdb",
)
