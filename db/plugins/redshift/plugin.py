"""Entry-point declaration for the Redshift plugin.

Redshift is PostgreSQL-wire-compatible, but it needs the Redshift SQLAlchemy
dialect/driver instead of the standard PostgreSQL dialect because Redshift does
not implement every PostgreSQL connection bootstrap query.
"""

from __future__ import annotations

from db.plugins.redshift.provider import RedshiftProvider
from db.plugins.redshift.quirks import RedshiftQuirks
from db.plugins.redshift.sqlalchemy_url import build_sqlalchemy_url
from db.provider_registry import PluginInfo

PLUGIN: PluginInfo = PluginInfo(
    name="redshift",
    version="1.0.0",
    description="Redshift database provider",
    dialects=["redshift"],
    provider_class=RedshiftProvider,
    transport="native",
    quirks_class=RedshiftQuirks,
    config_dialect="postgresql",
    sqlalchemy_url_builder=build_sqlalchemy_url,
    native_driver_module="redshift_connector",
)
