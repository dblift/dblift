"""ADR-26 E: Oracle Flyway-source-table case-sensitivity quirk.

The import-flyway command reads a *Flyway* source table whose name is
exact-case on Oracle (where DBLift's own history names are uppercased by
``get_applied_migrations``). The predicate that selects the verbatim-query
path used to be ``db_type == "oracle"``; it now lives on a quirks
capability so framework code names no dialect.
"""

from db.base_quirks import BaseQuirks
from db.plugins.db2.quirks import Db2Quirks
from db.plugins.mysql.quirks import MysqlQuirks
from db.plugins.oracle.quirks import OracleQuirks
from db.plugins.postgresql.quirks import PostgresqlQuirks
from db.plugins.sqlite.quirks import SqliteQuirks
from db.plugins.sqlserver.quirks import SqlserverQuirks


def test_base_default_false():
    assert BaseQuirks("").flyway_source_table_case_sensitive is False


def test_oracle_true():
    assert OracleQuirks().flyway_source_table_case_sensitive is True


def test_non_oracle_dialects_false():
    # DB2 also uppercases identifiers, but the verbatim-query path is
    # Oracle-only by design — DB2 must keep the get_applied_migrations path.
    assert Db2Quirks().flyway_source_table_case_sensitive is False
    assert PostgresqlQuirks().flyway_source_table_case_sensitive is False
    assert MysqlQuirks().flyway_source_table_case_sensitive is False
    assert SqlserverQuirks().flyway_source_table_case_sensitive is False
    assert SqliteQuirks().flyway_source_table_case_sensitive is False
