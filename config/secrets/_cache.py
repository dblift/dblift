"""In-process TTL cache for resolved secret values."""

import time
from dataclasses import dataclass
from typing import Dict, Optional


@dataclass
class _CacheEntry:
    value: str
    expires_at: float


class SecretsCache:
    """Thread-unsafe in-process cache — sufficient for a single-threaded CLI."""

    def __init__(self, ttl_seconds: float = 60.0) -> None:
        self._ttl = ttl_seconds
        self._store: Dict[str, _CacheEntry] = {}

    def get(self, key: str) -> Optional[str]:
        entry = self._store.get(key)
        if entry is None:
            return None
        if time.monotonic() >= entry.expires_at:
            del self._store[key]
            return None
        return entry.value

    def set(self, key: str, value: str) -> None:
        self._store[key] = _CacheEntry(value=value, expires_at=time.monotonic() + self._ttl)

    def clear(self) -> None:
        self._store.clear()

    def size(self) -> int:
        return len(self._store)
