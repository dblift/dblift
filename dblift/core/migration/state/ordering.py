"""The strict-mode ordering rule: which pending migrations sit below the current version."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Sequence, Tuple

from dblift.core.migration.migration import Migration
from dblift.core.migration.version_utils import compare_versions


@dataclass(frozen=True)
class OutOfOrder:
    """A pending versioned migration at or below the schema's current version."""

    migration: Migration
    current_version: str


def out_of_order(
    pending: Sequence[Migration], current_version: Optional[str]
) -> Tuple[OutOfOrder, ...]:
    """Return the pending migrations whose version is at or below ``current_version``.

    ``migrate`` and the validator both read this one rule. Pending migrations
    without a version are never out of order, and nothing is out of order while
    the schema has no current version. The input order is kept.
    """
    if not current_version:
        return ()
    return tuple(
        OutOfOrder(migration, str(current_version))
        for migration in pending
        if migration.version and compare_versions(str(migration.version), str(current_version)) <= 0
    )
