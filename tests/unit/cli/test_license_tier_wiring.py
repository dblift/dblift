"""``execute_single_command`` must populate the handler context's ``license_tier``
from the tier-resolver seam.

Regression: ``CliCommandContext.license_tier`` defaults to ``None`` and its
docstring says ``execute_single_command`` supplies the real CLI-resolved tier —
but the construction dropped the assignment, so every paid-feature gate
(``require_tier(FEATURE, ctx.license_tier)``) saw ``None`` and rejected every
Pro/Enterprise CLI command regardless of the license.
"""

from types import SimpleNamespace

import pytest

from cli import _command_handlers
from core.seams import tier_resolver


@pytest.mark.unit
def test_execute_single_command_populates_license_tier_from_resolver(monkeypatch):
    captured = {}

    def _handler(ctx):
        captured["tier"] = ctx.license_tier
        return (True, None)

    monkeypatch.setitem(_command_handlers._COMMAND_HANDLERS, "migrate", _handler)
    monkeypatch.setattr(tier_resolver, "_RESOLVER", lambda args: "ENTERPRISE_SENTINEL")

    _command_handlers.execute_single_command(
        client=None,
        command="migrate",
        args=SimpleNamespace(),
        log=None,
        scripts_dir=None,
        additional_scripts_dirs=[],
        recursive=False,
        placeholders={},
        dir_recursive_map={},
    )

    assert captured["tier"] == "ENTERPRISE_SENTINEL"


@pytest.mark.unit
def test_license_tier_is_none_when_no_resolver_registered(monkeypatch):
    """Pure OSS (no resolver) still resolves to None — fail-closed, unchanged."""
    captured = {}

    def _handler(ctx):
        captured["tier"] = ctx.license_tier
        return (True, None)

    monkeypatch.setitem(_command_handlers._COMMAND_HANDLERS, "migrate", _handler)
    monkeypatch.setattr(tier_resolver, "_RESOLVER", None)

    _command_handlers.execute_single_command(
        client=None,
        command="migrate",
        args=SimpleNamespace(),
        log=None,
        scripts_dir=None,
        additional_scripts_dirs=[],
        recursive=False,
        placeholders={},
        dir_recursive_map={},
    )

    assert captured["tier"] is None
