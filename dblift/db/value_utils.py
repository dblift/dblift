"""Small value-conversion helpers shared by providers and introspection."""

from typing import Any, Dict, Optional


def to_python_string(value: Any) -> Optional[str]:
    """Return a Python string, or None if value is None."""
    if value is None:
        return None
    return str(value)


def row_value(row: Dict[str, Any], *names: str, default: Any = None) -> Any:
    """Read a value from a row mapping, tolerating exact, upper and lower case keys."""
    for name in names:
        if name in row:
            return row[name]
        upper = name.upper()
        if upper in row:
            return row[upper]
        lower = name.lower()
        if lower in row:
            return row[lower]
    return default


def clean_identifier(name: str) -> str:
    """Return a bare identifier: double quotes removed and whitespace stripped."""
    return name.replace('"', "").strip()


def double_quote_identifier(name: str) -> str:
    """Return *name* as a double-quoted identifier, doubling embedded quotes."""
    return '"' + name.replace('"', '""') + '"'


def string_mapping(values: Any) -> Dict[str, str]:
    """Return *values* as a ``str -> str`` dict; anything that is not a dict gives ``{}``."""
    if not isinstance(values, dict):
        return {}
    return {str(key): str(value) for key, value in values.items()}
