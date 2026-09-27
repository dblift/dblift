"""ADR-26 E: Flyway-source-table case-sensitivity quirk.

The import-flyway command reads a *Flyway* source table whose name is
exact-case on Oracle and DB2 (where DBLift's own history names are
uppercased by ``get_applied_migrations``). The predicate that selects the verbatim-query
path used to be ``db_type == "oracle"``; it now lives on a quirks
capability so framework code names no dialect.
"""

from dblift.db.base_quirks import BaseQuirks
from dblift.db.plugins.db2.quirks import Db2Quirks
from dblift.db.plugins.mysql.quirks import MysqlQuirks
from dblift.db.plugins.oracle.quirks import OracleQuirks
from dblift.db.plugins.postgresql.quirks import PostgresqlQuirks
from dblift.db.plugins.sqlite.quirks import SqliteQuirks
from dblift.db.plugins.sqlserver.quirks import SqlserverQuirks


def test_base_default_false():
    assert BaseQuirks("").flyway_source_table_case_sensitive is False


def test_uppercase_folding_dialects_true():
    # Flyway creates a quoted lowercase "flyway_schema_history" on both, which
    # get_applied_migrations (uppercasing the name) cannot find.
    assert OracleQuirks().flyway_source_table_case_sensitive is True
    assert Db2Quirks().flyway_source_table_case_sensitive is True


def test_other_dialects_false():
    assert PostgresqlQuirks().flyway_source_table_case_sensitive is False
    assert MysqlQuirks().flyway_source_table_case_sensitive is False
    assert SqlserverQuirks().flyway_source_table_case_sensitive is False
    assert SqliteQuirks().flyway_source_table_case_sensitive is False
