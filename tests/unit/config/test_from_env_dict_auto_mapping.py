"""BUG-08 regression: from_env_dict() auto-maps all DBLIFT_DB_* env vars.

Before this fix only URL, USER, PASSWORD, and SCHEMA were explicitly mapped;
any other DBLIFT_DB_* variable (e.g. DBLIFT_DB_HOST, DBLIFT_DB_PORT) was
silently ignored. The fix replaces the hardcoded block with a convention-based
loop: DBLIFT_DB_<SUFFIX> -> database.<suffix.lower()>, with special aliases
(USER -> username) and structured parsing (OPTIONS, SESSION_VARS).
"""

from __future__ import annotations

import json

import pytest

from config.dblift_config import ConfigEnvDiagnostics, DbliftConfig


class TestFromEnvDictAutoMapping:
    def test_known_fields_still_map_correctly(self, monkeypatch):
        monkeypatch.setenv("DBLIFT_DB_URL", "postgresql+psycopg://localhost/db")
        monkeypatch.setenv("DBLIFT_DB_USER", "alice")
        monkeypatch.setenv("DBLIFT_DB_PASSWORD", "secret")
        monkeypatch.setenv("DBLIFT_DB_SCHEMA", "public")
        result = DbliftConfig.from_env_dict()
        db = result["database"]
        assert db["url"] == "postgresql+psycopg://localhost/db"
        assert db["username"] == "alice"
        assert db["password"] == "secret"
        assert db["schema"] == "public"

    def test_allowlisted_db_fields_are_mapped(self, monkeypatch):
        monkeypatch.setenv("DBLIFT_DB_HOST", "db.example.com")
        monkeypatch.setenv("DBLIFT_DB_PORT", "5432")
        monkeypatch.setenv("DBLIFT_DB_TYPE", "postgresql")
        result = DbliftConfig.from_env_dict()
        db = result["database"]
        assert db["host"] == "db.example.com"
        assert db["port"] == 5432
        assert db["type"] == "postgresql"

    def test_options_parsed_as_json(self, monkeypatch):
        monkeypatch.setenv("DBLIFT_DB_OPTIONS", json.dumps({"ssl": "true", "timeout": "30"}))
        result = DbliftConfig.from_env_dict()
        assert result["database"]["options"] == {"ssl": "true", "timeout": "30"}

    def test_options_parsed_as_csv(self, monkeypatch):
        monkeypatch.setenv("DBLIFT_DB_OPTIONS", "ssl=true,timeout=30")
        result = DbliftConfig.from_env_dict()
        assert result["database"]["options"] == {"ssl": "true", "timeout": "30"}

    def test_session_vars_parsed_as_json(self, monkeypatch):
        monkeypatch.setenv("DBLIFT_DB_SESSION_VARS", json.dumps({"search_path": "myschema"}))
        result = DbliftConfig.from_env_dict()
        assert result["database"]["session_variables"] == {"search_path": "myschema"}

    def test_session_vars_parsed_as_csv(self, monkeypatch):
        monkeypatch.setenv("DBLIFT_DB_SESSION_VARS", "search_path=myschema,timezone=UTC")
        result = DbliftConfig.from_env_dict()
        assert result["database"]["session_variables"] == {
            "search_path": "myschema",
            "timezone": "UTC",
        }

    def test_top_level_keys_still_work(self, monkeypatch):
        monkeypatch.setenv("DBLIFT_SNAPSHOT_TABLE", "my_snapshots")
        monkeypatch.setenv("DBLIFT_HISTORY_TABLE", "my_history")
        monkeypatch.setenv("DBLIFT_MAX_SNAPSHOTS", "5")
        result = DbliftConfig.from_env_dict()
        assert result["snapshot_table"] == "my_snapshots"
        assert result["history_table"] == "my_history"
        assert result["max_snapshots"] == 5

    def test_empty_env_returns_empty_dict(self, monkeypatch):
        # New contract: with no DBLIFT_* env set, no "database" key is emitted
        # so ``if env_dict:`` becomes a true emptiness check at callers, not a
        # no-op merge through ``BaseDatabaseConfig.create()``.
        for key in list(__import__("os").environ.keys()):
            if key.startswith("DBLIFT_"):
                monkeypatch.delenv(key, raising=False)
        result = DbliftConfig.from_env_dict()
        assert result == {}

    def test_empty_value_is_skipped(self, monkeypatch):
        for key in list(__import__("os").environ.keys()):
            if key.startswith("DBLIFT_"):
                monkeypatch.delenv(key, raising=False)
        monkeypatch.setenv("DBLIFT_DB_HOST", "")
        result = DbliftConfig.from_env_dict()
        assert result == {}

    def test_unknown_suffix_is_ignored(self, monkeypatch):
        for key in list(__import__("os").environ.keys()):
            if key.startswith("DBLIFT_"):
                monkeypatch.delenv(key, raising=False)
        monkeypatch.setenv("DBLIFT_DB_INTERNAL_CI_VAR", "some-value")
        monkeypatch.setenv("DBLIFT_DB_RANDOM_TOOLING_KEY", "irrelevant")
        result = DbliftConfig.from_env_dict()
        assert result == {}

    def test_diagnostics_collect_unknown_suffixes_without_changing_output(self, monkeypatch):
        for key in list(__import__("os").environ.keys()):
            if key.startswith("DBLIFT_"):
                monkeypatch.delenv(key, raising=False)
        monkeypatch.setenv("DBLIFT_DB_INTERNAL_CI_VAR", "some-value")
        diagnostics = ConfigEnvDiagnostics()

        result = DbliftConfig.from_env_dict(diagnostics=diagnostics)

        assert result == {}
        assert diagnostics.ignored_db_vars == ["DBLIFT_DB_INTERNAL_CI_VAR"]

    def test_connection_timeout_coerced_to_int(self, monkeypatch):
        monkeypatch.setenv("DBLIFT_DB_CONNECTION_TIMEOUT", "60")
        result = DbliftConfig.from_env_dict()
        assert result["database"]["connection_timeout"] == 60
        assert isinstance(result["database"]["connection_timeout"], int)

    def test_port_coerced_to_int(self, monkeypatch):
        monkeypatch.setenv("DBLIFT_DB_PORT", "5432")
        result = DbliftConfig.from_env_dict()
        assert result["database"]["port"] == 5432
        assert isinstance(result["database"]["port"], int)

    def test_invalid_int_field_is_skipped(self, monkeypatch):
        for key in list(__import__("os").environ.keys()):
            if key.startswith("DBLIFT_"):
                monkeypatch.delenv(key, raising=False)
        monkeypatch.setenv("DBLIFT_DB_CONNECTION_TIMEOUT", "not_a_number")
        result = DbliftConfig.from_env_dict()
        assert result == {}

    def test_diagnostics_collect_invalid_int_fields(self, monkeypatch):
        monkeypatch.setenv("DBLIFT_DB_CONNECTION_TIMEOUT", "not_a_number")
        monkeypatch.setenv("DBLIFT_MAX_SNAPSHOTS", "NaN")
        diagnostics = ConfigEnvDiagnostics()

        DbliftConfig.from_env_dict(diagnostics=diagnostics)

        assert diagnostics.invalid_int_vars == [
            "DBLIFT_DB_CONNECTION_TIMEOUT",
            "DBLIFT_MAX_SNAPSHOTS",
        ]

    def test_diagnostics_collect_invalid_structured_fields(self, monkeypatch):
        for key in list(__import__("os").environ.keys()):
            if key.startswith("DBLIFT_"):
                monkeypatch.delenv(key, raising=False)
        monkeypatch.setenv("DBLIFT_DB_OPTIONS", "not-json-or-csv")
        diagnostics = ConfigEnvDiagnostics()

        result = DbliftConfig.from_env_dict(diagnostics=diagnostics)

        assert result == {}
        assert diagnostics.invalid_structured_vars == ["DBLIFT_DB_OPTIONS"]

    def test_bool_field_true_values(self, monkeypatch):
        for truthy in ("true", "True", "TRUE", "1", "yes", "Yes"):
            monkeypatch.setenv("DBLIFT_DB_ENCRYPT", truthy)
            result = DbliftConfig.from_env_dict()
            assert result["database"]["encrypt"] is True, f"Expected True for {truthy!r}"

    def test_bool_field_false_values(self, monkeypatch):
        for falsy in ("false", "False", "0", "no", "No"):
            monkeypatch.setenv("DBLIFT_DB_ENCRYPT", falsy)
            result = DbliftConfig.from_env_dict()
            assert result["database"]["encrypt"] is False, f"Expected False for {falsy!r}"

    def test_extra_params_parsed_as_json(self, monkeypatch):
        monkeypatch.setenv("DBLIFT_DB_EXTRA_PARAMS", json.dumps({"sslMode": "require"}))
        result = DbliftConfig.from_env_dict()
        assert result["database"]["extra_params"] == {"sslMode": "require"}

    def test_extra_params_parsed_as_csv(self, monkeypatch):
        monkeypatch.setenv("DBLIFT_DB_EXTRA_PARAMS", "sslMode=require,connectTimeout=10")
        result = DbliftConfig.from_env_dict()
        assert result["database"]["extra_params"] == {
            "sslMode": "require",
            "connectTimeout": "10",
        }
