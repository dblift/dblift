"""CLI-level shared constants.

Single source of truth for values referenced in more than one CLI module
(``cli/main.py``, ``cli/_command_handlers.py``, parsers, formatters).
Adding a constant here instead of inlining it is a hard requirement of
the stabilization program: duplicated literals across modules have been
the root cause of several recent regressions (see
``docs/stabilization-plan.md`` §"Doubles sources de vérité").
"""

from __future__ import annotations

# Output formats whose stdout is a parser-facing contract, not a
# human-facing report. Any command exposing one of these via ``--format``
# must keep stdout empty of banners, log lines, and completion messages
# (see ``docs/adr/0005-stdout-machine-readability.md``).
#
# When a subcommand adds a new machine-readable format, add it here —
# not inline at the call site — so that ``cli/main.py`` banner
# suppression and ``cli/_command_handlers.py`` log-line suppression stay
# in lockstep.
MACHINE_READABLE_FORMATS: frozenset[str] = frozenset(
    {"json", "sarif", "github-actions", "gitlab", "compact"}
)
