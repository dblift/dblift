"""Leaf migration type vocabulary shared by resolution and history."""

from enum import Enum


class MigrationType(Enum):
    """Enum for migration types."""

    # Flyway-style versioned scripts (V*__description.*); parse_filename uses SQL for
    # every supported extension (.sql, .py, …), not "SQL format only".
    SQL = "SQL"
    PYTHON = "PYTHON"  # non-SQL versioned script migrations (.py, .js, etc.)
    REPEATABLE = "REPEATABLE"  # Repeatable migrations (R*.sql)
    UNDO_SQL = "UNDO_SQL"  # Undo migrations (U*.sql)
    BASELINE = "BASELINE"  # Baseline command entries (not actual script files)
    CALLBACK = "CALLBACK"  # Callback scripts
    DELETE = "DELETE"  # Delete operation entries (for audit trail when scripts are removed)
    UNKNOWN = "UNKNOWN"  # Unknown migration type


# Subset of MigrationType names that behave like versioned, ordered, run-once
# scripts. Consulted from state/command modules to decide whether a migration
# should participate in version-based pending/applied/undone accounting.
# Extend when a new scripted format is implemented — this is the single source
# of truth (the former duplicated copies in core/migration/state/*.py and the
# hardcoded literal in base_command.py have been removed).
VERSIONED_SCRIPT_TYPES: frozenset[str] = frozenset(
    {MigrationType.SQL.value, MigrationType.PYTHON.value}
)
