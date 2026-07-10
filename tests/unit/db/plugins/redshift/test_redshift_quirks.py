"""Redshift dialect quirks."""

from db.plugins.redshift.quirks import RedshiftQuirks


def test_redshift_snapshot_table_uses_wide_varchar_payload() -> None:
    ddl = RedshiftQuirks().build_snapshot_table_ddl(
        '"app"."dblift_schema_snapshots"',
        snapshot_id_size=255,
        checksum_size=128,
    )

    assert "model_data VARCHAR(MAX) NOT NULL" in ddl
    assert "model_data TEXT" not in ddl
