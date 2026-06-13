"""CLI wrapper for export-schema command.

Business logic lives in core.migration.commands.export_schema_command.
This module re-exports all symbols for backward compatibility.
"""

from core.migration.commands._schema_export_types import _json_default  # noqa: F401
from core.migration.commands.export_schema_command import (  # noqa: F401
    _exclude_internal_objects,
    _filter_objects,
    _generate_migration_footer,
    _generate_migration_header,
    _get_managed_objects,
    _is_object_managed,
    _log_command_footer,
    _normalize_identifier,
    _populate_export_result_metadata,
    _remove_redundant_unique_constraints,
    export_schema,
)
from core.utils.url_masking import mask_database_url  # noqa: F401

# Backward compatibility alias
_mask_database_url = mask_database_url
