"""Secrets resolution stub for the public package.

Secret URI providers (vault://, aws-secrets://, azure-keyvault://, etc.) are
not bundled here. This stub keeps the config layer importable without external
secret-manager dependencies.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional


@dataclass
class SecretsConfig:
    """No-op secrets config for the public package."""

    vault: Optional[Any] = None
    aws: Optional[Any] = None
    azure: Optional[Any] = None
    gcp: Optional[Any] = None

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "SecretsConfig":
        return cls()


def resolve_secret_refs(data: Any, secrets_config: Optional[SecretsConfig] = None) -> Any:
    """Secret URI resolution is a no-op in this package; return data unchanged."""
    return data


__all__ = ["SecretsConfig", "resolve_secret_refs"]
