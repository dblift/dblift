import os
from unittest.mock import patch

import pytest

from config.dblift_config import DbliftConfig, deep_merge_dicts, load_config
from config.errors import ConfigurationError


@pytest.mark.unit
def test_from_file_invalid_yaml(tmp_path):
    bad_file = tmp_path / "bad.yaml"
    bad_file.write_text(":not yaml:")
    with pytest.raises(Exception):
        DbliftConfig.from_file(str(bad_file))


@pytest.mark.unit
def test_from_file_missing_file():
    with pytest.raises(FileNotFoundError):
        DbliftConfig.from_file("/no/such/file.yaml")


@pytest.mark.unit
def test_from_file_empty_file(tmp_path):
    empty_file = tmp_path / "empty.yaml"
    empty_file.write_text("")
    with pytest.raises(Exception):
        DbliftConfig.from_file(str(empty_file))


@pytest.mark.unit
def test_from_dict_missing_extra_fields():
    # Missing database
    with pytest.raises(Exception):
        DbliftConfig.from_dict({})
    # Extra fields are ignored
    d = {
        "database": {
            "url": "postgresql+psycopg://localhost:5432/db",
            "username": "pg",
            "password": "pw",
        },
        "extra_field": 123,
    }
    config = DbliftConfig.from_dict(d)
    assert hasattr(config, "database")


@pytest.mark.unit
def test_from_dict_invalid_log_level():
    d = {
        "database": {
            "url": "postgresql+psycopg://localhost:5432/db",
            "username": "pg",
            "password": "pw",
        },
        "logging": {"level": "BADLEVEL"},
    }
    with pytest.raises(ValueError):
        DbliftConfig.from_dict(d)


@pytest.mark.unit
def test_merge_partial_and_none():
    base = DbliftConfig.from_dict(
        {
            "database": {
                "url": "postgresql+psycopg://localhost:5432/db",
                "username": "pg",
                "password": "pw",
            }
        }
    )
    # Merge with None
    base.merge({})
    assert base.database.type == "postgresql"
    # Merge with partial dict
    base.merge({"logging": {"level": "DEBUG"}})
    assert base.logging.level == "DEBUG"
    # Merge with malformed dict (should not raise)
    base.merge({"not_a_real_section": {"foo": "bar"}})
    assert hasattr(base, "database")


@pytest.mark.unit
def test_to_dict_optional_fields():
    base = DbliftConfig.from_dict(
        {
            "database": {
                "url": "postgresql+psycopg://localhost:5432/db",
                "username": "pg",
                "password": "pw",
            }
        }
    )
    d = base.to_dict()
    assert "database" in d
    # Add optional fields
    base.tags = "t1"
    base.placeholders = {"x": "y"}
    d = base.to_dict()
    assert d["tags"] == "t1"
    assert d["placeholders"]["x"] == "y"


@pytest.mark.unit
def test_from_env_dict_and_args_dict_edge_cases(monkeypatch):
    # No env set
    monkeypatch.delenv("DBLIFT_DB_URL", raising=False)
    monkeypatch.delenv("DBLIFT_DB_USER", raising=False)
    monkeypatch.delenv("DBLIFT_DB_PASSWORD", raising=False)
    env = DbliftConfig.from_env_dict()
    # With no DBLIFT_DB_* env set, the "database" key is intentionally absent
    # so ``if env_dict:`` at callers is a true emptiness check (not a no-op
    # merge through ``BaseDatabaseConfig.create()``).
    assert "database" not in env
    # Empty args
    args = {}
    argd = DbliftConfig.from_args_dict(args)
    assert "database" not in argd


@pytest.mark.unit
def test_deep_merge_dicts_edge_cases():
    # Nested merge
    base = {"a": {"b": 1}, "c": 2}
    override = {"a": {"b": 9, "d": 3}, "c": None}
    merged = deep_merge_dicts(base, override)
    assert merged["a"]["b"] == 9
    assert merged["a"]["d"] == 3
    assert merged["c"] == 2
    # Override with empty dict
    merged = deep_merge_dicts(base, {})
    assert merged["a"]["b"] == 1
    # Override with None values
    merged = deep_merge_dicts(base, {"a": None})
    assert merged["a"] == {"b": 1}


