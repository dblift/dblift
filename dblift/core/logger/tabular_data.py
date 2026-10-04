"""Pure query-result data shaping shared by execution and presentation."""

from typing import Any, Dict, List, Tuple


def rows_to_columns_and_values(
    result_set: List[Dict[str, Any]],
) -> Tuple[List[str], List[List[Any]]]:
    """Convert a query result set (list of row dicts) into (columns, rows) form.

    ``columns`` is taken from the first row's key order; ``rows`` is a list of
    cell-value lists in that same column order, suitable for
    ``render_records_table`` or JSON/HTML serialization.
    """
    columns = list(result_set[0].keys()) if result_set else []
    return columns, [[row.get(c) for c in columns] for row in result_set]
