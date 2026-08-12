"""Tests for config._credential_masking and BaseDatabaseConfig.to_safe_dict.

``to_safe_dict`` feeds ``__repr__``, so anything it fails to mask reaches
tracebacks, log lines and debugger output in clear text.
"""

import pytest

from config._credential_masking import mask_credentials, mask_url_credentials
from config._subclasses.dummy_config import DummyDatabaseConfig


@pytest.mark.unit
class TestMaskUrlCredentials:
    """URL masking must cover the same surface as core.utils.url_masking."""

    def test_masks_authority_password(self):
        masked = mask_url_credentials("postgresql://admin:secret@host:5432/db")
        assert "secret" not in masked
        assert "admin" in masked

    def test_masks_scheme_less_authority(self):
        """A ``//user:pass@host`` form with no scheme must still be masked."""
        masked = mask_url_credentials("//admin:secret@host:5432/db")
        assert "secret" not in masked

    def test_masks_password_param(self):
        masked = mask_url_credentials("server=host;password=secret123;database=db")
        assert "secret123" not in masked

    def test_masks_pwd_param(self):
        """``pwd=`` is an alias for ``password=`` in ODBC/DB2 strings."""
        masked = mask_url_credentials("server=host;pwd=secret123;database=db")
        assert "secret123" not in masked

    def test_masks_cosmosdb_account_key(self):
        conn = "AccountEndpoint=https://acct.documents.azure.com/;AccountKey=abc123secret;"
        masked = mask_url_credentials(conn)
        assert "abc123secret" not in masked

    def test_url_without_credentials_unchanged(self):
        url = "postgresql://localhost/db?user=admin"
        assert mask_url_credentials(url) == url


@pytest.mark.unit
class TestToSafeDict:
    """``repr(config)`` must never expose a credential."""

    def test_masks_password_field(self):
        cfg = DummyDatabaseConfig(type="dummy", url="dummy://host/db", password="secret123")
        assert cfg.to_safe_dict()["password"] != "secret123"
        assert "secret123" not in repr(cfg)

    def test_masks_pwd_in_url(self):
        cfg = DummyDatabaseConfig(type="dummy", url="dummy://host/db;pwd=secret123")
        assert "secret123" not in cfg.to_safe_dict()["url"]
        assert "secret123" not in repr(cfg)

    def test_masks_cosmos_account_key_in_url(self):
        cfg = DummyDatabaseConfig(
            type="dummy",
            url="AccountEndpoint=https://acct.documents.azure.com/;AccountKey=abc123secret;",
        )
        assert "abc123secret" not in cfg.to_safe_dict()["url"]
        assert "abc123secret" not in repr(cfg)

    def test_masks_sensitive_top_level_key_on_a_real_dialect_config(self):
        """A dialect that adds its own credential field must be masked too.

        ``CosmosDbConfig.to_dict`` injects ``account_key`` at the top level, not
        inside ``extra_params``, so masking only the known ``password`` field
        left it in clear text in every ``repr``.
        """
        from db.plugins.cosmosdb.config import CosmosDbConfig

        cfg = CosmosDbConfig(
            type="cosmosdb",
            account_endpoint="https://acct.documents.azure.com/",
            account_key="abc123secret",
            database_name="db",
        )

        assert cfg.to_safe_dict()["account_key"] != "abc123secret"
        assert "abc123secret" not in repr(cfg)

    def test_masking_preserves_non_sensitive_values(self):
        """Masking must not flatten the dict-valued fields it walks into."""
        cfg = DummyDatabaseConfig(
            type="dummy",
            url="dummy://host/db",
            extra_params={"api_key": "secret123", "sslmode": "require"},
        )
        safe = cfg.to_safe_dict()

        assert safe["extra_params"]["sslmode"] == "require"
        assert safe["type"] == "dummy"
        assert safe["connection_timeout"] == 30

    def test_every_registered_config_has_a_masked_repr(self):
        """No registered dialect config may re-generate a plain dataclass repr.

        ``BaseDatabaseConfig`` defines a credential-masked ``__repr__``, but a
        subclass decorated with a bare ``@dataclass`` silently replaces it and
        prints the password in clear. Guard the whole registry so a new plugin
        cannot reintroduce that.
        """
        from config.database_config import BaseDatabaseConfig
        from db.provider_registry import ProviderRegistry

        ProviderRegistry.discover_plugins()  # populate the config registry

        assert BaseDatabaseConfig._registry, "no dialect configs registered"
        for config_class in BaseDatabaseConfig._registry.values():
            assert "__repr__" not in vars(config_class), (
                f"{config_class.__name__} defines its own __repr__ "
                "(bare @dataclass?) and bypasses credential masking; "
                "use @dataclass(repr=False)"
            )

    def test_masks_sensitive_extra_params(self):
        cfg = DummyDatabaseConfig(
            type="dummy",
            url="dummy://host/db",
            extra_params={"api_key": "secret123", "sslmode": "require"},
        )
        safe = cfg.to_safe_dict()
        assert safe["extra_params"]["api_key"] != "secret123"
        assert safe["extra_params"]["sslmode"] == "require"


@pytest.mark.unit
class TestMaskCredentialsUrlShapedKeys:
    """A connection string can be exposed under names other than ``url``.

    ``mask_credentials`` must treat every URL-shaped key the same way, not
    just the literal ``url`` field — otherwise a dialect whose ``to_dict``
    exposes the connection string as ``uri``/``dsn``/``connection_string``
    leaks its password into ``repr()``.
    """

    def test_masks_uri_key(self):
        result = mask_credentials({"uri": "mongodb://admin:secret@host:27017/db"})
        assert "secret" not in result["uri"]
        assert "admin" in result["uri"]

    def test_masks_dsn_key(self):
        result = mask_credentials({"dsn": "postgresql://admin:secret@host:5432/db"})
        assert "secret" not in result["dsn"]
        assert "admin" in result["dsn"]

    def test_masks_connection_string_key(self):
        result = mask_credentials(
            {"connection_string": "server=host;password=secret123;database=db"}
        )
        assert "secret123" not in result["connection_string"]

    def test_url_key_behavior_unchanged(self):
        result = mask_credentials({"url": "postgresql://admin:secret@host:5432/db"})
        assert "secret" not in result["url"]
        assert "admin" in result["url"]

    def test_clean_url_shaped_value_is_byte_identical(self):
        """Masking must not rewrite a URL-shaped value that has no credentials."""
        clean = "mongodb://localhost:27017/db"
        result = mask_credentials({"uri": clean})
        assert result["uri"] == clean

    def test_non_url_key_is_not_run_through_url_masking(self):
        """A key that isn't URL-shaped (and isn't sensitive-named) must pass
        through untouched, even if its value looks like a connection string."""
        value = "connect via user:secret@host if needed"
        result = mask_credentials({"description": value})
        assert result["description"] == value
