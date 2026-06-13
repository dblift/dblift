"""CLI wrapper for snapshot command.

Business logic lives in core.migration.commands.snapshot_command.
This module re-exports all symbols for backward compatibility.
"""

from core.migration.commands.snapshot_command import (  # noqa: F401
    SnapshotSource,
    _json_default,
    _log_command_footer,
    snapshot,
)
from core.utils.url_masking import mask_database_url  # noqa: F401

# Backward compatibility alias
_mask_database_url = mask_database_url
