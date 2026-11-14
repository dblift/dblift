"""Exit with ``EXIT_LICENSE_REQUIRED`` on a capability denial outside command dispatch."""

from __future__ import annotations

import sys
from contextlib import contextmanager
from typing import Iterator

from dblift.cli._constants import EXIT_LICENSE_REQUIRED, LICENSE_REQUIRED_FALLBACK_MESSAGE
from dblift.core.seams.capabilities import CapabilityDeniedError


@contextmanager
def exit_on_capability_denial() -> Iterator[None]:
    """Report a capability denial raised inside the block on stderr and exit.

    Used around configuration loading, which runs before (or instead of) the dispatch
    handler that maps the denial. ``SystemExit`` passes through the broad ``except``
    clauses of the callers, and a context manager adds no branch to their complexity.
    """
    try:
        yield
    except CapabilityDeniedError as e:
        print(f"Error: {str(e).strip() or LICENSE_REQUIRED_FALLBACK_MESSAGE}", file=sys.stderr)
        sys.exit(EXIT_LICENSE_REQUIRED)
