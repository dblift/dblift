"""Base types for secrets providers."""

from abc import ABC, abstractmethod
from typing import Optional

from config.secrets._secrets_config import SecretsConfig


class SecretsResolutionError(Exception):
    """Raised when a secret URI cannot be resolved."""


class AbstractSecretsProvider(ABC):
    """Abstract base class for all secrets providers."""

    scheme: str

    def __init__(self, config: Optional[SecretsConfig] = None) -> None:
        self._config = config or SecretsConfig()

    @abstractmethod
    def resolve(self, uri: str) -> str:
        """Resolve a secret URI to its plaintext value."""

    @abstractmethod
    def is_available(self) -> bool:
        """Return True if the provider is configured and its SDK is importable."""
