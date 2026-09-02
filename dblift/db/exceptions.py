"""Shared exception groups for database driver boundary code."""

from typing import Tuple, Type

DB_OPERATION_EXCEPTIONS: Tuple[Type[Exception], ...] = (
    AttributeError,
    ValueError,
    TypeError,
    OSError,
    RuntimeError,
)
