"""SQLite owns schema snapshot persistence like every other provider.

SQLite previously overrode ``supports_snapshots()`` to ``False`` and raised
``NotImplementedError`` from ``create_snapshot_table_if_not_exists`` -- the
only one of the 18 providers to do so. ``ProviderInterface`` reserves that
override for providers whose snapshot repository queries *cannot be executed*;
SQLite's execute fine, so the deviation was removed.

The first test below is the one with teeth: it drives the real provider
against a real SQLite database file and inspects the resulting table through
``PRAGMA table_info``. A capability assertion on its own cannot detect a
capability that misstates the engine.
"""

import pytest

from dblift.config import DbliftConfig
from dblift.core.logger import NullLog
from dblift.db.plugins.sqlite.provider import SQLiteProvider

# Mirrors db/constants.py (SNAPSHOT_ID_VARCHAR_SIZE=64 / CHECKSUM_VARCHAR_SIZE=128)
# as rendered by BaseQuirks.build_snapshot_table_ddl, which SqliteQuirks
# inherits unmodified.
EXPECTED_SNAPSHOT_COLUMNS = {
    "snapshot_id": "VARCHAR(64)",
    "captured_at": "VARCHAR(64)",
    "checksum": "VARCHAR(128)",
    "model_data": "TEXT",
}


def _make_provider(tmp_path):
    config = DbliftConfig.from_dict(
        {
            "database": {"type": "sqlite", "path": str(tmp_path / "app.db")},
            "migrations": {
                "directory": str(tmp_path),
                "table": "dblift_schema_history",
            },
        }
    )
    return SQLiteProvider(config, NullLog())


@pytest.mark.unit
def test_sqlite_creates_snapshot_table_with_expected_columns(tmp_path):
    """The snapshot table is really created in a real SQLite database file.

    Asserts the physical shape via ``PRAGMA table_info`` rather than trusting
    a capability flag -- this is what would catch the capability being wrong
    about the engine.
    """
    provider = _make_provider(tmp_path)

    try:
        provider.create_connection()

        provider.create_snapshot_table_if_not_exists("main", "dblift_schema_snapshots")

        rows = provider.query_executor.execute_query(
            provider._get_connection(),
            "SELECT name FROM sqlite_master "
            "WHERE type = 'table' AND name = 'dblift_schema_snapshots'",
        )
        assert rows, "snapshot table was not created in the SQLite database"

        columns = provider.query_executor.execute_query(
            provider._get_connection(),
            "PRAGMA table_info(dblift_schema_snapshots)",
        )
        actual = {row["name"]: row["type"].upper() for row in columns}
        assert actual == EXPECTED_SNAPSHOT_COLUMNS

        by_name = {row["name"]: row for row in columns}
        assert by_name["snapshot_id"]["pk"] == 1
        for column in ("captured_at", "checksum", "model_data"):
            assert by_name[column]["notnull"] == 1, f"{column} should be NOT NULL"
    finally:
        provider.close()


@pytest.mark.unit
def test_sqlite_snapshot_table_creation_is_idempotent(tmp_path):
    """A second call must not raise -- callers invoke this on every capture."""
    provider = _make_provider(tmp_path)

    try:
        provider.create_connection()

        provider.create_snapshot_table_if_not_exists("main", "dblift_schema_snapshots")
        provider.create_snapshot_table_if_not_exists("main", "dblift_schema_snapshots")

        rows = provider.query_executor.execute_query(
            provider._get_connection(),
            "SELECT name FROM sqlite_master "
            "WHERE type = 'table' AND name = 'dblift_schema_snapshots'",
        )
        assert len(rows) == 1
    finally:
        provider.close()


@pytest.mark.unit
def test_sqlite_provider_declares_snapshots_supported(tmp_path):
    provider = _make_provider(tmp_path)

    assert provider.supports_snapshots() is True


@pytest.mark.unit
def test_sqlite_provider_does_not_override_snapshot_capability():
    """Match the sibling-plugin convention (cf. the MariaDB plugin test).

    Snapshot behaviour is expressed through quirks, not by overriding the
    capability or the table hook on the provider.
    """
    assert "supports_snapshots" not in SQLiteProvider.__dict__
    assert "create_snapshot_table_if_not_exists" not in SQLiteProvider.__dict__
