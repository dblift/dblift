"""Version/edition-gated feature resolution.

:class:`~db.feature_gate.FeatureGate` declarations live on each plugin's
quirks class (``feature_gates`` ClassVar — plugins are the single source of
truth, ADR-0026). This module derives the lazy alias->gates registry from
the plugin registry (same shape as ``_CAPABILITIES`` in
:mod:`core.sql_model.dialect`, including the counter-based invalidation)
and exposes the tri-state resolver :func:`supports_feature`.

Resolver contract (the caller-facing semantics):

- ``True``  — the captured server provably supports the feature.
- ``False`` — the captured server provably does NOT support it.
- ``None``  — unknown: no gate declared for the (dialect, feature) pair, or
  the gate's constraints cannot be evaluated against the available server
  info. Callers keep their conservative fallback (typically a
  "verify your edition/version" caveat note).

``supports_feature`` never raises.
"""

from __future__ import annotations

import re
from typing import Any, Dict, FrozenSet, Mapping, Optional, Union

from core.sql_model.server_info import ServerInfo
from db.feature_gate import FeatureGate

#: Shared feature-name vocabulary. Names are cross-tier API: consumers key
#: on them, plugins declare gates under them. Adding a name is MINOR;
#: removing or renaming one is MAJOR. Values (thresholds, edition
#: patterns) stay plugin-owned — the same split as capability field names
#: vs. per-plugin capability values.
KNOWN_FEATURES: FrozenSet[str] = frozenset(
    {
        "online_index_build",
        "rename_column",
    }
)

_FEATURE_GATES: Dict[str, Dict[str, FeatureGate]] = {}
_feature_gates_seen: int = 0


def _ensure_feature_gates() -> None:
    """Populate ``_FEATURE_GATES`` from registered plugin quirks.

    Re-builds when the registry's expected (plugin, alias) pair count
    changes. Uses an integer counter — not ``len(_FEATURE_GATES)`` —
    because two plugins can legitimately share an alias (e.g. mysql and
    mariadb both publish ``"mariadb"`` while loading), causing dict
    deduplication that would otherwise pin the length below ``expected``
    and trigger an infinite rebuild loop. (PR #241 Bugbot; same idiom as
    ``core.sql_model.dialect._ensure_capabilities``.)
    """
    global _feature_gates_seen
    from db.provider_registry import ProviderRegistry

    ProviderRegistry.discover_plugins()
    expected = sum(len(p.dialects) for p in ProviderRegistry.list_plugins())
    if expected and _feature_gates_seen == expected:
        return
    _FEATURE_GATES.clear()
    _feature_gates_seen = 0
    for plugin_info in ProviderRegistry.list_plugins():
        quirks = ProviderRegistry.get_quirks(plugin_info.name)
        gates = dict(quirks.feature_gates)
        for alias in plugin_info.dialects:
            _feature_gates_seen += 1
            _FEATURE_GATES[alias.lower()] = gates


def get_feature_gates(dialect: Optional[str]) -> Mapping[str, FeatureGate]:
    """Return the declared gates for *dialect* (empty for unknown/None)."""
    if not dialect:
        return {}
    _ensure_feature_gates()
    return _FEATURE_GATES.get(dialect.strip().lower(), {})


def _combine(*constraints: Optional[bool]) -> Optional[bool]:
    """Conservative tri-state AND: any False -> False, else any None -> None."""
    result: Optional[bool] = True
    for constraint in constraints:
        if constraint is False:
            return False
        if constraint is None:
            result = None
    return result


def supports_feature(
    dialect: Optional[str],
    feature: str,
    server_info: Optional[Union[Mapping[str, Any], ServerInfo]] = None,
) -> Optional[bool]:
    """Tri-state: does *dialect*'s captured server support *feature*?

    ``server_info`` accepts either a parsed :class:`ServerInfo` or the raw
    snapshot mapping (``{"edition": ..., "version": ...}``). See the module
    docstring for the True/False/None contract. Never raises.
    """
    try:
        gate = get_feature_gates(dialect).get(feature)
        if gate is None:
            return None
        info = (
            server_info
            if isinstance(server_info, ServerInfo)
            else ServerInfo.from_mapping(dialect, server_info)
        )

        edition_ok: Optional[bool] = True
        if gate.edition_pattern is not None:
            if info.edition is None:
                edition_ok = None
            else:
                edition_ok = bool(re.search(gate.edition_pattern, info.edition, re.IGNORECASE))

        from core.introspection.version_detector import version_matches_spec

        min_version_ok: Optional[bool] = True
        if gate.min_version is not None:
            if info.version is None:
                min_version_ok = None
            else:
                min_version_ok = version_matches_spec(info.version, gate.min_version)

        removed_ok: Optional[bool] = True
        if gate.removed_in is not None:
            if info.version is None:
                removed_ok = None
            else:
                removed_ok = not version_matches_spec(info.version, gate.removed_in + "+")

        return _combine(edition_ok, min_version_ok, removed_ok)
    except Exception:
        return None


__all__ = [
    "FeatureGate",
    "KNOWN_FEATURES",
    "get_feature_gates",
    "supports_feature",
]
