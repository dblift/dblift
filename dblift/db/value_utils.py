"""Small value-conversion helpers shared by providers and introspection."""

from typing import Any, Optional


def to_python_string(value: Any) -> Optional[str]:
    """Return a Python string, or None if value is None."""
    if value is None:
        return None
    return str(value)
