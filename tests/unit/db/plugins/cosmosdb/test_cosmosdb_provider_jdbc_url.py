"""NOTE-02 regression: CosmosDbProvider.get_database_url() delegates to connection manager.

Before this fix, ``CosmosDbProvider`` had no ``get_database_url()`` method.  The
``check-connection`` command fell back to ``config.database.url``, which is
empty for CosmosDB (it uses ``account_endpoint`` instead), so the displayed URL
was blank.

The fix adds ``get_database_url()`` on the provider, delegating to
``connection_manager.get_database_url()`` — consistent with how SQL providers
(SQL Server, MySQL, DB2) expose their display URL.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest


@pytest.mark.unit
class TestCosmosDbProviderGetJdbcUrl:
    def _make_provider(self, connection_url: str):
        from dblift.db.plugins.cosmosdb.provider import CosmosDbProvider

        provider = CosmosDbProvider.__new__(CosmosDbProvider)
        provider.log = MagicMock()
        provider.connection_manager = MagicMock()
        provider.connection_manager.get_database_url.return_value = connection_url
        provider.connection_manager.get_database_url.return_value = connection_url
        return provider

    def test_delegates_to_connection_manager(self):
        """get_database_url() returns whatever the connection manager provides."""
        provider = self._make_provider("AccountEndpoint=https://mydb.documents.azure.com:443/")
        url = provider.get_database_url()
        assert url == "AccountEndpoint=https://mydb.documents.azure.com:443/"
        provider.connection_manager.get_database_url.assert_called_once()

    def test_none_from_connection_manager_returns_empty_string(self):
        """A None from connection_manager converts to '' — no AttributeError downstream."""
        provider = self._make_provider(None)
        assert provider.get_database_url() == ""

    def test_method_exists_on_provider(self):
        """Provider exposes get_database_url so check-connection can call it directly."""
        provider = self._make_provider("https://localhost:8081/")
        assert hasattr(provider, "get_database_url")
        assert callable(provider.get_database_url)

    def test_display_url_uses_neutral_connection_url_method(self):
        provider = self._make_provider("https://localhost:8081/")

        assert provider.get_display_url() == "https://localhost:8081/"
        provider.connection_manager.get_database_url.assert_called_once_with()
