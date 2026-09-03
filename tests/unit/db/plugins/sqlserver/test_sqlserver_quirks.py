"""SQL Server quirks unit tests."""

import pytest

from dblift.db.plugins.sqlserver.quirks import SqlserverQuirks


def test_sqlserver_quirks_reject_snapshot_table_ddl() -> None:
    with pytest.raises(NotImplementedError, match="SQL Server snapshots are not provider-owned"):
        SqlserverQuirks().build_snapshot_table_ddl("dbo.dblift_schema_snapshots", 128, 64)
