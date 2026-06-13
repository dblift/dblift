"""
Common utility functions for schema introspection.

This module provides shared utility functions used across all introspectors
and extractors, including row value extraction, JSON parsing, and type conversion.
"""

import json
from typing import Any, Dict, List, Optional


def get_row_value(row: Dict[str, Any], key: str) -> Any:
    """
    Get value from row dictionary, handling both lowercase and uppercase keys.

    Different databases return column names in different cases:
    - PostgreSQL, MySQL, SQL Server: lowercase
    - Oracle: UPPERCASE
    - DB2: Various formats (may strip underscores, use abbreviations)

    Args:
        row: Dictionary from query result
        key: Column name to look up (lowercase)

    Returns:
        Value from the row, or None if not found
    """
    # Try lowercase first (PostgreSQL, MySQL, SQL Server)
    value = row.get(key)
    if value is not None:
        return value
    # Try uppercase (Oracle)
    value = row.get(key.upper())
    if value is not None:
        return value
    # Some drivers (DB2) strip underscores from aliases; try without them
    alt_keys = set()
    if "_" in key:
        compact_key = key.replace("_", "")
        alt_keys.add(compact_key)
        alt_keys.add(compact_key.upper())

    # DB2-style abbreviations (sequence -> seq, constraint -> const, table -> tab, column -> col, index -> ind)
    if "sequence" in key:
        alt_keys.add(key.replace("sequence", "seq"))
        alt_keys.add(key.replace("sequence", "seq").replace("_", ""))
    if "constraint" in key:
        alt_keys.add(key.replace("constraint", "const"))
        alt_keys.add(key.replace("constraint", "const").replace("_", ""))
    if "table" in key:
        alt_keys.add(key.replace("table", "tab"))
        alt_keys.add(key.replace("table", "tab").replace("_", ""))
    if "column" in key:
        alt_keys.add(key.replace("column", "col"))
        alt_keys.add(key.replace("column", "col").replace("_", ""))
    if "index" in key:
        alt_keys.add(key.replace("index", "ind"))
        alt_keys.add(key.replace("index", "ind").replace("_", ""))
    if "view" in key:
        alt_keys.add(key.replace("_", ""))

    db2_aliases = {
        "view_definition": {"text"},
        "sequence_name": {"seqname"},
        "start_value": {"start"},
        "minimum_value": {"minvalue"},
        "maximum_value": {"maxvalue"},
        "increment": {"increment"},
        "increment_by": {"increment"},
        "cache_size": {"cache"},
        "check_option": {"checkoption"},
        "is_updatable": {"readonly"},
        "trigger_name": {"trigname"},
        "table_name": {"tabname"},
        "action_statement": {"text"},
        "constraint_definition": {"text"},  # DB2 TEXT column for check constraints
    }
    if key in db2_aliases:
        alt_keys.update(db2_aliases[key])

    for alt in alt_keys:
        if not alt:
            continue
        value = row.get(alt)
        if value is not None:
            return value
        value = row.get(alt.upper())
        if value is not None:
            return value
    return None


def parse_pg_options(raw_options: Any) -> Dict[str, str]:
    """
    Parse PostgreSQL option arrays into dictionaries.

    Args:
        raw_options: Raw options from PostgreSQL (can be list, string, or other)

    Returns:
        Dictionary of parsed options
    """
    options: Dict[str, str] = {}
    if raw_options is None:
        return options

    if isinstance(raw_options, (list, tuple, set)):
        iterable = raw_options
    elif isinstance(raw_options, str):
        iterable = [item.strip() for item in raw_options.split(",") if item.strip()]
    else:
        iterable = [raw_options]

    for item in iterable:
        if item is None:
            continue
        if isinstance(item, bytes):
            try:
                item = item.decode("utf-8")
            except Exception:
                # Intentional: non-UTF-8 bytes fall back to str() representation
                item = str(item)
        item_str = str(item)
        if "=" in item_str:
            key, value = item_str.split("=", 1)
            options[key.strip()] = value.strip()
        else:
            options[item_str.strip()] = ""

    return options


def parse_json_array(raw_value: Any) -> List[Any]:
    """Parse a JSON array payload returned by vendor queries."""
    if raw_value is None:
        return []
    if isinstance(raw_value, list):
        return raw_value
    if isinstance(raw_value, str):
        try:
            parsed = json.loads(raw_value)
            return parsed if isinstance(parsed, list) else []
        except json.JSONDecodeError:
            return []
    return []


def strip_leading_comments(sql_text: str) -> str:
    """Remove leading comments/whitespace from SQL text."""
    if not sql_text:
        return ""
    idx = 0
    length = len(sql_text)
    while idx < length:
        while idx < length and sql_text[idx] in (" ", "\t", "\n", "\r"):
            idx += 1
        if idx >= length:
            break
        if sql_text.startswith("--", idx):
            newline_pos = sql_text.find("\n", idx + 2)
            if newline_pos == -1:
                return ""
            idx = newline_pos + 1
            continue
        if sql_text.startswith("/*", idx):
            end_pos = sql_text.find("*/", idx + 2)
            if end_pos == -1:
                return ""
            idx = end_pos + 2
            continue
        break
    return sql_text[idx:]


def to_int(value: Any) -> Optional[int]:
    """Best-effort conversion of metadata value to integer."""
    if value is None:
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return int(value)
    try:
        text = str(value).strip()
        if not text:
            return None
        try:
            return int(text)
        except ValueError:
            return int(float(text))
    except (ValueError, TypeError, OverflowError):
        return None
