"""Tests for the secret-refs resolver (traversal + dispatch)."""

from typing import Any
from unittest.mock import MagicMock

import pytest

pytestmark = [pytest.mark.unit]

from config.secrets._provider_base import AbstractSecretsProvider, SecretsResolutionError
from config.secrets._registry import _providers, register
from config.secrets._resolver import clear_cache, resolve_secret_refs
from config.secrets._secrets_config import SecretsConfig


class _StubProvider(AbstractSecretsProvider):
    scheme = "stub"

    def __init__(self, config: SecretsConfig | None = None) -> None:
        self._available = True
        self._values: dict[str, str] = {}

    def set_value(self, uri: str, value: str) -> None:
        self._values[uri] = value

    def resolve(self, uri: str) -> str:
        if uri not in self._values:
            raise SecretsResolutionError(f"stub: no value for {uri}")
        return self._values[uri]

    def is_available(self) -> bool:
        return self._available


@pytest.fixture(autouse=True)
def _register_stub_and_clean_cache() -> Any:
    """Register stub provider for all resolver tests; clear cache before each."""
    register("stub", _StubProvider)
    clear_cache()
    yield
    _providers.pop("stub", None)
    clear_cache()


class TestResolveSecretRefsTraversal:
    def test_plain_string_unchanged(self) -> None:
        result = resolve_secret_refs("plaintext")
        assert result == "plaintext"

    def test_non_secret_string_unchanged(self) -> None:
        result = resolve_secret_refs("postgresql+psycopg://localhost/db")
        assert result == "postgresql+psycopg://localhost/db"

    def test_none_unchanged(self) -> None:
        assert resolve_secret_refs(None) is None

    def test_integer_unchanged(self) -> None:
        assert resolve_secret_refs(42) == 42

    def test_list_traversed(self) -> None:
        result = resolve_secret_refs(["plain", 99])
        assert result == ["plain", 99]

    def test_dict_traversed(self) -> None:
        result = resolve_secret_refs({"key": "plain", "num": 1})
        assert result == {"key": "plain", "num": 1}

    def test_nested_dict_traversed(self) -> None:
        data = {"database": {"host": "localhost", "password": "plain"}}
        result = resolve_secret_refs(data)
        assert result == {"database": {"host": "localhost", "password": "plain"}}

    def test_secret_uri_in_dict_value_is_resolved(self) -> None:
        provider = _StubProvider()
        provider.set_value("stub://myapp/db#password", "resolved-password")
        _providers["stub"] = provider

        data = {"database": {"password": "stub://myapp/db#password"}}
        result = resolve_secret_refs(data)
        assert result["database"]["password"] == "resolved-password"

    def test_secret_uri_in_list_is_resolved(self) -> None:
        provider = _StubProvider()
        provider.set_value("stub://x#y", "val")
        _providers["stub"] = provider

        result = resolve_secret_refs(["stub://x#y", "plain"])
        assert result == ["val", "plain"]

    def test_only_secret_uris_are_resolved(self) -> None:
        provider = _StubProvider()
        provider.set_value("stub://x#y", "val")
        _providers["stub"] = provider

        data = {"a": "stub://x#y", "b": "not-a-secret", "c": 123}
        result = resolve_secret_refs(data)
        assert result["a"] == "val"
        assert result["b"] == "not-a-secret"
        assert result["c"] == 123


class TestResolveSecretRefsCaching:
    def test_same_uri_resolved_once(self) -> None:
        mock_provider = MagicMock(spec=AbstractSecretsProvider)
        mock_provider.scheme = "stub"
        mock_provider.is_available.return_value = True
        mock_provider.resolve.return_value = "cached-value"
        _providers["stub"] = mock_provider

        resolve_secret_refs("stub://x#y")
        resolve_secret_refs("stub://x#y")

        mock_provider.resolve.assert_called_once_with("stub://x#y")

    def test_clear_cache_forces_re_resolve(self) -> None:
        mock_provider = MagicMock(spec=AbstractSecretsProvider)
        mock_provider.scheme = "stub"
        mock_provider.is_available.return_value = True
        mock_provider.resolve.return_value = "value"
        _providers["stub"] = mock_provider

        resolve_secret_refs("stub://x#y")
        clear_cache()
        resolve_secret_refs("stub://x#y")

        assert mock_provider.resolve.call_count == 2

    def test_mock_config_does_not_poison_cache_ttl(self) -> None:
        mock_provider = MagicMock(spec=AbstractSecretsProvider)
        mock_provider.scheme = "stub"
        mock_provider.is_available.return_value = True
        mock_provider.resolve.return_value = "value"
        _providers["stub"] = mock_provider

        mock_config = MagicMock()
        mock_config.cache_ttl_seconds = MagicMock()

        resolve_secret_refs("stub://x#y", mock_config)
        resolve_secret_refs("stub://x#y", mock_config)

        mock_provider.resolve.assert_called_once_with("stub://x#y")


class TestResolveSecretRefsErrors:
    def test_unknown_scheme_passes_through(self) -> None:
        # Unregistered schemes are not treated as secret URIs — returned unchanged.
        result = resolve_secret_refs("no-such-scheme://path#field")
        assert result == "no-such-scheme://path#field"

    def test_unavailable_provider_raises(self) -> None:
        unavailable = _StubProvider()
        unavailable._available = False
        _providers["stub"] = unavailable

        with pytest.raises(SecretsResolutionError, match="not available"):
            resolve_secret_refs("stub://path#field")

    def test_provider_resolve_error_propagates(self) -> None:
        provider = _StubProvider()  # no values set → will raise
        _providers["stub"] = provider

        with pytest.raises(SecretsResolutionError):
            resolve_secret_refs("stub://missing#field")
