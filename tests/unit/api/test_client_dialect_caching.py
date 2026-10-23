"""Tests for dialect caching and normalization (story 18-13).

Validates that dialect is normalized to lowercase and cached at initialization
in DBLiftClient, JdbcProvider, and SqlGeneratorFactory.
"""

from unittest.mock import MagicMock, patch

import pytest

# ── AC#1 — DBLiftClient.dialect cached at __init__ ──────────────────────


@pytest.mark.unit
class TestClientDialectCaching:
    """Tests for DBLiftClient dialect caching (AC#1)."""

    def _make_client(self, provider_dialect="postgresql"):
        """Create a DBLiftClient with a mocked provider."""
        from dblift.api.client import DBLiftClient

        provider = MagicMock()
        provider.dialect = provider_dialect
        provider.config = None

        config = MagicMock()
        config.migrations.directory = "/tmp/migrations"
        config.migrations.directories = []

        logger = MagicMock()
        client = DBLiftClient(
            provider=provider,
            migrations_dir="/tmp/migrations",
            config=config,
            logger=logger,
        )
        return client

    def test_dialect_cached_at_init(self):
        """client.dialect is defined after __init__."""
        client = self._make_client()
        assert hasattr(client, "dialect")
        assert isinstance(client.dialect, str)

    def test_dialect_normalized_to_lowercase(self):
        """provider.dialect = 'PostgreSQL' → client.dialect == 'postgresql'."""
        client = self._make_client(provider_dialect="PostgreSQL")
        assert client.dialect == "postgresql"

    def test_get_dialect_called_once_not_on_method_call(self):
        """_get_dialect_for_sql_generation called 1x at init, not when accessing self.dialect."""
        from dblift.api.client import DBLiftClient

        provider = MagicMock()
        provider.dialect = "postgresql"
        provider.config = None

        config = MagicMock()
        config.migrations.directory = "/tmp/migrations"
        config.migrations.directories = []

        logger = MagicMock()

        with patch.object(
            DBLiftClient, "_get_dialect_for_sql_generation", return_value="postgresql"
        ) as mock_get:
            client = DBLiftClient(
                provider=provider,
                migrations_dir="/tmp/migrations",
                config=config,
                logger=logger,
            )
            assert mock_get.call_count == 1

            # Accessing self.dialect should NOT trigger another call
            assert client.dialect == "postgresql"
            assert mock_get.call_count == 1


# ── AC#2 — BaseProvider canonical dialect key fallback ───────────────────


@pytest.mark.unit
class TestBaseProviderDialect:
    """Tests for native provider dialect metadata (AC#2)."""

    def test_default_canonical_dialect_key_is_empty(self):
        from dblift.db.base_provider import BaseProvider

        assert BaseProvider.canonical_dialect_key == ""

    def test_postgresql_provider_declares_canonical_dialect_key(self):
        from dblift.db.plugins.postgresql.provider import PostgreSqlProvider

        assert PostgreSqlProvider.canonical_dialect_key == "postgresql"


# ── AC#3 — SqlGeneratorFactory case-insensitive ──────────────────────────