@pytest.mark.unit
def test_load_config_file_exists_and_valid(tmp_path):
    os.environ.pop("DBLIFT_DB_USER", None)
    os.environ.pop("DBLIFT_DB_URL", None)
    # Simulate a config file that exists and is valid
    config_file = tmp_path / "config.yaml"
    config_file.write_text("""
database:
  url: postgresql+psycopg://localhost:5432/db
  username: testuser
  password: testpw
""")
    with patch("os.path.exists", return_value=True):
        config = load_config(str(config_file), None)
        assert config.database.username == "testuser"
        assert config.database.url.startswith("postgresql+psycopg")


@pytest.mark.unit
def test_load_config_file_exists_and_invalid(tmp_path):
    os.environ.pop("DBLIFT_DB_USER", None)
    os.environ.pop("DBLIFT_DB_URL", None)
    # An explicit --config pointing at an unparseable file must fail loudly rather than
    # silently fall back to defaults (otherwise typos in --config are invisible).
    config_file = tmp_path / "bad.yaml"
    config_file.write_text("database: [")
    with patch("os.path.exists", return_value=True):
        with pytest.raises(RuntimeError, match="Error loading config file"):
            load_config(str(config_file), None)


@pytest.mark.unit
@pytest.mark.parametrize("exc_cls", [AttributeError, IndexError])
def test_load_config_wraps_data_shape_errors(tmp_path, exc_cls):
    # Data-shape errors raised during YAML load / merge (e.g. .get() on None,
    # missing list element) must be wrapped in the friendly RuntimeError, not
    # propagate as raw tracebacks.
    config_file = tmp_path / "shape.yaml"
    config_file.write_text("key: value")
    with patch(
        "config.dblift_config.DbliftConfig.load_config_data_from_yaml",
        side_effect=exc_cls("boom"),
    ):
        with pytest.raises(RuntimeError, match="Error loading config file"):
            load_config(str(config_file), None)


@pytest.mark.unit
def test_load_config_file_not_exists(tmp_path):
    os.environ.pop("DBLIFT_DB_USER", None)
    os.environ.pop("DBLIFT_DB_URL", None)
    # An explicit --config path that does not exist is a user error, not a reason to
    # silently fall back to defaults.
    config_file = tmp_path / "nofile.yaml"
    with patch("os.path.exists", return_value=False):
        with pytest.raises(FileNotFoundError, match="Config file not found"):
            load_config(str(config_file), None)


@pytest.mark.unit
def test_load_config_no_path_returns_defaults():
    os.environ.pop("DBLIFT_DB_USER", None)
    os.environ.pop("DBLIFT_DB_URL", None)
    with pytest.raises(ConfigurationError, match="No configuration source provided"):
        load_config("", None)


@pytest.mark.unit
def test_load_config_validate_sql_requires_dialect_without_database_type():
    class Args:
        command = "validate-sql"
        dialect = None

    with patch.dict(os.environ, {}, clear=True):
        with pytest.raises(ConfigurationError) as exc:
            load_config("", Args())

    message = str(exc.value)
    assert "validate-sql requires --dialect" in message
    assert "--db-url" not in message


@pytest.mark.unit
def test_load_config_validate_sql_dialect_uses_lint_placeholder_config():
    class Args:
        command = "validate-sql"
        dialect = "postgresql"

    with patch.dict(os.environ, {}, clear=True):
        config = load_config("", Args())

    assert config.database.type == "postgresql"
    assert config.database.url == "postgresql://127.0.0.1:5432/dblift_validate_sql"


@pytest.mark.unit
def test_load_config_validate_sql_sqlite_dialect_uses_lint_placeholder_config():
    class Args:
        command = "validate-sql"
        dialect = "sqlite"

    with patch.dict(os.environ, {}, clear=True):
        config = load_config("", Args())

    assert config.database.type == "sqlite"
    assert getattr(config.database, "path", None) == ":memory:"


