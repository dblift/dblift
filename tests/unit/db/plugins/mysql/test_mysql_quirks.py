"""ADR-26: MySQL provider-compat snapshot DDL lives in MysqlQuirks."""

import pytest

from db.plugins.mysql.quirks import MysqlQuirks

pytestmark = [pytest.mark.unit]


def test_mysql_compat_snapshot_ddl_is_innodb_if_not_exists():
    ddl = MysqlQuirks().build_provider_compat_snapshot_ddl("db.snap", 100, 128)
    assert ddl == (
        "CREATE TABLE IF NOT EXISTS db.snap ("
        "snapshot_id VARCHAR(100) PRIMARY KEY, "
        "captured_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, "
        "checksum VARCHAR(128), "
        "model_data LONGTEXT NOT NULL"
        ") ENGINE=InnoDB"
    )


def test_mysql_skips_existence_check():
    assert MysqlQuirks().provider_compat_snapshot_skips_existence_check is True
