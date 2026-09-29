"""Redshift dialect quirks."""

from dblift.db.plugins.redshift.quirks import RedshiftQuirks


def test_redshift_snapshot_table_uses_wide_varchar_payload() -> None:
    ddl = RedshiftQuirks().build_snapshot_table_ddl(
        '"app"."dblift_schema_snapshots"',
        snapshot_id_size=255,
        checksum_size=128,
    )

    assert "model_data VARCHAR(MAX) NOT NULL" in ddl
    assert "model_data TEXT" not in ddl


def test_redshift_uses_its_own_sqlglot_dialect_not_postgres() -> None:
    assert RedshiftQuirks().sqlglot_dialect == "redshift"
