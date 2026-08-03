"""DB2 quirks behavior."""

import pytest

from db.plugins.db2.quirks import Db2Quirks


def test_build_snapshot_table_ddl_refuses_db2_snapshot_ddl() -> None:
    with pytest.raises(NotImplementedError):
        Db2Quirks().build_snapshot_table_ddl('"APP"."DBLIFT_SCHEMA_SNAPSHOTS"', 255, 128)


def test_build_data_history_table_ddl_declares_id_not_null() -> None:
    # DB2 rejects a PRIMARY KEY column without an explicit NOT NULL
    # (SQL0542N) — unlike PG/MySQL/SQLite, where PRIMARY KEY implies it.
    ddl = Db2Quirks().build_data_history_table_ddl('"APP"."DBLIFT_DATA_HISTORY"', 100, 128)
    assert "id VARCHAR(100) NOT NULL PRIMARY KEY" in ddl
