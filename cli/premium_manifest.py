"""Catalog of paid dblift commands surfaced as stubs in the OSS CLI.

This module is the ONLY place OSS code may name paid-edition commands
(2026-07 amendment to the tier-architecture naming invariant: the
unidirectional dependency rule is untouched — OSS still imports nothing
from a higher tier — but this one file may carry a declarative catalog so
the OSS CLI can advertise paid commands instead of silently omitting them).

It is pure data plus rendering helpers. When the paid runtime is installed,
its entry-point registrations run first and the stubs for those commands
are never created (see ``_register_premium_stub_parsers`` in
``cli/_parser_setup.py`` and the gap-fill block in
``cli/_command_handlers.py``), so precedence is structural, not conditional.

The paid monorepo carries a CI check that diffs this catalog against the
commands its packages actually register — keep entries in sync with the
real command surface, never ahead of it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, Tuple

UPGRADE_URL = "https://dblift.com/upgrade"


@dataclass(frozen=True)
class PremiumCommand:
    """Declarative descriptor for a command that exists only in a paid edition."""

    name: str
    edition: str  # human-facing label: "Pro" or "Enterprise"
    summary: str  # one-line help, mirrored from the paid parser registration


PREMIUM_COMMANDS: Tuple[PremiumCommand, ...] = (
    PremiumCommand(
        "diff",
        "Pro",
        "Compare applied migrations against live database schema (drift detection)",
    ),
    PremiumCommand(
        "export-schema",
        "Pro",
        "Export database schema to SQL migration file(s)",
    ),
    PremiumCommand(
        "validate-sql",
        "Pro",
        "Validate SQL files with business rules and performance analysis",
    ),
    PremiumCommand(
        "data",
        "Pro",
        "Manage data corrections - audited DML with plan/apply/undo",
    ),
    PremiumCommand(
        "snapshot",
        "Enterprise",
        "Export database schema snapshot to JSON model file",
    ),
    PremiumCommand(
        "plan",
        "Enterprise",
        "Build an offline migration plan from a snapshot model",
    ),
    PremiumCommand(
        "preflight",
        "Enterprise",
        "Run deployment preflight checks from a snapshot model",
    ),
)


def premium_commands_missing_from(
    registered: Iterable[str],
) -> Tuple[PremiumCommand, ...]:
    """Manifest entries with no real registration among ``registered``.

    Callers pass the names already claimed by builtins and entry-point
    extensions; anything returned needs a stub. With the paid runtime
    installed this is empty and the OSS surface is untouched.
    """
    taken = set(registered)
    return tuple(cmd for cmd in PREMIUM_COMMANDS if cmd.name not in taken)


def premium_stub_index(registered: Iterable[str]) -> Dict[str, PremiumCommand]:
    """Like :func:`premium_commands_missing_from`, keyed by command name."""
    return {cmd.name: cmd for cmd in premium_commands_missing_from(registered)}


def render_upsell(cmd: PremiumCommand) -> str:
    """Message shown when a stubbed paid command is invoked in OSS."""
    return (
        f"'{cmd.name}' is a dblift {cmd.edition} command and is not included "
        f"in the open-source edition.\n"
        f"  {cmd.summary}.\n"
        f"Learn more and upgrade: {UPGRADE_URL}"
    )
