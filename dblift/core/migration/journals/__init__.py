"""Migration journal module for in-memory performance tracking.

This module provides in-memory tracking of migration execution details,
including SQL statements, performance metrics, and execution status.
Data is kept in memory for inclusion in log reports (HTML/JSON).
"""

from dblift.core.migration.journals.migration_journal import (
    EntryType,
    JournalEntry,
    MigrationJournal,
)

__all__ = ["EntryType", "JournalEntry", "MigrationJournal"]
