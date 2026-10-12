"""External integration runs require an explicitly selected MySQL database."""

import pytest

from tests.integration import conftest as integration_config


@pytest.mark.parametrize("database", [None, ""])
def test_external_mysql_requires_explicit_database(monkeypatch, database):
    monkeypatch.setattr(integration_config, "EXTERNAL_MYSQL_HOST", "test-host")
    monkeypatch.setattr(integration_config, "EXTERNAL_MYSQL_DATABASE", database)

    with pytest.raises(pytest.fail.Exception, match="DBLIFT_MYSQL_DATABASE"):
        integration_config.db_configs.__wrapped__()


def test_external_mysql_keeps_explicit_database(monkeypatch):
    monkeypatch.setattr(integration_config, "EXTERNAL_MYSQL_HOST", "test-host")
    monkeypatch.setattr(integration_config, "EXTERNAL_MYSQL_DATABASE", "isolated_test_db")

    assert integration_config.db_configs.__wrapped__()["mysql"]["database"] == "isolated_test_db"
