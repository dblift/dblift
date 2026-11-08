"""Operations without caller connections do not need a transaction guard lookup."""

import threading

from dblift.api.client import DBLiftClient, _with_client_emitter
from dblift.api.events import EventEmitter


class _DeferredProviderClient(DBLiftClient):
    @property
    def provider(self):
        raise AssertionError("operation resolved its deferred provider")

    @_with_client_emitter(mutating=False)
    def operation(self):
        assert self._thread_state.stack
        return "completed"


def test_operation_without_caller_connection_does_not_resolve_provider_for_guard():
    client = object.__new__(_DeferredProviderClient)
    client.events = EventEmitter()
    client._operation_lock = threading.RLock()
    client._thread_state = threading.local()
    client._thread_state.stack = []
    client._caller_transaction_provider = None

    assert client.operation() == "completed"
