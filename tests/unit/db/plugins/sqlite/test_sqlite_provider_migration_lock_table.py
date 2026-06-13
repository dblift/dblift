"""BUG-04 regression: SQLiteProvider declares MIGRATION_LOCK_TABLE.

Before this fix, ``SQLiteProvider`` inherited from ``BaseProvider`` (not
``JdbcProvider``) and never defined ``MIGRATION_LOCK_TABLE``. The snapshot
service filters internal tables via::

    getattr(self.provider, "MIGRATION_LOCK_TABLE", "")

For SQLite, that reduced to the empty string, so ``dblift_migration_lock``
appeared in snapshots as if it were a user table.
"""

from __future__ import annotations

import pytest


@pytest.mark.unit
class TestSqliteProviderMigrationLockTable:
    def test_attribute_declared_on_class(self):
        """The attribute must be reachable on the class (without instantiation)
        because schema_snapshot_service consults it via ``getattr`` on the
        provider instance."""
        from db.plugins.sqlite.provider import SQLiteProvider

        assert hasattr(SQLiteProvider, "MIGRATION_LOCK_TABLE")
        assert SQLiteProvider.MIGRATION_LOCK_TABLE == "dblift_migration_lock"

    def test_uses_standard_lock_table_name(self):
        """Snapshot filtering and cleanup rely on the standard lock table name."""
        from db.plugins.sqlite.provider import SQLiteProvider

        assert SQLiteProvider.MIGRATION_LOCK_TABLE == "dblift_migration_lock"
