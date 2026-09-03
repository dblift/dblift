"""Backward-compatible re-export of the premium-command catalog.

The catalog itself lives in ``core/premium_manifest.py`` now — both
``cli/`` and ``api/`` need it, and the ``cli-is-topmost`` .importlinter
contract forbids ``api`` from importing ``cli``, so it moved to a layer
both can reach. This module keeps ``from cli.premium_manifest import ...``
working unchanged for existing CLI code and tests.
"""

from __future__ import annotations

from dblift.core.premium_manifest import (
    PREMIUM_COMMANDS,
    UPGRADE_URL,
    PremiumCommand,
    premium_commands_missing_from,
    premium_stub_index,
    render_upsell,
)

__all__ = [
    "PREMIUM_COMMANDS",
    "UPGRADE_URL",
    "PremiumCommand",
    "premium_commands_missing_from",
    "premium_stub_index",
    "render_upsell",
]
