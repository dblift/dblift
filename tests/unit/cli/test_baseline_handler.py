"""Tests for the baseline CLI handler."""

from types import SimpleNamespace
from unittest.mock import MagicMock

from dblift.cli._command_handlers import CliCommandContext
from dblift.cli.handlers.baseline import _handle_baseline


def test_handle_baseline_forwards_dry_run():
    client = MagicMock()
    result = SimpleNamespace(success=True)
    client.baseline.return_value = result
    log = MagicMock()
    args = SimpleNamespace(
        baseline_version="1.0.0",
        baseline_description="initial",
        dry_run=True,
    )
    ctx = CliCommandContext(client=client, args=args, log=log)

    success, returned = _handle_baseline(ctx)

    assert success is True
    assert returned is result
    client.baseline.assert_called_once_with("1.0.0", "initial", dry_run=True)
