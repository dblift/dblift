"""Feature tier definitions, registry, and gate helpers."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Set


class FeatureTier(str, Enum):
    """Distribution tier that owns a DBLift feature."""

    OSS = "oss"
    PRO = "pro"
    ENTERPRISE = "enterprise"


@dataclass(frozen=True)
class Feature:
    """Neutral feature descriptor shared across packaging boundaries."""

    name: str
    tier: FeatureTier
    description: str = field(default="", compare=False, hash=False)


_TIER_ORDER: List[FeatureTier] = [FeatureTier.OSS, FeatureTier.PRO, FeatureTier.ENTERPRISE]


def is_feature_available(feature: Feature, granted_features: Set[str]) -> bool:
    """Return whether a feature is available for the granted entitlements."""
    if feature.tier is FeatureTier.OSS:
        return True
    return feature.name in granted_features


def meets_tier(license_tier: FeatureTier, required_tier: FeatureTier) -> bool:
    """Return True if license_tier satisfies required_tier."""
    return _TIER_ORDER.index(license_tier) >= _TIER_ORDER.index(required_tier)


class FeatureNotAvailableError(Exception):
    """Raised when a feature requires a higher license tier."""

    def __init__(  # lint: allow-missing-docstring: parameters self-document the error
        self, feature: Feature, license_tier: FeatureTier
    ) -> None:
        self.feature = feature
        self.license_tier = license_tier
        tier_label = license_tier.value.upper()
        required_label = feature.tier.value.upper()
        label = feature.description or f"'{feature.name}'"
        super().__init__(
            f"{label.capitalize()} requires a {required_label} license "
            f"(current: {tier_label}). "
            f"Upgrade at https://dblift.com/upgrade"
        )


def require_tier(feature: Feature, license_tier: FeatureTier) -> None:
    """Raise FeatureNotAvailableError if license_tier is insufficient."""
    if not meets_tier(license_tier, feature.tier):
        raise FeatureNotAvailableError(feature, license_tier)


# ── Feature registry ────────────────────────────────────────────────────────

DIFF_DB_STORED = Feature(
    name="diff.db_stored",
    tier=FeatureTier.PRO,
    description="diff against the database-stored snapshot",
)
DIFF_FILE_MODEL = Feature(
    name="diff.file_model",
    tier=FeatureTier.ENTERPRISE,
    description="diff against an external snapshot file (--snapshot-model)",
)

EXPORT_SCHEMA = Feature(
    name="export_schema",
    tier=FeatureTier.PRO,
    description="export-schema command",
)

SNAPSHOT_EXPORT = Feature(
    name="snapshot.export",
    tier=FeatureTier.ENTERPRISE,
    description="snapshot export to file",
)

VALIDATE_SQL_SECURITY = Feature(
    name="validate_sql.security",
    tier=FeatureTier.PRO,
    description="SQL validation command",
)
VALIDATE_SQL_FULL = Feature(
    name="validate_sql.full_packs",
    tier=FeatureTier.ENTERPRISE,
    description="SQL validation with advanced rule packs and profiles",
)

PLAN = Feature(
    name="plan",
    tier=FeatureTier.ENTERPRISE,
    description="offline migration plan command",
)
PREFLIGHT = Feature(
    name="preflight",
    tier=FeatureTier.ENTERPRISE,
    description="preflight deployment check command",
)

DATA = Feature(
    name="data",
    tier=FeatureTier.PRO,
    description="data command (plan/apply/status for audited corrections)",
)

DATA_UNDO = Feature(
    name="data.undo",
    tier=FeatureTier.ENTERPRISE,
    description="data undo command",
)
