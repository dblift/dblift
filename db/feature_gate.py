"""Version/edition feature-gate value type.

A :class:`FeatureGate` describes when one named feature is available on one
dialect, as a function of the *server* the migration targets (its version
and/or edition) rather than the dialect alone — the complement of the
boolean capability flags on :class:`db.base_quirks.BaseQuirks`.

Gates are declared per-dialect on each plugin's quirks class
(``feature_gates: ClassVar[Dict[str, FeatureGate]]``) so plugins stay the
single source of truth (ADR-0026), and resolved through
:func:`core.sql_model.feature_gates.supports_feature`. This module is a
stdlib-only leaf so ``db.base_quirks`` can import it without cycles.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class FeatureGate:
    """A version/edition gate for one named feature on one dialect.

    Every constraint field is optional; a gate with no constraints means
    the feature is unconditionally supported. Constraints combine
    conservatively in the resolver: any failed constraint denies the
    feature, and a constraint that cannot be evaluated (missing or
    unparseable server info) yields "unknown" rather than a guess.
    """

    #: Minimum server version spec, e.g. ``"8.0+"`` (see
    #: :func:`core.introspection.version_detector.version_matches_spec`).
    min_version: Optional[str] = None
    #: Version (exclusive upper bound) in which the feature was removed.
    removed_in: Optional[str] = None
    #: Case-insensitive regex fragment matched against the captured server
    #: edition string, e.g. ``r"enterprise|developer|evaluation|azure"``.
    edition_pattern: Optional[str] = None
    #: Operator-facing one-liner naming the gated feature.
    description: str = ""


__all__ = ["FeatureGate"]
