"""Helpers for schema-wide index introspection."""

from typing import Any, Dict, List, Optional, Sequence


def group_bulk_indexes(
    introspector: Any, schema: str, tables: Sequence[Any]
) -> Optional[Dict[str, List[Any]]]:
    """Return indexes grouped by table, or ``None`` to use per-table lookup."""
    get_all_indexes = getattr(introspector, "get_all_indexes", None)
    if not callable(get_all_indexes):
        return None

    try:
        indexes = get_all_indexes(schema)
    except Exception as exc:
        introspector.log.debug(f"Bulk index introspection failed: {exc}; using per-table lookup")
        return None

    if not isinstance(indexes, list):
        return None

    grouped: Dict[str, List[Any]] = {table.name: [] for table in tables}
    for index in indexes:
        table_name = getattr(index, "table_name", None)
        if not isinstance(table_name, str):
            continue
        table_indexes = grouped.get(table_name)
        if table_indexes is not None:
            table_indexes.append(index)
    return grouped
