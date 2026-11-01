"""``table_exists`` must see a table the connected login cannot read."""

import pytest
from sqlalchemy.exc import OperationalError, ProgrammingError

from dblift.db.plugins.sqlserver.provider import SqlServerProvider


def _error(code, message):
    return ProgrammingError("SELECT", None, Exception(code, message.encode()))


class _Provider(SqlServerProvider):
    def __init__(self, catalog_count, probe_error=None):
        self.sql = []
        self.catalog_count = catalog_count
        self.probe_error = probe_error

    def execute_query(self, sql, params=None):
        self.sql.append(sql)
        if "sys.tables" in sql:
            return [{"cnt": self.catalog_count}]
        if self.probe_error is not None:
            raise self.probe_error
        return []


def test_a_listed_table_is_not_probed():
    provider = _Provider(1)

    assert provider.table_exists("app", "h") is True

    assert len(provider.sql) == 1


def test_an_unlisted_table_the_login_cannot_select_exists():
    """``sys.tables`` shows only objects the login holds a permission on, so a
    history table without one reads as absent and ``info`` reports every migration
    pending. The read says ``denied`` (229), not ``invalid object name`` (208)."""
    provider = _Provider(0, _error(229, "The SELECT permission was denied on the object 'h'"))

    assert provider.table_exists("app", "h") is True

    assert provider.sql[-1] == "SELECT 1 FROM [app].[h] WHERE 1=0"


def test_an_unlisted_table_missing_from_the_database_is_absent():
    provider = _Provider(0, _error(208, "Invalid object name 'app.h'."))

    assert provider.table_exists("app", "h") is False


def test_a_probe_that_reads_means_the_table_exists():
    """A table the catalog does not list but a SELECT reads (a temporary table)."""
    assert _Provider(0).table_exists("app", "h") is True


def test_any_other_probe_failure_is_raised_not_read_as_absent():
    provider = _Provider(0, OperationalError("SELECT", None, Exception(20003, b"timeout")))

    with pytest.raises(OperationalError):
        provider.table_exists("app", "h")
