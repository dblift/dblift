"""Structural tests for native connection setup in SchemaIntrospector."""

import inspect
from types import SimpleNamespace

import pytest


@pytest.mark.unit
class TestSchemaIntrospectorIsinstance:
    """Verify provider connection setup stays on the typed native path."""

    def test_ensure_metadata_no_hasattr_get_connection(self):
        """AC#5.1 — hasattr('get_connection'/'create_connection') removed from _ensure_metadata."""
        from core.introspection.schema_introspector import SchemaIntrospector

        source = inspect.getsource(SchemaIntrospector._ensure_metadata)
        assert (
            'hasattr(self.provider, "get_connection")' not in source
        ), "hasattr(self.provider, 'get_connection') still present in _ensure_metadata"
        assert (
            'hasattr(self.provider, "create_connection")' not in source
        ), "hasattr(self.provider, 'create_connection') still present in _ensure_metadata"

    def test_ensure_metadata_delegates_to_native_connection_helper(self):
        """_ensure_metadata delegates native connection setup to one helper."""
        from core.introspection.schema_introspector import SchemaIntrospector

        source = inspect.getsource(SchemaIntrospector._ensure_metadata)
        assert "_ensure_native_connection()" in source

    def test_ensure_metadata_raises_attribute_error_for_non_connection_provider(self):
        """L1 fix — else branch raises AttributeError for provider not implementing ConnectionProvider."""
        from core.introspection.schema_introspector import SchemaIntrospector

        class NotAProvider:
            config = SimpleNamespace(database=SimpleNamespace(type="postgresql"))

        introspector = SchemaIntrospector(
            provider=NotAProvider(), log=None, use_vendor_queries=False
        )
        with pytest.raises(AttributeError, match="ConnectionProvider interface"):
            introspector._ensure_metadata()
