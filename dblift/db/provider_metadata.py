"""Lightweight metadata for discovering database provider plugins."""

from dataclasses import dataclass


@dataclass(frozen=True)
class PluginDescriptor:
    """Provider identity and the import reference for its full plugin."""

    name: str
    dialects: tuple[str, ...]
    factory: str
