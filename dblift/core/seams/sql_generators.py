"""Neutral seam for higher-tier SQL generator registration."""

from __future__ import annotations

import logging
from collections.abc import Callable

from dblift.core.seams.feature_loading import load_feature_extensions

_log = logging.getLogger(__name__)
_registrars: list[Callable[[], None]] = []
_bootstrapped = False


def register_sql_generator_registrar(registrar: Callable[[], None]) -> None:
    """Register a higher-tier SQL generator registrar exactly once."""
    if registrar not in _registrars:
        _registrars.append(registrar)


def attach_registered_sql_generators() -> None:
    """Run every registered SQL generator registrar."""
    global _bootstrapped
    if not _bootstrapped and not _registrars:
        load_feature_extensions()
        # Latch only if load_feature_extensions() actually populated
        # _registrars -- same latch bug as AlterGeneratorFactory._ensure_populated
        # and feature_loading.load_feature_extensions: an empty result can be
        # the documented race (a paid package's entry point not yet visible),
        # so it must not be latched permanently and must retry on a later call.
        _bootstrapped = bool(_registrars)

    for registrar in _registrars:
        try:
            registrar()
        except Exception as exc:  # pragma: no cover - defensive fallback logging
            _log.warning("SQL generator registrar failed: %s", exc)


def clear_sql_generator_registrars() -> None:
    """Test hook."""
    global _bootstrapped
    from dblift.core.seams import feature_loading

    _registrars.clear()
    _bootstrapped = False
    feature_loading._features_loaded = False
