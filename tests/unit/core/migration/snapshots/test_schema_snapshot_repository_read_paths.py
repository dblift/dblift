"""Read-path tests for ``SchemaSnapshotRepository``.

Regression coverage for BUG-06 (ADR-0012-class bug report): the CosmosDB
snapshot command hung indefinitely when the backing container did not
exist yet — the SDK's ``query_items`` iterator never raised and the
process never returned. The root cause was that ``get_latest_snapshot``
(and its siblings) issued the SELECT query unconditionally; the fix
short-circuits to ``None``/``[]`` when the snapshot table/container
does not exist.

These tests use an in-memory fake provider so they run in any
environment (no Docker, no Cosmos SDK, no JDBC).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import pytest

from core.migration.snapshots.schema_snapshot import (
    SNAPSHOT_TABLE_NAME,
    SchemaSnapshot,
    SchemaSnapshotPayload,
    encode_payload,
)
from core.migration.snapshots.schema_snapshot_repository import SchemaSnapshotRepository


class _FakeDbConfig:
    def __init__(self, dialect: str = "postgresql") -> None:
        self.type = dialect


class _FakeConfig:
    def __init__(self, dialect: str = "postgresql") -> None:
        self.database = _FakeDbConfig(dialect)
        self.snapshot_table = SNAPSHOT_TABLE_NAME


class _FakeProvider:
    """Minimal BaseProvider stand-in — pinned surface for this test only."""

    def __init__(self, *, table_exists: bool, dialect: str = "postgresql") -> None:
        self.config = _FakeConfig(dialect)
        self._table_exists = table_exists
        self.execute_query_calls: List[str] = []
        self.query_result: List[Dict[str, Any]] = []

    def get_normalized_object_name(self, object_name: str) -> str:
        return object_name

    def _ensure_connection(self) -> None:  # noqa: D401
        """No-op — the fake provider is always "connected"."""
        return None

    def table_exists(self, schema: str, table_name: str) -> bool:
        return self._table_exists

    def get_schema_qualified_name(self, schema: str, object_name: str) -> str:
        return f"{schema}.{object_name}"

    def create_snapshot_table_if_not_exists(self, schema: str, table_name: str) -> None:
        # A real provider would create the table; the fake flips its flag so
        # subsequent ``table_exists`` calls see it.
        self._table_exists = True

    def execute_query(self, sql: str, params: Optional[List[Any]] = None) -> List[Dict[str, Any]]:
        self.execute_query_calls.append(sql)
        return list(self.query_result)


@pytest.fixture
def repo_factory():
    def _factory(*, table_exists: bool) -> tuple[SchemaSnapshotRepository, _FakeProvider]:
        provider = _FakeProvider(table_exists=table_exists)
        repo = SchemaSnapshotRepository(provider=provider, schema="public")
        return repo, provider

    return _factory


@pytest.mark.unit
class TestReadPathWithoutSnapshotTable:
    """BUG-06 regression: read methods must not query a missing table.

    Before the fix, ``get_latest_snapshot`` / ``get_snapshot_by_id`` /
    ``list_snapshots`` called ``ensure_table()`` (which creates on
    write-capable paths) then unconditionally issued the SELECT. On
    CosmosDB, the SDK's ``query_items`` on a fresh/missing container
    could hang forever. On any other dialect the unconditional call
    is simply wasteful — reading has no business mutating state.
    """

    def test_get_latest_snapshot_returns_none_when_missing(self, repo_factory):
        repo, provider = repo_factory(table_exists=False)
        assert repo.get_latest_snapshot() is None
        assert provider.execute_query_calls == []

    def test_get_snapshot_by_id_returns_none_when_missing(self, repo_factory):
        repo, provider = repo_factory(table_exists=False)
        assert repo.get_snapshot_by_id("any-id") is None
        assert provider.execute_query_calls == []

    def test_list_snapshots_returns_empty_when_missing(self, repo_factory):
        repo, provider = repo_factory(table_exists=False)
        assert repo.list_snapshots() == []
        assert provider.execute_query_calls == []


@pytest.mark.unit
class TestReadPathWithExistingTable:
    """Sanity: when the table exists the read methods still work."""

    @staticmethod
    def _stub_row() -> Dict[str, Any]:
        payload = SchemaSnapshotPayload(metadata={"snapshot": {}})
        return {
            "snapshot_id": "snap-123",
            "captured_at": "2026-04-20T00:00:00+00:00",
            "checksum": "deadbeef",
            "model_data": encode_payload(payload),
        }

    def test_get_latest_snapshot_returns_hit(self, repo_factory):
        repo, provider = repo_factory(table_exists=True)
        provider.query_result = [self._stub_row()]
        snapshot = repo.get_latest_snapshot()
        assert isinstance(snapshot, SchemaSnapshot)
        assert snapshot.snapshot_id == "snap-123"
        assert len(provider.execute_query_calls) == 1

    def test_get_latest_snapshot_returns_none_on_empty_result(self, repo_factory):
        repo, provider = repo_factory(table_exists=True)
        provider.query_result = []
        assert repo.get_latest_snapshot() is None
        assert len(provider.execute_query_calls) == 1


@pytest.mark.unit
class TestInfrastructureErrorsPropagate:
    """BUG-06 fix must not mask real connection / auth / timeout errors.

    ``_snapshot_table_exists`` must NOT catch arbitrary exceptions from
    ``provider.table_exists`` — silently returning False would convert
    a network blip into "no snapshot available" and callers like
    ``diff_command`` / ``export_schema_command`` / ``snapshot_command``
    would continue without a baseline instead of surfacing an
    actionable error.
    """

    class _BoomProvider(_FakeProvider):
        def __init__(self, exc: Exception) -> None:
            super().__init__(table_exists=True)
            self._exc = exc

        def table_exists(self, schema: str, table_name: str) -> bool:
            raise self._exc

    @pytest.mark.parametrize(
        "exc",
        [
            ConnectionError("connection refused"),
            TimeoutError("deadline exceeded"),
            RuntimeError("401 unauthorised"),
        ],
        ids=lambda e: type(e).__name__,
    )
    def test_get_latest_snapshot_propagates(self, exc):
        provider = self._BoomProvider(exc)
        repo = SchemaSnapshotRepository(provider=provider, schema="public")
        with pytest.raises(type(exc)):
            repo.get_latest_snapshot()

    def test_list_snapshots_propagates(self):
        provider = self._BoomProvider(ConnectionError("connection refused"))
        repo = SchemaSnapshotRepository(provider=provider, schema="public")
        with pytest.raises(ConnectionError):
            repo.list_snapshots()

    def test_get_snapshot_by_id_propagates(self):
        provider = self._BoomProvider(TimeoutError("deadline exceeded"))
        repo = SchemaSnapshotRepository(provider=provider, schema="public")
        with pytest.raises(TimeoutError):
            repo.get_snapshot_by_id("snap-x")
