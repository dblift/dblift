"""Oracle quirks behavior."""

import pytest

from db.plugins.oracle.quirks import OracleQuirks


def test_build_snapshot_table_ddl_is_not_owned_by_oracle_plugin() -> None:
    with pytest.raises(NotImplementedError):
        OracleQuirks().build_snapshot_table_ddl('"APP"."DBLIFT_SCHEMA_SNAPSHOTS"', 255, 128)


def test_oracle_compat_snapshot_ddl_is_clob_plain_create():
    from db.plugins.oracle.quirks import OracleQuirks

    ddl = OracleQuirks().build_provider_compat_snapshot_ddl("S.SNAP", 100, 128)
    assert ddl == (
        "CREATE TABLE S.SNAP ("
        "SNAPSHOT_ID VARCHAR2(100) PRIMARY KEY, "
        "CAPTURED_AT VARCHAR2(100) NOT NULL, "
        "CHECKSUM VARCHAR2(128) NOT NULL, "
        "MODEL_DATA CLOB NOT NULL)"
    )


def test_oracle_does_not_skip_existence_check():
    from db.plugins.oracle.quirks import OracleQuirks

    assert OracleQuirks().provider_compat_snapshot_skips_existence_check is False
