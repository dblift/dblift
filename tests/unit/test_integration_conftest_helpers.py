"""Unit coverage for integration-test fixture helpers."""

from types import SimpleNamespace

from tests.integration import conftest as integration_conftest


def test_mysql_port_override_applies_without_external_host():
    configs = {"mysql": {"port": 3306}}

    integration_conftest._apply_mysql_port_override(configs, "3307")

    assert configs["mysql"]["port"] == 3307


def test_mysql_port_override_ignores_invalid_values():
    configs = {"mysql": {"port": 3306}}

    integration_conftest._apply_mysql_port_override(configs, "not-a-port")

    assert configs["mysql"]["port"] == 3306


def test_ensure_schema_before_cleanup_creates_schema_and_commits():
    calls = []

    provider = SimpleNamespace(
        create_schema_if_not_exists=lambda schema: calls.append(("create", schema)),
        commit_transaction=lambda: calls.append(("commit", None)),
    )

    integration_conftest._ensure_schema_before_cleanup(provider, "postgresql", "TEST_SCHEMA")

    assert calls == [("create", "TEST_SCHEMA"), ("commit", None)]


def test_ensure_schema_before_cleanup_skips_database_scoped_engines():
    calls = []
    provider = SimpleNamespace(
        create_schema_if_not_exists=lambda schema: calls.append(("create", schema)),
        commit_transaction=lambda: calls.append(("commit", None)),
    )

    integration_conftest._ensure_schema_before_cleanup(provider, "mysql", "TEST_SCHEMA")

    assert calls == []


def test_mysql_test_schema_uses_configured_database():
    schema = integration_conftest._test_schema_for_service("mysql", {"database": "testdb"})

    assert schema == "testdb"


def test_schema_scoped_engines_use_test_schema():
    schema = integration_conftest._test_schema_for_service("postgresql", {"database": "testdb"})

    assert schema == "TEST_SCHEMA"
