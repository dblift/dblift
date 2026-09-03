"""Partition metadata handling for the hybrid SQL parser.

Extracted from hybrid_parser.py (story 20-16) to reduce file size.
Contains functions for parsing and normalizing partition metadata from CREATE TABLE statements.
"""

import re
from typing import List, Optional, Tuple

from dblift.core.sql_model.table import Table


def _normalize_identifier(identifier: Optional[str], preserve_case: bool) -> str:
    """Normalize a SQL identifier by stripping quotes and brackets."""
    if identifier is None:
        return ""

    trimmed = identifier.strip().strip('"').strip("`")
    if trimmed.startswith("[") and trimmed.endswith("]"):
        trimmed = trimmed[1:-1]

    if "." in trimmed:
        trimmed = trimmed.split(".")[-1]

    return trimmed if preserve_case else trimmed.upper()


def apply_partition_metadata(table: Table, sql_text: str) -> None:
    """Extract partition metadata from SQL text and apply it to the table."""
    pattern = re.compile(r"PARTITION\s+BY\s+([A-Z_]+)\s*\(", re.IGNORECASE)
    match = pattern.search(sql_text)
    if not match:
        table.partition_method = None
        table.partition_columns = None
        return
    method = match.group(1).upper()
    start_index = match.end()
    column_expr = extract_balanced_partition_expression(sql_text, start_index)
    columns = normalize_partition_columns(column_expr)

    table.partition_method = method
    table.partition_columns = columns or None


def normalize_partition_columns(expression: str) -> List[str]:
    """Normalize partition column expressions into a list of column names."""
    columns: List[str] = []
    for raw in expression.split(","):
        candidate = raw.strip()
        if not candidate:
            continue

        candidate = strip_function_wrappers(candidate)
        normalized = _normalize_identifier(candidate, preserve_case=False)
        if normalized:
            columns.append(normalized)
    return columns


def extract_balanced_partition_expression(sql_text: str, start_index: int) -> str:
    """Extract the balanced parenthesized expression starting at start_index."""
    depth = 1
    chars: List[str] = []
    i = start_index
    while i < len(sql_text) and depth > 0:
        char = sql_text[i]
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                break
        chars.append(char)
        i += 1
    return "".join(chars).strip()


def strip_function_wrappers(expression: str) -> str:
    """Iteratively strip outer function wrappers from an expression."""
    candidate = expression.strip()
    changed = True
    while changed:
        candidate, changed = strip_outer_function(candidate)
    # If nested parentheses remain unmatched, strip trailing closing parens
    while candidate.endswith(")") and candidate.count("(") < candidate.count(")"):
        candidate = candidate[:-1]
    return candidate.strip()


def strip_outer_function(expression: str) -> Tuple[str, bool]:
    """Strip a single outer function wrapper. Returns (result, was_stripped)."""
    expr = expression.strip()
    if not expr.endswith(")"):
        return expr, False

    depth = 0
    open_index = None
    for idx, char in enumerate(expr):
        if char == "(":
            depth += 1
            if depth == 1:
                open_index = idx
        elif char == ")":
            depth -= 1
            if depth == 0 and idx == len(expr) - 1 and open_index is not None:
                func_name = expr[:open_index].strip()
                if func_name and func_name.replace("_", "").replace("-", "").isalnum():
                    inner = expr[open_index + 1 : idx].strip()
                    # If the function had multiple arguments, assume column is last argument
                    if "," in inner:
                        inner = inner.split(",")[-1].strip()
                    return inner, True
    return expr, False
