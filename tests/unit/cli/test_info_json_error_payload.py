"""Regression test: ``info --format json`` still emits a JSON payload on error.

Cursor bot found: ``_handle_info`` redirected stdout into a sink while calling
``ctx.client.info()`` so that human output wouldn't contaminate the JSON
channel. If ``info()`` raised, the exception propagated out of the redirect
block, stdout was restored, but the ``if use_json:`` emit step was skipped —
the user got a raw traceback and no machine-readable error payload. That
breaks the JSON contract for error cases.

The fix catches the exception in the JSON path, emits a
``{"success": False, "error": ...}`` payload via ``command_output.machine``,
and returns ``(False, None)``. Human format re-raises (existing behavior).
"""

from __future__ import annotations

import io
import json
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from cli._command_handlers import _handle_info


def _make_ctx(format_value: str, info_side_effect):
    client = MagicMock()
    client.info.side_effect = info_side_effect
    args = SimpleNamespace(
        target_version=None,
        versions=None,
        exclude_versions=None,
        tags=None,
        exclude_tags=None,
        format=format_value,
        verbose=False,
    )
    ctx = SimpleNamespace(
        client=client,
        args=args,
        log=MagicMock(),
        recursive=True,
        additional_scripts_dirs=None,
    )
    return ctx


@pytest.mark.unit
class TestInfoJsonErrorPayload:
    def test_json_error_emits_payload_not_traceback(self, capsys):
        """info() raising with --format json → JSON error payload on stdout."""
        ctx = _make_ctx("json", RuntimeError("connection refused"))

        success, result = _handle_info(ctx)

        captured = capsys.readouterr()
        assert success is False
        assert result is None

        # Payload is valid JSON and describes the error.
        payload = json.loads(captured.out)
        assert payload["success"] is False
        assert "connection refused" in payload["error"]
        assert "RuntimeError" in payload["error"]

    def test_human_format_reraises(self):
        """Human format keeps the old behavior: exception propagates upward."""
        ctx = _make_ctx("table", RuntimeError("connection refused"))

        with pytest.raises(RuntimeError, match="connection refused"):
            _handle_info(ctx)

    def test_keyboard_interrupt_always_propagates(self):
        """Ctrl-C must terminate the process, even in JSON mode — we do NOT
        want to convert it into a ``{"success": false}`` payload and silently
        swallow the signal.
        """
        ctx = _make_ctx("json", KeyboardInterrupt())

        with pytest.raises(KeyboardInterrupt):
            _handle_info(ctx)

    def test_system_exit_always_propagates(self):
        """``SystemExit`` (raised by license validation, argparse, etc.) must
        propagate so the process exits with the correct code. Swallowing it
        as a JSON payload would leave the process running."""
        ctx = _make_ctx("json", SystemExit(2))

        with pytest.raises(SystemExit):
            _handle_info(ctx)

    def test_none_result_returns_false_without_attribute_error(self):
        """If ``ctx.client.info()`` returns None (provider bug / mock), we must
        not hit ``AttributeError: 'NoneType' has no attribute 'success'``."""

        def _returns_none(**kwargs):
            return None

        ctx = _make_ctx("table", _returns_none)

        success, result = _handle_info(ctx)

        assert success is False
        assert result is None

    def test_none_result_in_json_mode_emits_structured_error(self, capsys):
        """In JSON mode, a None result emits a ``{"success": false, ...}``
        payload instead of a misleading ``success: true`` with empty fields."""

        def _returns_none(**kwargs):
            return None

        ctx = _make_ctx("json", _returns_none)

        success, result = _handle_info(ctx)

        assert success is False
        assert result is None

        captured = capsys.readouterr()
        payload = json.loads(captured.out)
        assert payload["success"] is False
        assert "no result" in payload["error"].lower()
