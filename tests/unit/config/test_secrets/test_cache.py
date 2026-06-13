"""Tests for SecretsCache TTL behaviour."""

import time

import pytest

pytestmark = [pytest.mark.unit]

from config.secrets._cache import SecretsCache


class TestSecretsCache:
    def test_miss_returns_none(self) -> None:
        cache = SecretsCache()
        assert cache.get("vault://x#y") is None

    def test_set_then_get_returns_value(self) -> None:
        cache = SecretsCache()
        cache.set("vault://x#y", "secret-value")
        assert cache.get("vault://x#y") == "secret-value"

    def test_expired_entry_returns_none(self) -> None:
        cache = SecretsCache(ttl_seconds=0.01)
        cache.set("vault://x#y", "secret-value")
        time.sleep(0.05)
        assert cache.get("vault://x#y") is None

    def test_expired_entry_is_evicted(self) -> None:
        cache = SecretsCache(ttl_seconds=0.01)
        cache.set("vault://x#y", "v")
        time.sleep(0.05)
        cache.get("vault://x#y")  # triggers eviction
        assert cache.size() == 0

    def test_clear_removes_all_entries(self) -> None:
        cache = SecretsCache()
        cache.set("a", "1")
        cache.set("b", "2")
        cache.clear()
        assert cache.size() == 0
        assert cache.get("a") is None

    def test_different_keys_are_independent(self) -> None:
        cache = SecretsCache()
        cache.set("vault://a#f", "val-a")
        cache.set("vault://b#f", "val-b")
        assert cache.get("vault://a#f") == "val-a"
        assert cache.get("vault://b#f") == "val-b"

    def test_overwrite_updates_value(self) -> None:
        cache = SecretsCache()
        cache.set("vault://x#y", "old")
        cache.set("vault://x#y", "new")
        assert cache.get("vault://x#y") == "new"
