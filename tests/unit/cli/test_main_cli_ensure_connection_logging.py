"""Tests vérifiant que _ensure_connection() logge l'exception is_connected()."""

from unittest.mock import MagicMock

import pytest

from dblift.db.provider_interfaces import ConnectionProvider


@pytest.mark.unit
class TestEnsureConnectionLogging:
    """Vérifie que _ensure_connection() logge les exceptions is_connected()."""

    def _make_client(self, provider):
        client = MagicMock()
        client.provider = provider
        return client

    def test_is_connected_exception_is_logged(self):
        """Exception de is_connected() doit être loggée en debug (AC#1)."""
        from dblift.cli.main import _ensure_connection

        provider = MagicMock(spec=ConnectionProvider)
        provider.is_connected.side_effect = RuntimeError("connection lost")
        client = self._make_client(provider)
        log = MagicMock()

        _ensure_connection(client, log, "migrate")

        debug_calls = [str(c) for c in log.debug.call_args_list]
        assert any(
            "Could not check connection state before command migrate" in c for c in debug_calls
        ), f"Expected debug log for is_connected() exception, got: {debug_calls}"
        assert any(
            "connection lost" in c for c in debug_calls
        ), f"Expected exception message in debug log, got: {debug_calls}"

    def test_is_connected_exception_still_attempts_connection(self):
        """Après exception is_connected(), la connexion doit être tentée (comportement inchangé)."""
        from dblift.cli.main import _ensure_connection

        provider = MagicMock(spec=ConnectionProvider)
        provider.is_connected.side_effect = RuntimeError("connection lost")
        provider.ensure_connection = MagicMock()
        client = self._make_client(provider)
        log = MagicMock()

        _ensure_connection(client, log, "migrate")

        provider.ensure_connection.assert_called_once()

    def test_is_connected_success_no_exception_log(self):
        """Si is_connected() réussit, pas de log d'exception (régression)."""
        from dblift.cli.main import _ensure_connection

        provider = MagicMock(spec=ConnectionProvider)
        provider.is_connected.return_value = True
        client = self._make_client(provider)
        log = MagicMock()

        _ensure_connection(client, log, "migrate")

        debug_calls = [str(c) for c in log.debug.call_args_list]
        assert not any("Could not check connection state" in c for c in debug_calls)
