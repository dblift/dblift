"""Build a ``DBLiftClient`` without connecting, for tests that stub its collaborators."""

from __future__ import annotations

import threading
from typing import Any

from dblift.api.client import DBLiftClient
from dblift.api.events import EventEmitter


def bare_client(**attributes: Any) -> DBLiftClient:
    """A ``DBLiftClient`` that skips ``__init__``'s connection and executor setup.

    It carries the state ``__init__`` always sets and every public operation
    needs (``dialect``, ``events``, the operation lock and the per-thread
    reentrancy state). *attributes* set or replace anything else, such as
    ``config``, ``provider`` and ``executor``.
    """
    client = DBLiftClient.__new__(DBLiftClient)
    client.dialect = "sqlite"
    client.events = EventEmitter()
    client._operation_lock = threading.RLock()
    client._thread_state = threading.local()
    for name, value in attributes.items():
        setattr(client, name, value)
    return client
