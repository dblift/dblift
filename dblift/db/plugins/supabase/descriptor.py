"""Discovery metadata for the supabase provider."""

from dblift.db.provider_metadata import PluginDescriptor

DESCRIPTOR = PluginDescriptor(
    name="supabase",
    dialects=("supabase",),
    factory="dblift.db.plugins.supabase.plugin:PLUGIN",
)
