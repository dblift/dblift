"""
Migration display state enumeration.

This module defines the possible states that migrations can have
for display and UI purposes.
"""

from enum import Enum


class MigrationDisplayState(Enum):
    """Migration display states for UI/presentation purposes."""

    SUCCESS = "Success"
    FAILED = "Failed"
    PENDING = "Pending"
    UNDONE = "Undone"
    DELETED = "Deleted"  # Migration marked as deleted by repair
    AVAILABLE = "Available"  # Undo migration ready to be applied
    ABOVE_TARGET = "Above target"  # Migration not applied and won't be (target version lower)
    BASELINE = "Baseline"  # Migration baselined this DB
    BELOW_BASELINE = "Below baseline"  # Migration not applied (DB baselined with higher version)
    MISSING = "Missing"  # Migration succeeded but could not be resolved
    FAILED_MISSING = "Failed missing"  # Migration failed and could not be resolved
    FAILED_FUTURE = "Failed future"  # Migration failed and version higher than current
    FUTURE = "Future"  # Migration succeeded but version higher than current
    OUT_OF_ORDER = "Out of order"  # Migration succeeded but applied out of order
    OUTDATED = "Outdated"  # Repeatable migration outdated and should be re-applied
    UNKNOWN = "Unknown"  # Migration state cannot be determined
    NEEDS_REPAIR = "Needs repair"  # Migration requires repair action
