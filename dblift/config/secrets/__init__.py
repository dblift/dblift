"""OSS secrets: environment-variable resolution and the custom-provider
registration seam. No built-in external vault providers ship in OSS."""

from dblift.config.secrets._provider_base import AbstractSecretsProvider, SecretsResolutionError
from dblift.config.secrets._registry import register_provider
from dblift.config.secrets._resolver import clear_cache, resolve_secret_refs
from dblift.config.secrets._secrets_config import SecretsConfig

__all__ = [
    "resolve_secret_refs",
    "clear_cache",
    "SecretsResolutionError",
    "SecretsConfig",
    "AbstractSecretsProvider",
    "register_provider",
]
