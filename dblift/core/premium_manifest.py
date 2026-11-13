"""Catalog of paid dblift commands surfaced as stubs in OSS.

This module is the ONLY place OSS code may name paid-edition commands
(2026-07 amendment to the tier-architecture naming invariant: the
unidirectional dependency rule is untouched — OSS still imports nothing
from a higher tier — but this one file may carry a declarative catalog so
OSS can advertise paid commands instead of silently omitting them).

It lives in ``core/`` rather than ``cli/`` because both the CLI
(``cli/premium_manifest.py`` re-exports these symbols for backward
compatibility) and the API (``api/client.py``) need it, and the
``cli-is-topmost`` .importlinter contract forbids ``api`` from importing
``cli``. ``core/`` is a layer both can reach.

It is pure data plus rendering helpers. When the paid runtime is installed,
its entry-point registrations run first and the stubs for those commands
are never created (see ``_register_premium_stub_parsers`` in
``cli/_parser_setup.py`` and the gap-fill block in
``cli/_command_handlers.py``), so precedence is structural, not conditional.

The ``api_method`` field on ``PremiumCommand`` names the corresponding OSS
``DBLiftClient`` method (``api/client.py``), for commands that have a
programmatic-API equivalent. It is used to build the API's own paid-tier
stub methods (``diff``, ``export_schema``, ``snapshot``, ``plan``,
``preflight``), mirroring the CLI stubs one layer down. Commands with no
API equivalent (``data``) leave it ``None``.

``_register_premium_stub_parsers`` (``cli/_parser_setup.py``) decides
whether to create a stub purely by string-matching catalog names against
already-registered parser names — it cannot tell a stale entry from a real
gap. If this catalog drifts from the command surface a paid runtime
actually registers (a rename, a removal, a name never shipped), a stub
gets created that either shadows a real command under a different name or
advertises one that does not exist, breaking the "real parsers always
win" precedence above. Keep entries in sync with the real command
surface, never ahead of it.

A stub also fires when an extension package is installed without the
package that provides the command; :func:`render_upsell` then says which
package to install instead of the default message. It checks the installed
distributions only when a stub fires, never at import time.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version
from typing import Dict, Iterable, Optional, Tuple

_log = logging.getLogger(__name__)

UPGRADE_URL = "https://dblift.com/upgrade"
# Distribution names (PEP 503 canonical form) checked by render_upsell and feature loading.
PRO_DISTRIBUTION = "dblift-pro"
ENTERPRISE_DISTRIBUTION = "dblift-enterprise"


@dataclass(frozen=True)
class PremiumCommand:
    """Declarative descriptor for a command, or root flag, that only an extension provides."""

    name: str  # command name, or the flag spelling (``--flag``) for a root flag
    edition: str  # human-facing label: "Pro" or "Enterprise"
    summary: str  # one-line help, mirrored from the paid parser registration
    api_method: Optional[str] = None  # corresponding api.DBLiftClient method, if any


PREMIUM_COMMANDS: Tuple[PremiumCommand, ...] = (
    PremiumCommand(
        "diff",
        "Pro",
        "Compare applied migrations against live database schema (drift detection)",
        api_method="diff",
    ),
    PremiumCommand(
        "export-schema",
        "Pro",
        "Export database schema to SQL migration file(s)",
        api_method="export_schema",
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
        api_method="snapshot",
    ),
    PremiumCommand(
        "plan",
        "Enterprise",
        "Build an offline migration plan from a snapshot model",
        api_method="plan",
    ),
    PremiumCommand(
        "preflight",
        "Enterprise",
        "Run deployment preflight checks from a snapshot model",
        api_method="preflight",
    ),
    PremiumCommand(
        "license",
        "Enterprise",
        "Manage the dblift license (activate, info, check)",
    ),
)

# Root flags an extension package registers. Kept apart from PREMIUM_COMMANDS,
# which drives the subcommand stubs.
PREMIUM_ROOT_FLAGS: Tuple[PremiumCommand, ...] = (
    PremiumCommand(
        "--license-key",
        "Enterprise",
        "Pass a key for this invocation",
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


def premium_root_flags_missing_from(
    registered: Iterable[str],
) -> Tuple[PremiumCommand, ...]:
    """Root-flag entries whose spelling is not among the ``registered`` option strings."""
    taken = set(registered)
    return tuple(flag for flag in PREMIUM_ROOT_FLAGS if flag.name not in taken)


def premium_stub_index(registered: Iterable[str]) -> Dict[str, PremiumCommand]:
    """Like :func:`premium_commands_missing_from`, keyed by command name."""
    return {cmd.name: cmd for cmd in premium_commands_missing_from(registered)}


def distribution_installed(name: str) -> bool:
    """Whether the distribution ``name`` is installed; a broken one counts as absent."""
    try:
        version(name)
    except PackageNotFoundError:
        return False
    except Exception as exc:  # a broken distribution must not break the caller
        _log.warning("Could not check whether %r is installed: %s", name, exc)
        return False
    return True


def render_upsell(cmd: PremiumCommand) -> str:
    """Message shown when a stubbed command is invoked.

    By default it names the edition and the upgrade page. When an extension
    package is installed without the package that provides the command, it
    says which package to install instead.
    """
    if distribution_installed(PRO_DISTRIBUTION) and not distribution_installed(
        ENTERPRISE_DISTRIBUTION
    ):
        return (
            f"'{cmd.name}' is provided by the {ENTERPRISE_DISTRIBUTION} package, "
            f"which is not installed.\n"
            f"  {cmd.summary}.\n"
            f"Install {ENTERPRISE_DISTRIBUTION}[<engine>] from your DBLift bundle, "
            f"then run: dblift license activate <key>"
        )
    kind = "option" if cmd.name.startswith("--") else "command"
    return (
        f"'{cmd.name}' is a dblift {cmd.edition} {kind} and is not included "
        f"in the open-source edition.\n"
        f"  {cmd.summary}.\n"
        f"Learn more and upgrade: {UPGRADE_URL}"
    )
