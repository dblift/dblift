"""Configuration dataclass for secrets providers."""

from dataclasses import dataclass
from typing import Any, Dict, Optional


@dataclass
class SecretsConfig:
    """Provider-level configuration for the secrets subsystem.

    Values are read from the ``secrets:`` block in dblift.yaml.
    Every field has a sensible default so the dataclass is usable
    with zero configuration (ambient credentials / env vars are
    sufficient for all cloud providers).
    """

    # HashiCorp Vault
    vault_url: Optional[str] = None
    vault_token: Optional[str] = None
    vault_namespace: Optional[str] = None

    # AWS (Secrets Manager + SSM share the same region)
    aws_region: Optional[str] = None

    # Azure Key Vault
    azure_vault_name: Optional[str] = None

    # GCP Secret Manager
    gcp_project_id: Optional[str] = None

    # Cache TTL for resolved secrets (seconds)
    cache_ttl_seconds: float = 60.0

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SecretsConfig":
        from config.secrets._registry import is_secret_uri

        def _literal(v: Any) -> Optional[str]:
            """Return v only when it is a plain string (not a secret URI).

            Provider config fields that are themselves secret URIs must be
            treated as absent here so that providers fall back to ambient
            credentials (env vars) during Phase-1 bootstrap resolution.
            The resolved values are populated after Phase 1 completes.
            """
            return v if isinstance(v, str) and not is_secret_uri(v) else None

        vault = data.get("vault") or {}
        aws = data.get("aws") or {}
        azure = data.get("azure") or {}
        gcp = data.get("gcp") or {}
        return cls(
            vault_url=_literal(vault.get("url")),
            vault_token=_literal(vault.get("token")),
            vault_namespace=_literal(vault.get("namespace")),
            aws_region=_literal(aws.get("region")),
            azure_vault_name=_literal(azure.get("vault_name")),
            gcp_project_id=_literal(gcp.get("project_id")),
            cache_ttl_seconds=float(data.get("cache_ttl_seconds", 60.0)),
        )
