"""Load ``dblift.features`` entry points (tier feature registration).

Each ``dblift.features`` entry point resolves to a no-arg callable that
performs registrations against the neutral seams
(:mod:`core.seams.runtime_checks`, :mod:`core.seams.tier_resolver`, ...).
OSS ships none; installed higher tiers register their runtime checks and
tier resolver here.

Loading is idempotent via a module-level once-flag: entry points do not
change at runtime, and both CLI startup and API-client construction invoke
:func:`load_feature_extensions`, so double-loading is expected and cheap.

``DBLIFT_DISABLE_CLI_EXTENSIONS=1`` skips feature loading entirely. This is
an accepted, explicit operator opt-out: with higher-tier packages installed
it also disables their registered runtime checks and tier resolution for
API usage in the same process.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable
from importlib.metadata import entry_points
from typing import Protocol

_log = logging.getLogger(__name__)

FEATURE_ENTRY_POINT_GROUP = "dblift.features"

# Feature registrations load in tier order (pro before enterprise, unknown
# third parties in between, name as the tie-breaker) — the same ordering
# contract as cli/extensions.py's command-extension loaders.
_TIER_LOAD_ORDER = {"pro": 0, "enterprise": 2}
_DEFAULT_TIER_LOAD_ORDER = 1

_features_loaded = False


class _FeatureEntryPoint(Protocol):
    name: str

    def load(self) -> Callable[[], object]:
        pass


def load_feature_extensions() -> None:
    """Load every ``dblift.features`` entry point (idempotent, best-effort)."""
    global _features_loaded
    if _features_loaded or os.environ.get("DBLIFT_DISABLE_CLI_EXTENSIONS") == "1":
        return
    discovered_by_name: dict[str, _FeatureEntryPoint] = {
        entry_point.name: entry_point
        for entry_point in entry_points(group=FEATURE_ENTRY_POINT_GROUP)
    }
    ordered = sorted(
        discovered_by_name.values(),
        key=lambda ep: (_TIER_LOAD_ORDER.get(ep.name, _DEFAULT_TIER_LOAD_ORDER), ep.name),
    )
    for entry_point in ordered:
        try:
            register = entry_point.load()
            register()
        except Exception as exc:  # a bad plugin must not break startup
            _log.warning("dblift.features '%s' failed to load: %s", entry_point.name, exc)
    _features_loaded = True
