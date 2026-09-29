"""SQL Server quirks unit tests."""

import pytest

from dblift.db.plugins.sqlserver.quirks import SqlserverQuirks


def test_sqlserver_quirks_reject_snapshot_table_ddl() -> None:
    with pytest.raises(NotImplementedError, match="SQL Server snapshots are not provider-owned"):
        SqlserverQuirks().build_snapshot_table_ddl("dbo.dblift_schema_snapshots", 128, 64)


@pytest.mark.parametrize("nullable, suffix", [(False, "NOT NULL"), (True, "NULL")])
@pytest.mark.parametrize("type_source", ["expected", "diff", "both"])
def test_nullable_change_includes_type_and_preserves_precheck(nullable, suffix, type_source):
    from types import SimpleNamespace

    diff = SimpleNamespace(nullable_diff=(nullable, not nullable))
    if type_source in ("expected", "both"):
        diff.expected_data_type = "VARCHAR(20)"
    if type_source in ("diff", "both"):
        diff.data_type_diff = ("VARCHAR(99)" if type_source == "both" else "VARCHAR(20)", "INT")
    statement = SqlserverQuirks().render_column_nullable_change(diff, "[t]", "[c]", "sqlserver")
    assert statement.sql == f"ALTER TABLE [t] ALTER COLUMN [c] VARCHAR(20) {suffix};"
    if not nullable:
        assert statement.pre_check == "SELECT COUNT(*) FROM [t] WHERE [c] IS NULL;"
        assert statement.error_if_check_fails is True
        assert statement.error_message == "Cannot set NOT NULL: column contains NULL values"
    else:
        assert statement.pre_check is None


@pytest.mark.parametrize("nullable", [False, True])
def test_nullable_change_without_known_type_is_not_renderable(nullable):
    from types import SimpleNamespace

    diff = SimpleNamespace(nullable_diff=(nullable, not nullable), expected_data_type=None)
    assert SqlserverQuirks().render_column_nullable_change(diff, "[t]", "[c]", "sqlserver") is None
