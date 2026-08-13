"""Load ``dblift.features`` entry points (tier feature registration).

Each ``dblift.features`` entry point resolves to a no-arg callable that
performs registrations against the neutral seams
(:mod:`core.seams.runtime_checks`, :mod:`core.seams.tier_resolver`, ...).
OSS ships none; installed higher tiers register their runtime checks and
tier resolver here.

Loading is idempotent via a module-level once-flag: entry points do not
change at runtime, and both CLI startup and API-client construction invoke
:func:`load_feature_extensions`, so double-loading is expected and cheap. An
empty entry-point result latches immediately unless a known tier
distribution (``dblift-pro``/``dblift-enterprise``) is installed but its
entry point hasn't reached this process's metadata view yet, in which case
it is retried on a later call instead of latched.

``DBLIFT_DISABLE_CLI_EXTENSIONS=1`` skips feature loading entirely. This is
an accepted, explicit operator opt-out: with higher-tier packages installed
it also disables their registered runtime checks and tier resolution for
API usage in the same process.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable
from importlib.metadata import PackageNotFoundError, entry_points, version
from typing import Protocol

_log = logging.getLogger(__name__)

FEATURE_ENTRY_POINT_GROUP = "dblift.features"

# Feature registrations load in tier order (pro before enterprise, unknown
# third parties in between, name as the tie-breaker) — the same ordering
# contract as cli/extensions.py's command-extension loaders.
_TIER_LOAD_ORDER = {"pro": 0, "enterprise": 2}
_DEFAULT_TIER_LOAD_ORDER = 1

_features_loaded = False

# Must be updated if a tier package's distribution name changes, or a new
# tier is added under a different name -- an unlisted distribution is
# indistinguishable here from "not installed", so
# _any_tier_distribution_installed silently reverts to the pre-fix
# never-retries behavior for it.
_KNOWN_TIER_DISTRIBUTIONS = ("dblift-pro", "dblift-enterprise")


def _any_tier_distribution_installed() -> bool:
    """Whether a known paid-tier package is installed as a distribution.

    Checked independently of whether its ``dblift.features`` entry point has
    become visible yet in this process's ``importlib.metadata`` view -- this
    is what distinguishes "no dblift.features entry point will ever exist"
    (pure OSS, no tier package installed at all -- the ordinary case) from
    "one exists but hasn't reached this process's view of the metadata yet"
    (the documented race an empty ``entry_points()`` result alone can't
    rule out).
    """
    for name in _KNOWN_TIER_DISTRIBUTIONS:
        try:
            version(name)
        except PackageNotFoundError:
            continue
        except Exception as exc:  # a broken distribution must not break startup
            _log.warning("Could not check whether %r is installed: %s", name, exc)
            continue
        return True
    return False


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
    # Latch when something was actually found, OR when nothing was found but
    # no tier package is installed at all -- an empty result is only the
    # documented race (a paid package's dblift.features entry point not yet
    # reaching this process's importlib.metadata view, needing a retry on a
    # later call, exactly like the identical latch bug fixed in
    # AlterGeneratorFactory._ensure_populated) when a tier distribution is
    # actually installed. In pure OSS, with no tier package installed,
    # OSS's own pyproject.toml declares the entry-points group empty, so an
    # empty result is permanent and must latch immediately.
    _features_loaded = bool(ordered) or not _any_tier_distribution_installed()
