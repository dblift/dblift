"""generate_undo_scripts() (batch) always emitted a batch-level
``MIGRATION_COMPLETED`` event after processing all items, even when every
item in the batch failed (``success=False``). The per-item results and the
``success_count``/``failure_count`` payload fields were computed correctly —
only the batch-level terminal event type was wrong.

Mirrors the fix already applied to ``DBLiftClient.undo()`` (see
``test_undo_events.py``): a batch-level failure must be signaled with the
failure event, not the completed event, so listeners can't mistake an
all-failed run for success.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from api._client_operations import generate_undo_scripts_operation
from api.events import EventType


def _make_client(dialect: str = "postgresql"):
    """Minimal client stub with just what generate_undo_scripts_operation needs."""
    client = MagicMock()
    client.dialect = dialect
    client.logger = None
    client.config = None
    client.events = MagicMock()
    return client


def _batch_terminal_call(client):
    """Find the single batch-level terminal emit (payload carries 'results')."""
    calls = [
        call for call in client.events.emit.call_args_list if "results" in call.args[1]
    ]
    assert len(calls) == 1, "expected exactly one batch-level terminal event"
    return calls[0]


@pytest.mark.unit
class TestGenerateUndoScriptsBatchFailedEvent:
    def test_all_failures_emits_migration_failed_not_completed(self, tmp_path):
        """Every item failing must emit a batch-level MIGRATION_FAILED, not MIGRATION_COMPLETED."""
        missing_paths = [
            tmp_path / "V1__missing.sql",
            tmp_path / "V2__missing.sql",
        ]

        client = _make_client()
        results = generate_undo_scripts_operation(client, migration_paths=missing_paths)

        assert len(results) == 2
        assert all(r.success is False for r in results)

        batch_call = _batch_terminal_call(client)
        assert batch_call.args[0] == EventType.MIGRATION_FAILED
        assert batch_call.args[1]["success_count"] == 0
        assert batch_call.args[1]["failure_count"] == 2

        emitted_types = [call.args[0] for call in client.events.emit.call_args_list]
        assert EventType.MIGRATION_COMPLETED not in emitted_types

    def test_all_successes_still_emits_migration_completed(self, tmp_path):
        """All items succeeding must still emit the batch-level MIGRATION_COMPLETED."""
        (tmp_path / "V1__create_table.sql").write_text(
            "CREATE TABLE widgets (id INT PRIMARY KEY);\n"
        )
        (tmp_path / "V2__create_other.sql").write_text(
            "CREATE TABLE gadgets (id INT PRIMARY KEY);\n"
        )

        client = _make_client()
        results = generate_undo_scripts_operation(client, migrations_dir=tmp_path)

        assert len(results) == 2
        assert all(r.success is True for r in results)

        batch_call = _batch_terminal_call(client)
        assert batch_call.args[0] == EventType.MIGRATION_COMPLETED
        assert batch_call.args[1]["success_count"] == 2
        assert batch_call.args[1]["failure_count"] == 0

    def test_partial_failure_emits_migration_failed(self, tmp_path):
        """A mix of success and failure must be reported as a batch-level failure."""
        (tmp_path / "V1__create_table.sql").write_text(
            "CREATE TABLE widgets (id INT PRIMARY KEY);\n"
        )
        missing_path = tmp_path / "V2__missing.sql"

        client = _make_client()
        results = generate_undo_scripts_operation(
            client, migration_paths=[tmp_path / "V1__create_table.sql", missing_path]
        )

        assert len(results) == 2
        batch_call = _batch_terminal_call(client)
        assert batch_call.args[0] == EventType.MIGRATION_FAILED
        assert batch_call.args[1]["success_count"] == 1
        assert batch_call.args[1]["failure_count"] == 1
