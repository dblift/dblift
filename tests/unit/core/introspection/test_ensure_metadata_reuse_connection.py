"""OBS-01 regression: SchemaIntrospector reuses existing provider connection.

Before this fix, SchemaIntrospector._ensure_metadata() always called
provider.create_connection(), which on MySQL overwrites provider.connection
with a new connection, silently destroying the snapshot context and
leaving the function introspection query unable to execute on the right
session.  The fix checks for an existing connection first.
"""

from __future__ import annotations

from unittest.mock import MagicMock, PropertyMock

import pytest


def _make_provider(existing_connection=None):
    from db.provider_interfaces import ConnectionProvider

    provider = MagicMock(spec=ConnectionProvider)
    provider.connection = existing_connection
    new_conn = MagicMock()
    new_conn.getAutoCommit.return_value = True
    new_conn.getMetaData.return_value = MagicMock()
    provider.create_connection.return_value = new_conn
    return provider, new_conn


@pytest.mark.unit
class TestEnsureMetadataReuseConnection:
    def test_reuses_existing_provider_connection(self):
        from core.introspection.schema_introspector import SchemaIntrospector

        existing = MagicMock()
        existing.getAutoCommit.return_value = True
        existing.getMetaData.return_value = MagicMock()

        provider, _ = _make_provider(existing_connection=existing)

        si = SchemaIntrospector.__new__(SchemaIntrospector)
        si.provider = provider
        si.log = MagicMock()
        si.metadata = None
        si.connection = None

        si._ensure_metadata()

        provider.create_connection.assert_not_called()
        assert si.connection is existing

    def test_native_metadata_does_not_toggle_provider_autocommit(self):
        from core.introspection.schema_introspector import SchemaIntrospector

        existing = MagicMock()
        existing.getAutoCommit.return_value = False
        existing.getMetaData.return_value = MagicMock()

        provider, _ = _make_provider(existing_connection=existing)

        si = SchemaIntrospector.__new__(SchemaIntrospector)
        si.provider = provider
        si.log = MagicMock()
        si.metadata = None
        si.connection = None
        si._original_autocommit = None

        si._ensure_metadata()
        si.close()

        existing.rollback.assert_not_called()
        existing.setAutoCommit.assert_not_called()
        existing.close.assert_not_called()
        assert si.connection is None
        assert si.metadata is None

    def test_creates_connection_when_none_exists(self):
        from core.introspection.schema_introspector import SchemaIntrospector

        provider, new_conn = _make_provider(existing_connection=None)

        si = SchemaIntrospector.__new__(SchemaIntrospector)
        si.provider = provider
        si.log = MagicMock()
        si.metadata = None
        si.connection = None

        si._ensure_metadata()

        provider.create_connection.assert_called_once()
        assert si.connection is new_conn

    def test_skips_ensure_when_metadata_already_set(self):
        from core.introspection.schema_introspector import SchemaIntrospector

        provider, _ = _make_provider()
        existing_meta = MagicMock()

        si = SchemaIntrospector.__new__(SchemaIntrospector)
        si.provider = provider
        si.log = MagicMock()
        si.metadata = existing_meta
        si.connection = MagicMock()

        si._ensure_metadata()

        provider.create_connection.assert_not_called()
        assert si.metadata is existing_meta
