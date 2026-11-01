"""``table_exists`` must see a table the connected account cannot read."""

import pytest
from sqlalchemy.exc import OperationalError, ProgrammingError

from dblift.db.plugins.mariadb.provider import MariadbProvider
from dblift.db.plugins.mysql.provider import MySqlProvider


def _error(code, message):
    return ProgrammingError("SELECT", None, Exception(code, message))


class _Mixin:
    def __init__(self, catalog_rows, probe_error=None):
        self.sql = []
        self.catalog_rows = catalog_rows
        self.probe_error = probe_error

    def execute_query(self, sql, params=None):
        self.sql.append(sql)
        if "information_schema" in sql:
            return self.catalog_rows
        if self.probe_error is not None:
            raise self.probe_error
        return []


class _MySql(_Mixin, MySqlProvider):
    pass


class _Maria(_Mixin, MariadbProvider):
    pass


@pytest.fixture(params=[_MySql, _Maria], ids=["mysql", "mariadb"])
def provider_class(request):
    return request.param


def test_a_listed_table_is_not_probed(provider_class):
    provider = provider_class([{"TABLE_NAME": "h"}])

    assert provider.table_exists("app", "h") is True

    assert len(provider.sql) == 1


def test_an_unlisted_table_the_account_cannot_select_exists(provider_class):
    """``information_schema.TABLES`` lists only tables the account holds a privilege
    on, so a history table without one reads as absent and ``info`` reports every
    migration pending. The read says ``denied`` (1142), not ``missing`` (1146)."""
    provider = provider_class(
        [], _error(1142, "SELECT command denied to user 'r'@'h' for table 'h'")
    )

    assert provider.table_exists("app", "h") is True

    assert provider.sql[-1] == "SELECT 1 FROM `app`.`h` WHERE 1=0"


def test_an_unlisted_table_the_account_may_not_see_at_all_exists(provider_class):
    provider = provider_class([], _error(1044, "Access denied for user 'r'@'h' to database 'app'"))

    assert provider.table_exists("app", "h") is True


def test_an_unlisted_table_missing_from_the_database_is_absent(provider_class):
    provider = provider_class([], _error(1146, "Table 'app.h' doesn't exist"))

    assert provider.table_exists("app", "h") is False


def test_an_unlisted_table_in_a_database_that_does_not_exist_is_absent(provider_class):
    """A dry run before the first deploy: the database is created by ``migrate``."""
    provider = provider_class([], _error(1049, "Unknown database 'app'"))

    assert provider.table_exists("app", "h") is False


def test_a_probe_that_reads_means_the_table_exists(provider_class):
    """A table the catalog does not list but a SELECT reads (a temporary table)."""
    provider = provider_class([])

    assert provider.table_exists("app", "h") is True


def test_any_other_probe_failure_is_raised_not_read_as_absent(provider_class):
    lost = OperationalError("SELECT", None, Exception(2013, "Lost connection to server"))
    provider = provider_class([], lost)

    with pytest.raises(OperationalError):
        provider.table_exists("app", "h")
