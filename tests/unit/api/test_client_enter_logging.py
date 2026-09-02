"""Tests vérifiant que client.__enter__() logge l'exception is_connected()."""

from unittest.mock import MagicMock

import pytest

from dblift.db.provider_interfaces import ConnectionProvider


@pytest.mark.unit
class TestClientEnterLogging:
    """Vérifie que __enter__() logge les exceptions is_connected() avant reconnexion."""

    def test_is_connected_exception_is_logged_in_enter(self):
        """Exception de is_connected() dans __enter__ doit être loggée en debug (AC#2)."""
        from dblift.api.client import DBLiftClient

        provider = MagicMock(spec=ConnectionProvider)
        provider.is_connected.side_effect = OSError("socket error")

        logger = MagicMock()
        client = object.__new__(DBLiftClient)
        client.provider = provider
        client.logger = logger

        result = client.__enter__()

        debug_calls = [str(c) for c in logger.debug.call_args_list]
        assert any(
            "Could not check connection state in __enter__" in c for c in debug_calls
        ), f"Expected debug log for is_connected() exception, got: {debug_calls}"
        assert any(
            "socket error" in c for c in debug_calls
        ), f"Expected exception message in debug log, got: {debug_calls}"
        assert result is client

    def test_is_connected_exception_still_creates_connection_in_enter(self):
        """Après exception is_connected(), create_connection() doit être appelée."""
        from dblift.api.client import DBLiftClient

        provider = MagicMock(spec=ConnectionProvider)
        provider.is_connected.side_effect = OSError("socket error")

        client = object.__new__(DBLiftClient)
        client.provider = provider
        client.logger = MagicMock()

        client.__enter__()

        provider.create_connection.assert_called_once()
