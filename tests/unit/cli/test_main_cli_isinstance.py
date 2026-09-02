"""Story 16-12 — structural tests: hasattr replaced by isinstance in _ensure_connection."""

import inspect

import pytest


@pytest.mark.unit
class TestMainCliIsinstance:
    """Verify hasattr replaced by isinstance(ConnectionProvider) in _ensure_connection."""

    def test_ensure_connection_no_hasattr_is_connected(self):
        """AC#6.1 — hasattr('is_connected') removed from _ensure_connection."""
        import dblift.cli.main as main_mod

        source = inspect.getsource(main_mod._ensure_connection)
        assert (
            'hasattr(client.provider, "is_connected")' not in source
        ), "hasattr(client.provider, 'is_connected') still present in _ensure_connection"

    def test_ensure_connection_no_hasattr_create_connection(self):
        """AC#6.1b — hasattr('create_connection') removed from _ensure_connection."""
        import dblift.cli.main as main_mod

        source = inspect.getsource(main_mod._ensure_connection)
        assert (
            'hasattr(client.provider, "create_connection")' not in source
        ), "hasattr(client.provider, 'create_connection') still present in _ensure_connection"

    def test_ensure_connection_uses_isinstance_connection_provider(self):
        """AC#6.2 — isinstance(ConnectionProvider) used in _ensure_connection."""
        import dblift.cli.main as main_mod

        source = inspect.getsource(main_mod._ensure_connection)
        assert "isinstance" in source, "_ensure_connection does not use isinstance"
        assert (
            "ConnectionProvider" in source
        ), "_ensure_connection does not reference ConnectionProvider"
