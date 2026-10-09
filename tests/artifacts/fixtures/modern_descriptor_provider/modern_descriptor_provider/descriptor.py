"""Metadata for the modern installed fixture."""

from dblift.db.provider_metadata import PluginDescriptor

DESCRIPTOR = PluginDescriptor(
    name="modern_fixture",
    dialects=("modern_fixture", "modern_alias"),
    factory="modern_descriptor_provider.plugin:PLUGIN",
)
