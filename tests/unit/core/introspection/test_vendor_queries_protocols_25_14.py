"""Story 25-14 ISP-01 — VendorMetadataQueries Protocol interfaces.

Tests verify:
AC#1: Five focused Protocol classes exist in vendor_queries_protocols.py.
AC#2: All concrete VendorMetadataQueries subclasses satisfy all five protocols.
AC#3: Protocols are runtime_checkable (isinstance works).
"""

import pytest

from core.introspection.vendor_queries_protocols import (
    IConstraintQueries,
    IIndexQueries,
    IStoredObjectQueries,
    ITableQueries,
    IViewQueries,
)

ALL_PROTOCOLS = [
    ITableQueries,
    IViewQueries,
    IConstraintQueries,
    IIndexQueries,
    IStoredObjectQueries,
]

PROTOCOL_NAMES = [p.__name__ for p in ALL_PROTOCOLS]


@pytest.mark.unit
class TestISP01ProtocolsExist:
    """AC#1 — five Protocol classes exist and are importable."""

    def test_all_protocols_importable(self):
        for proto in ALL_PROTOCOLS:
            assert proto is not None, f"{proto.__name__} should be importable"

    def test_protocol_names(self):
        expected = {
            "ITableQueries",
            "IViewQueries",
            "IConstraintQueries",
            "IIndexQueries",
            "IStoredObjectQueries",
        }
        actual = {p.__name__ for p in ALL_PROTOCOLS}
        assert actual == expected


@pytest.mark.unit
class TestISP01RuntimeCheckable:
    """AC#3 — protocols are @runtime_checkable."""

    def test_protocols_are_runtime_checkable(self):
        # If not runtime_checkable, isinstance() raises TypeError
        for proto in ALL_PROTOCOLS:
            try:
                isinstance(object(), proto)
            except TypeError as e:
                pytest.fail(f"{proto.__name__} is not runtime_checkable: {e}")


@pytest.mark.unit
class TestISP01ConcreteImplementations:
    """AC#2 — concrete vendor query classes satisfy all five protocols."""

    @pytest.fixture
    def postgresql_queries(self):
        from db.plugins.postgresql.introspection.postgresql_queries import (
            PostgreSQLMetadataQueries,
        )

        return PostgreSQLMetadataQueries()

    @pytest.fixture
    def oracle_queries(self):
        from db.plugins.oracle.introspection.oracle_queries import OracleMetadataQueries

        return OracleMetadataQueries()

    @pytest.fixture
    def mysql_queries(self):
        from db.plugins.mysql.introspection.mysql_queries import MySQLMetadataQueries

        return MySQLMetadataQueries()

    @pytest.fixture
    def sqlserver_queries(self):
        from db.plugins.sqlserver.introspection.sqlserver_queries import SQLServerMetadataQueries

        return SQLServerMetadataQueries()

    @pytest.fixture
    def db2_queries(self):
        from db.plugins.db2.introspection.db2_queries import DB2MetadataQueries

        return DB2MetadataQueries()

    @pytest.mark.parametrize("proto", ALL_PROTOCOLS, ids=PROTOCOL_NAMES)
    def test_postgresql_satisfies_all_protocols(self, postgresql_queries, proto):
        assert isinstance(
            postgresql_queries, proto
        ), f"PostgreSQLMetadataQueries does not satisfy {proto.__name__}"

    @pytest.mark.parametrize("proto", ALL_PROTOCOLS, ids=PROTOCOL_NAMES)
    def test_oracle_satisfies_all_protocols(self, oracle_queries, proto):
        assert isinstance(
            oracle_queries, proto
        ), f"OracleMetadataQueries does not satisfy {proto.__name__}"

    @pytest.mark.parametrize("proto", ALL_PROTOCOLS, ids=PROTOCOL_NAMES)
    def test_mysql_satisfies_all_protocols(self, mysql_queries, proto):
        assert isinstance(
            mysql_queries, proto
        ), f"MySQLMetadataQueries does not satisfy {proto.__name__}"

    @pytest.mark.parametrize("proto", ALL_PROTOCOLS, ids=PROTOCOL_NAMES)
    def test_sqlserver_satisfies_all_protocols(self, sqlserver_queries, proto):
        assert isinstance(
            sqlserver_queries, proto
        ), f"SQLServerMetadataQueries does not satisfy {proto.__name__}"

    @pytest.mark.parametrize("proto", ALL_PROTOCOLS, ids=PROTOCOL_NAMES)
    def test_db2_satisfies_all_protocols(self, db2_queries, proto):
        assert isinstance(
            db2_queries, proto
        ), f"DB2MetadataQueries does not satisfy {proto.__name__}"
