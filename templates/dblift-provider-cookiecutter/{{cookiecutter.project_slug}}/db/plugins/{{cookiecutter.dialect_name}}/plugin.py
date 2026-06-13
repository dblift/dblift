"""Entry-point declaration for the {{cookiecutter.dialect_name}} plugin.

The :class:`PluginInfo` constant exported by this module is registered
through the ``dblift.providers`` entry-point group in ``pyproject.toml``.
``ProviderRegistry.discover_plugins`` reads it via
``importlib.metadata.entry_points`` so first-party and third-party
plugins are discovered through the same mechanism.
"""

from __future__ import annotations

from db.plugins.{{cookiecutter.dialect_name}}.provider import {{cookiecutter.dialect_name.capitalize()}}Provider
from db.plugins.{{cookiecutter.dialect_name}}.quirks import {{cookiecutter.dialect_name.capitalize()}}Quirks
from db.plugins.{{cookiecutter.dialect_name}}.sqlalchemy_url import build_sqlalchemy_url
from db.provider_registry import PluginInfo

PLUGIN: PluginInfo = PluginInfo(
    name="{{cookiecutter.dialect_name}}",
    version="0.1.0",
    description="{{cookiecutter.description}}",
    dialects=["{{cookiecutter.dialect_name}}"],
    provider_class={{cookiecutter.dialect_name.capitalize()}}Provider,
    transport="native",
    quirks_class={{cookiecutter.dialect_name.capitalize()}}Quirks,
    sqlalchemy_url_builder=build_sqlalchemy_url,
)
