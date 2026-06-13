"""Unit tests for base extractor connection handling."""

from unittest.mock import MagicMock

import pytest

from core.introspection.extractors.base_extractor import BaseExtractor

pytestmark = [pytest.mark.unit]


def test_ensure_metadata_reuses_open_provider_connection():
    existing = MagicMock()
    existing.closed = False
    provider = MagicMock()
    provider.connection = existing

    extractor = BaseExtractor(provider=provider)

    extractor.ensure_metadata()

    provider.create_connection.assert_not_called()
    assert extractor.connection is existing


def test_ensure_metadata_creates_connection_without_declared_provider_connection():
    provider = MagicMock()
    new_connection = MagicMock()
    provider.create_connection.return_value = new_connection

    extractor = BaseExtractor(provider=provider)

    extractor.ensure_metadata()

    provider.create_connection.assert_called_once_with()
    assert extractor.connection is new_connection
