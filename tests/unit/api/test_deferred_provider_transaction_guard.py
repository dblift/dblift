"""The transaction guard reads the provider inside the public operation context."""

import threading

from dblift.api.client import DBLiftClient, _with_client_emitter
from dblift.api.events import EventEmitter


class _DeferredProviderClient(DBLiftClient):
    @property
    def provider(self):
        if not self._thread_state.stack:
            raise AssertionError("provider resolved before the operation context was set")
        return self._provider

    @provider.setter
    def provider(self, value):
        self._provider = value

    @_with_client_emitter
    def operation(self):
        return "completed"


def test_provider_is_resolved_after_operation_context_is_set():
    client = object.__new__(_DeferredProviderClient)
    client.events = EventEmitter()
    client._operation_lock = threading.RLock()
    client._thread_state = threading.local()
    client._thread_state.stack = []
    client._provider = object()

    assert client.operation() == "completed"
