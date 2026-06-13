"""Unit coverage for integration-test fixture helpers."""

from pathlib import Path
from types import SimpleNamespace

from sqlalchemy.engine import make_url

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


def test_integration_workflow_sets_mysql_override_port():
    workflow = Path(".github/workflows/integration-tests-new.yml").read_text()

    assert "DBLIFT_MYSQL_PORT: 3307" in workflow


def test_integration_workflow_installs_native_driver_extras():
    workflow = Path(".github/workflows/integration-tests-new.yml").read_text()

    assert 'python -m pip install -e ".[dev,all]"' in workflow
    assert 'python -m pip install -e ".[dev]"' not in workflow


def test_sqlserver_diff_config_uses_sqlalchemy_query_syntax():
    config = Path("tests/integration/config/diff_sqlserver.yaml").read_text()
    url_line = next(line for line in config.splitlines() if line.strip().startswith("url:"))
    url = make_url(url_line.split("url:", 1)[1].strip())

    assert ";" not in (url.database or "")
    assert url.database == "dblift"
    assert url.query["encrypt"] == "false"
    # trustServerCertificate may or may not be present depending on config; not required for syntax test
