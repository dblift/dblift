"""Oracle quirks behavior."""

import pytest

from dblift.db.plugins.oracle.quirks import OracleQuirks


def test_build_snapshot_table_ddl_is_not_owned_by_oracle_plugin() -> None:
    with pytest.raises(NotImplementedError):
        OracleQuirks().build_snapshot_table_ddl('"APP"."DBLIFT_SCHEMA_SNAPSHOTS"', 255, 128)


def test_oracle_compat_snapshot_ddl_is_clob_plain_create():
    from dblift.db.plugins.oracle.quirks import OracleQuirks

    ddl = OracleQuirks().build_provider_compat_snapshot_ddl("S.SNAP", 100, 128)
    assert ddl == (
        "CREATE TABLE S.SNAP ("
        "SNAPSHOT_ID VARCHAR2(100) PRIMARY KEY, "
        "CAPTURED_AT VARCHAR2(100) NOT NULL, "
        "CHECKSUM VARCHAR2(128) NOT NULL, "
        "MODEL_DATA CLOB NOT NULL)"
    )


def test_reference_queries_bind_the_catalog_spelling():
    quirks = OracleQuirks()
    assert quirks.fk_reference_bind_params('"MYSCHEMA"', "ORDERS", "ID") == [
        "MYSCHEMA",
        "MYSCHEMA",
        "ORDERS",
        "ID",
    ]
    assert quirks.fk_reference_bind_params('"myschema"', "ORDERS", "ID") == [
        "myschema",
        "myschema",
        "ORDERS",
        "ID",
    ]
    _sql, params = quirks.index_reference_query('"myschema"', "ORDERS", "ID")
    assert params == ["myschema", "ORDERS", "ID"]


def test_oracle_does_not_skip_existence_check():
    from dblift.db.plugins.oracle.quirks import OracleQuirks

    assert OracleQuirks().provider_compat_snapshot_skips_existence_check is False


@pytest.mark.parametrize(
    "obj_type, expected",
    [
        ("TABLE", 'DROP TABLE IF EXISTS "S"."T" CASCADE CONSTRAINTS'),
        ("VIEW", 'DROP VIEW IF EXISTS "S"."T"'),
        ("MATERIALIZED_VIEW", 'DROP MATERIALIZED VIEW IF EXISTS "S"."T"'),
        ("INDEX", 'DROP INDEX IF EXISTS "S"."T"'),
        ("SEQUENCE", 'DROP SEQUENCE IF EXISTS "S"."T"'),
        ("PROCEDURE", 'DROP PROCEDURE IF EXISTS "S"."T"'),
        ("FUNCTION", 'DROP FUNCTION IF EXISTS "S"."T"'),
        ("TRIGGER", 'DROP TRIGGER IF EXISTS "S"."T"'),
    ],
)
def test_oracle_render_drop_for_object_uses_native_if_exists(obj_type, expected):
    result = OracleQuirks().render_drop_for_object(obj_type, '"T"', '"S".', None)
    assert result == expected
