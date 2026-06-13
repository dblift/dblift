"""Tests for the secrets provider registry."""

import pytest

pytestmark = [pytest.mark.unit]

from config.secrets._provider_base import AbstractSecretsProvider, SecretsResolutionError
from config.secrets._registry import (
    KNOWN_SCHEMES,
    _providers,
    get_provider_class,
    is_secret_uri,
    register,
    register_provider,
)
from config.secrets._secrets_config import SecretsConfig


class _FakeProvider(AbstractSecretsProvider):
    scheme = "fake-test"

    def resolve(self, uri: str) -> str:
        return "resolved"

    def is_available(self) -> bool:
        return True


class TestKnownSchemes:
    def test_all_expected_schemes_present(self) -> None:
        assert "vault" in KNOWN_SCHEMES
        assert "aws-secrets" in KNOWN_SCHEMES
        assert "aws-ssm" in KNOWN_SCHEMES
        assert "azure-keyvault" in KNOWN_SCHEMES
        assert "gcp-secrets" in KNOWN_SCHEMES


class TestIsSecretUri:
    @pytest.mark.parametrize(
        "uri",
        [
            "vault://secret/data/prod/db#password",
            "aws-secrets://prod/myapp#password",
            "aws-ssm:///prod/db/password",
            "azure-keyvault://myvault.vault.azure.net/secrets/db-pass",
            "gcp-secrets://projects/proj/secrets/db/versions/latest",
        ],
    )
    def test_known_scheme_is_secret_uri(self, uri: str) -> None:
        assert is_secret_uri(uri) is True

    @pytest.mark.parametrize(
        "value",
        [
            "supersecret",
            "postgresql+psycopg://localhost:5432/db",
            "${DB_PASSWORD}",
            "",
            "http://example.com",
            "unknown://some/path",
        ],
    )
    def test_non_secret_values_are_not_secret_uri(self, value: str) -> None:
        assert is_secret_uri(value) is False


class TestRegisterAndGet:
    def test_register_then_get_returns_class(self) -> None:
        register("fake-test", _FakeProvider)
        assert get_provider_class("fake-test") is _FakeProvider
        # cleanup
        _providers.pop("fake-test", None)

    def test_get_unknown_scheme_returns_none(self) -> None:
        assert get_provider_class("nonexistent-scheme") is None

    def test_register_provider_registers_valid_class(self) -> None:
        register_provider("custom-vault", _FakeProvider)
        assert get_provider_class("custom-vault") is _FakeProvider
        _providers.pop("custom-vault", None)

    def test_register_provider_is_detectable_as_secret_uri(self) -> None:
        register_provider("custom-vault", _FakeProvider)
        assert is_secret_uri("custom-vault://my/secret") is True
        _providers.pop("custom-vault", None)

    def test_register_provider_rejects_empty_scheme(self) -> None:
        with pytest.raises(ValueError, match="non-empty"):
            register_provider("", _FakeProvider)

    def test_register_provider_rejects_scheme_with_double_slash(self) -> None:
        with pytest.raises(ValueError, match="://"):
            register_provider("bad://scheme", _FakeProvider)

    def test_register_provider_rejects_non_provider_class(self) -> None:
        class NotAProvider:
            pass

        with pytest.raises(TypeError, match="AbstractSecretsProvider"):
            register_provider("bad-provider", NotAProvider)  # type: ignore[arg-type]

    def test_register_provider_rejects_instance_not_class(self) -> None:
        with pytest.raises(TypeError, match="AbstractSecretsProvider"):
            register_provider("bad-provider", _FakeProvider())  # type: ignore[arg-type]

    def test_register_provider_rejects_incomplete_abstract_class(self) -> None:
        class IncompleteProvider(AbstractSecretsProvider):
            scheme = "incomplete"
            # Missing: resolve() and is_available()

        with pytest.raises(TypeError, match="abstract methods"):
            register_provider("incomplete", IncompleteProvider)  # type: ignore[arg-type]

    def test_register_overwrites_existing(self) -> None:
        class _FakeV2(AbstractSecretsProvider):
            scheme = "fake-test-v2"

            def resolve(self, uri: str) -> str:
                return "v2"

            def is_available(self) -> bool:
                return True

        register("fake-test-v2", _FakeV2)
        register("fake-test-v2", _FakeProvider)
        assert get_provider_class("fake-test-v2") is _FakeProvider
        _providers.pop("fake-test-v2", None)
