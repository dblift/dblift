"""
Compatibility imports for introspection utility helpers.

The neutral row-access implementations live in ``dblift.core.utils.row_access``.
Keep this module import-compatible while rich introspection callers transition.
"""

from dblift.core.utils.row_access import (
    get_row_value,
    parse_json_array,
    parse_pg_options,
    strip_leading_comments,
    to_int,
)

__all__ = [
    "get_row_value",
    "parse_json_array",
    "parse_pg_options",
    "strip_leading_comments",
    "to_int",
]
