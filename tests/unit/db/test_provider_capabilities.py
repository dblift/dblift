"""Tests for optional provider capability helpers."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from db.provider_capabilities import (
    ensure_provider_connection,
    get_clean_preview,
    get_provider_display_url,
)


@pytest.mark.unit
def test_display_url_prefers_neutral_provider_method():
    provider = MagicMock()
    provider.get_display_url.return_value = "native://account"
    config = SimpleNamespace(database=SimpleNamespace(url="postgresql+psycopg://fallback/db"))

    assert get_provider_display_url(provider, config) == "native://account"


@pytest.mark.unit
def test_display_url_falls_back_to_config_without_jdbc_hook():
    provider = object()
    config = SimpleNamespace(database=SimpleNamespace(url="", account_endpoint="https://account/"))

    assert get_provider_display_url(provider, config) == "https://account/"


@pytest.mark.unit
def test_display_url_uses_connection_manager_get_database_url():
    """Providers without get_display_url can surface URL via connection_manager."""
    connection_manager = MagicMock()
    connection_manager.get_database_url.return_value = "postgresql://from-cm/db"
    provider = SimpleNamespace(connection_manager=connection_manager)
    # Prefer connection manager over config fallback.
    config = SimpleNamespace(database=SimpleNamespace(url="postgresql://config/db"))

    assert get_provider_display_url(provider, config) == "postgresql://from-cm/db"
    connection_manager.get_database_url.assert_called_once_with()


@pytest.mark.unit
def test_display_url_skips_empty_connection_manager_url():
    connection_manager = MagicMock()
    connection_manager.get_database_url.return_value = ""
    provider = SimpleNamespace(connection_manager=connection_manager)
    config = SimpleNamespace(database=SimpleNamespace(url="postgresql://config/db"))

    assert get_provider_display_url(provider, config) == "postgresql://config/db"


@pytest.mark.unit
def test_ensure_provider_connection_calls_optional_hook_only_when_present():
    provider = MagicMock()

    ensure_provider_connection(provider)

    provider._ensure_connection.assert_called_once_with()


@pytest.mark.unit
def test_clean_preview_returns_none_when_provider_has_no_preview_hook():
    assert get_clean_preview(object(), "schema") is None
