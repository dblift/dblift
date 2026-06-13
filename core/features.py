"""Neutral feature metadata shared by OSS core and installed extensions."""

from dataclasses import dataclass
from enum import Enum
from typing import Set


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


def is_feature_available(feature: Feature, granted_features: Set[str]) -> bool:
    """Return whether a feature is available for the granted entitlements."""
    if feature.tier is FeatureTier.OSS:
        return True
    return feature.name in granted_features
