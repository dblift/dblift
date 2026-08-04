"""Lifecycle-phase ordering invariants for migration commands.

The BaseMigrationCommand preflight (ADR-0011) enforces the order:

    1. _ensure_connected()
    2. history_manager.create_schema_and_history_table()  (optional)
    3. _populate_database_info(result)

Before PR-11, ``info_command.execute`` called these in a different
order (``populate`` then ``create`` — Bugbot PR 160 flag). That order
is latent even if the provider tolerates it today: any provider whose
``_populate_database_info`` introspects a table that the history DDL
just created would return incomplete metadata.

These tests assert the call order on a spied ``_run_preflight`` so the
contract stays encoded in CI, not in prose.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest


class _Stub:
    """Minimal namespace to record method-call order on the command under test."""

    def __init__(self):
        self.calls: list[tuple[str, tuple, dict]] = []

    def __call__(self, name):
        def _recorder(*args, **kwargs):
            self.calls.append((name, args, kwargs))

        return _recorder


@pytest.fixture
def recorder():
    return _Stub()


# --- _run_preflight in isolation --------------------------------------------


def _patch_preflight(monkeypatch, command, recorder):
    """Replace the three preflight collaborators with call recorders."""
    monkeypatch.setattr(command, "_ensure_connected", recorder("_ensure_connected"))
    command.history_manager = MagicMock()
    command.history_manager.create_schema_and_history_table.side_effect = recorder(
        "create_schema_and_history_table"
    )
    monkeypatch.setattr(command, "_populate_database_info", recorder("_populate_database_info"))


def _make_minimal_command():
    """Build a BaseCommand without touching real config/provider/logger."""
    from core.migration.commands.base_command import BaseCommand

    cmd = BaseCommand.__new__(BaseCommand)
    cmd.log = MagicMock()
    cmd.provider = MagicMock()
    return cmd


class TestPreflightOrdering:
    def test_default_order_is_connect_then_populate(self, monkeypatch, recorder):
        """ensure_history=False (clean-style): connect → populate, no DDL."""
        cmd = _make_minimal_command()
        _patch_preflight(monkeypatch, cmd, recorder)

        cmd._run_preflight(result=MagicMock())

        order = [name for (name, _, _) in recorder.calls]
        assert order == ["_ensure_connected", "_populate_database_info"]

    def test_with_history_inserts_create_between_connect_and_populate(self, monkeypatch, recorder):
        """migrate/info: connect → create_history → populate (strict order)."""
        cmd = _make_minimal_command()
        _patch_preflight(monkeypatch, cmd, recorder)

        cmd._run_preflight(result=MagicMock(), ensure_history=True)

        order = [name for (name, _, _) in recorder.calls]
        assert order == [
            "_ensure_connected",
            "create_schema_and_history_table",
            "_populate_database_info",
        ]

    def test_dry_run_skips_history_creation(self, monkeypatch, recorder):
        """dry_run=True must NOT call create_schema_and_history_table (PR-02 contract)."""
        cmd = _make_minimal_command()
        _patch_preflight(monkeypatch, cmd, recorder)

        cmd._run_preflight(result=MagicMock(), ensure_history=True, dry_run=True)

        order = [name for (name, _, _) in recorder.calls]
        assert "create_schema_and_history_table" not in order
        assert order == ["_ensure_connected", "_populate_database_info"]

    def test_create_schema_defaults_to_false(self, monkeypatch, recorder):
        """migrate/info/undo: create_schema defaults to False (unchanged)."""
        cmd = _make_minimal_command()
        _patch_preflight(monkeypatch, cmd, recorder)

        cmd._run_preflight(result=MagicMock(), ensure_history=True)

        create_call = next(c for c in recorder.calls if c[0] == "create_schema_and_history_table")
        assert create_call[2] == {"create_schema": False}

    def test_create_schema_true_is_forwarded(self, monkeypatch, recorder):
        """baseline: create_schema=True must reach create_schema_and_history_table."""
        cmd = _make_minimal_command()
        _patch_preflight(monkeypatch, cmd, recorder)

        cmd._run_preflight(result=MagicMock(), ensure_history=True, create_schema=True)

        create_call = next(c for c in recorder.calls if c[0] == "create_schema_and_history_table")
        assert create_call[2] == {"create_schema": True}

    def test_populate_always_runs_last(self, monkeypatch, recorder):
        """Whatever the flags, populate comes AFTER connect (Bugbot PR 160 guard)."""
        cmd = _make_minimal_command()
        _patch_preflight(monkeypatch, cmd, recorder)

        for flags in (
            {},
            {"ensure_history": True},
            {"dry_run": True},
            {"ensure_history": True, "dry_run": True},
        ):
            recorder.calls.clear()
            cmd._run_preflight(result=MagicMock(), **flags)
            order = [name for (name, _, _) in recorder.calls]
            connect_idx = order.index("_ensure_connected")
            populate_idx = order.index("_populate_database_info")
            assert (
                connect_idx < populate_idx
            ), f"With flags {flags}: populate must come after connect, got {order}"