@pytest.mark.unit
def test_load_config_validate_sql_db2_dialect_uses_native_placeholder_config():
    class Args:
        command = "validate-sql"
        dialect = "db2"

    with patch.dict(os.environ, {}, clear=True):
        config = load_config("", Args())

    assert config.database.type == "db2"
    assert config.database.database == "dblift_validate_sql"
    assert config.database.host == "127.0.0.1"
    assert config.database.url == "ibm_db_sa://127.0.0.1:50000/dblift_validate_sql"


@pytest.mark.unit
def test_from_dict_secret_uri_as_database_url_does_not_raise(monkeypatch):
    """database.url: vault://... must not raise 'Invalid legacy URL' when resolve_secrets=False."""
    config = DbliftConfig.from_dict(
        {"database": {"url": "vault://secret/data/prod/db#url", "schema": "public"}},
        resolve_secrets=False,
    )
    assert config is not None
    assert config.database is not None


@pytest.mark.unit
def test_from_dict_typed_secret_uri_as_database_url_does_not_raise():
    """database.type set + database.url: vault://... must not be parsed as native."""
    config = DbliftConfig.from_dict(
        {
            "database": {
                "type": "postgresql",
                "url": "vault://secret/data/prod/db#url",
                "schema": "public",
            }
        },
        resolve_secrets=False,
    )
    assert config is not None
    assert config.database is not None
    assert config.database.url == "vault://secret/data/prod/db#url"
    assert getattr(config.database, "host", None) is None
    assert getattr(config.database, "database", None) is None


@pytest.mark.unit
def test_from_dict_oracle_host_database_uses_database_as_service_name():
    config = DbliftConfig.from_dict(
        {
            "database": {
                "type": "oracle",
                "host": "db.example.com",
                "database": "ORCLPDB1",
                "username": "system",
                "password": "oracle",
            }
        }
    )

    assert config.database.database == "ORCLPDB1"
    assert config.database.service_name == "ORCLPDB1"
    assert "service_name=ORCLPDB1" in config.database.build_database_url()


@pytest.mark.unit
def test_from_dict_db2_host_database_is_valid_connection_identifier():
    config = DbliftConfig.from_dict(
        {
            "database": {
                "type": "db2",
                "host": "db.example.com",
                "database": "SAMPLE",
                "username": "db2inst1",
                "password": "secret",
            }
        }
    )

    assert config.database.type == "db2"


@pytest.mark.unit
def test_from_dict_db2_host_without_database_is_invalid_connection_identifier():
    with pytest.raises(ConfigurationError, match="host/database"):
        DbliftConfig.from_dict(
            {
                "database": {
                    "type": "db2",
                    "host": "db.example.com",
                    "username": "db2inst1",
                    "password": "secret",
                }
            }
        )


@pytest.mark.unit
def test_load_config_plan_skips_secret_resolution(monkeypatch):
    """plan is an offline command — DbliftConfig.from_dict must be called with resolve_secrets=False."""

    class Args:
        command = "plan"

    monkeypatch.setenv("DBLIFT_DB_URL", "postgresql+psycopg://user:pass@localhost:5432/db")
    monkeypatch.setenv("DBLIFT_DB_SCHEMA", "public")

    with patch(
        "config.dblift_config.DbliftConfig.from_dict", wraps=DbliftConfig.from_dict
    ) as mock_from_dict:
        load_config("", Args())

    _, kwargs = mock_from_dict.call_args
    assert kwargs.get("resolve_secrets") is False


