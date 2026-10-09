"""Stateless discovery helpers; provider state and alias precedence stay in the registry."""

import importlib
import logging
from importlib import metadata
from pathlib import Path
from typing import Any, Iterator, Optional, TypeGuard

from dblift.db.provider_metadata import PluginDescriptor

_logger = logging.getLogger(__name__)


def _valid_descriptor(descriptor: Any) -> TypeGuard[PluginDescriptor]:
    return (
        isinstance(descriptor, PluginDescriptor)
        and isinstance(descriptor.name, str)
        and bool(descriptor.name)
        and isinstance(descriptor.dialects, tuple)
        and all(isinstance(alias, str) and alias for alias in descriptor.dialects)
        and isinstance(descriptor.factory, str)
        and ":" in descriptor.factory
    )


def _same_distribution(first: Any, second: Any) -> bool:
    a, b = getattr(first, "dist", None), getattr(second, "dist", None)
    if a is None or b is None:
        return False
    if a is b:
        return True
    first_path, second_path = getattr(a, "_path", None), getattr(b, "_path", None)
    return bool(
        first_path is not None
        and second_path is not None
        and Path(first_path).resolve() == Path(second_path).resolve()
    )


def _load_descriptor(ep: Any) -> Optional[PluginDescriptor]:
    try:
        descriptor = ep.load()
        if _valid_descriptor(descriptor):
            return descriptor
        _logger.warning(f"Invalid provider descriptor entry-point {ep.name!r}; ignoring.")
    except Exception as exc:
        _logger.warning(f"Failed to load provider descriptor {ep.name!r}: {exc}")
    return None


def entry_point_candidates(legacy_group: str, descriptor_group: str) -> Iterator[Any]:
    """Yield valid legacy plugins or descriptors in historical entry-point order."""
    from dblift.db.provider_registry import PluginInfo

    try:
        legacy = list(metadata.entry_points(group=legacy_group))
        descriptors = list(metadata.entry_points(group=descriptor_group))
    except Exception as exc:  # pragma: no cover - defensive
        _logger.warning(f"Failed to read entry-points for {legacy_group}: {exc}")
        return

    paired = set()
    for ep in legacy:
        descriptor = None
        for candidate in descriptors:
            if candidate.name != ep.name or not _same_distribution(ep, candidate):
                continue
            loaded = _load_descriptor(candidate)
            if loaded and loaded.name == ep.name and loaded.factory == ep.value:
                descriptor = loaded
                paired.add(id(candidate))
                break
        if descriptor is not None:
            yield descriptor
            continue
        try:
            plugin = ep.load()
        except Exception as exc:
            _logger.warning(f"Failed to load plugin entry-point {ep.name!r}: {exc}")
            continue
        if isinstance(plugin, PluginInfo):
            yield plugin
        else:
            _logger.warning(
                f"Entry-point {ep.name!r} returned {type(plugin).__name__}, "
                "expected PluginInfo; ignoring."
            )

    for ep in descriptors:
        if id(ep) not in paired:
            descriptor = _load_descriptor(ep)
            if descriptor is not None:
                yield descriptor


def filesystem_descriptor(plugin_dir: Path) -> Optional[PluginDescriptor]:
    """Read only a bundled descriptor, leaving the full provider unopened."""
    if not (plugin_dir / "descriptor.py").exists():
        return None
    try:
        descriptor = importlib.import_module(
            f"dblift.db.plugins.{plugin_dir.name}.descriptor"
        ).DESCRIPTOR
        if _valid_descriptor(descriptor):
            return descriptor
        _logger.warning(f"Invalid provider descriptor from {plugin_dir}; ignoring.")
    except Exception as exc:
        _logger.warning(f"Failed to load descriptor from {plugin_dir}: {exc}")
    return None


def load_factory(descriptor: PluginDescriptor, legacy_group: str) -> Any:
    """Resolve the legacy factory reference with standard entry-point semantics."""
    return metadata.EntryPoint(
        name=descriptor.name,
        value=descriptor.factory,
        group=legacy_group,
    ).load()
