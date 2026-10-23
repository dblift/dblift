"""Check whether an optional dependency is installed without importing it."""

import importlib.util


def module_available(module: str) -> bool:
    """Return True when ``module`` can be imported (without importing it)."""
    try:
        return importlib.util.find_spec(module) is not None
    except (ImportError, ValueError):
        return False