@pytest.mark.unit
def test_load_config_plan_chained_resolves_secrets(monkeypatch):
    """Chained 'plan migrate' must resolve secrets — plan is offline only when alone."""

    class Args:
        command = "plan"
        commands_list = ["plan", "migrate"]  # chained invocation

    monkeypatch.setenv("DBLIFT_DB_URL", "postgresql+psycopg://user:pass@localhost:5432/db")
    monkeypatch.setenv("DBLIFT_DB_SCHEMA", "public")

    with patch(
        "config.dblift_config.DbliftConfig.from_dict", wraps=DbliftConfig.from_dict
    ) as mock_from_dict:
        load_config("", Args())

    _, kwargs = mock_from_dict.call_args
    assert kwargs.get("resolve_secrets") is True


@pytest.mark.unit
def test_load_config_env_override(monkeypatch, tmp_path):
    os.environ.pop("DBLIFT_DB_USER", None)
    os.environ.pop("DBLIFT_DB_URL", None)
    # Simulate environment variable override
    config_file = tmp_path / "config.yaml"
    config_file.write_text("""
database:
  url: postgresql+psycopg://localhost:5432/db
  username: fileuser
  password: filepw
""")
    monkeypatch.setenv("DBLIFT_DB_USER", "envuser")
    monkeypatch.setenv("DBLIFT_DB_URL", "postgresql+psycopg://envhost:5432/db")
    with patch("os.path.exists", return_value=True):
        config = load_config(str(config_file), None)
        assert config.database.username == "envuser"
        assert config.database.url.startswith("postgresql+psycopg://envhost")


@pytest.mark.unit
def test_load_config_args_override(tmp_path):
    os.environ.pop("DBLIFT_DB_USER", None)
    os.environ.pop("DBLIFT_DB_URL", None)
    # Simulate command line args override
    config_file = tmp_path / "config.yaml"
    config_file.write_text("""
database:
  url: postgresql+psycopg://localhost:5432/db
  username: fileuser
  password: filepw
""")

    class Args:
        db_url = "postgresql+psycopg://cli:5432/db"
        db_username = "cliuser"
        db_password = "clipw"
        db_schema = "public"
        installed_by = "cliadmin"
        dry_run = True
        log_level = "DEBUG"
        log_file = "cli.log"
        tags = "t1"
        exclude_tags = "t2"
        versions = "v1"
        exclude_versions = "v2"
        placeholders = ["x=y", "a=b"]
        target_version = "2"
        undo = True
        mark_as_executed = True
        strict_mode = True
        history_table = "h"
        journal_enabled = True
        journal_dir = "jdir"
        error_handling_enabled = False
        max_retries = 5
        retry_delay = 2.0
        retry_backoff = 3.0
        retry_jitter = 0.5
        retryable_error_categories = ["foo", "bar"]

    with patch("os.path.exists", return_value=True):
        config = load_config(str(config_file), Args())
        assert config.database.username == "cliuser"
        assert config.database.schema == "public"
        assert config.dry_run is True
        assert config.log_level == "DEBUG"
        assert config.tags == "t1"
        assert config.placeholders["x"] == "y"
        assert config.placeholders["a"] == "b"
        assert config.target_version == "2"
        assert config.undo is True
        assert config.mark_as_executed is True
        assert config.strict_mode is True
        assert config.history_table == "h"
        assert config.journal_enabled is True
        # journal_dir is always None - journal is always in-memory only (set in cli/main.py)
        assert config.journal_dir is None
        assert config.error_handling_enabled is False
        assert config.max_retries == 5
        assert config.retry_delay == 2.0
        if hasattr(Args, "retry_backoff") and getattr(Args, "retry_backoff", None) is not None:
            assert config.retry_backoff == 3.0
        assert config.retry_jitter == 0.5
        assert config.retryable_error_categories == ["foo", "bar"]


@pytest.mark.unit
def test_from_args_dict_secret_uri_url_skips_jdbc_inference():
    """--db-url vault://... must not trigger JDBC type inference in from_args_dict."""
    result = DbliftConfig.from_args_dict({"db_url": "vault://secret/data/prod/db#url"})
    db = result.get("database", {})
    assert db.get("url") == "vault://secret/data/prod/db#url"
    # No type should be inferred from a secret URI
    assert db.get("type") is None
