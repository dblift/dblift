"""Multi-environment config layer: selection, merge, precedence, passthrough.

``environments:`` is the top-level scoping concept: root sections are the
shared base, the active environment's block deep-merges over them, and the
merge happens BEFORE env vars, CLI args, secrets resolution, and the paid
raw-config passthrough — so every consumer (OSS and paid) sees an already
environment-scoped effective config.
"""

from __future__ import annotations

import types

import pytest

from config.config_builder import ConfigBuilder
from config.dblift_config import (
    DEFAULT_ENV_SELECTOR_VAR,
    DbliftConfig,
    apply_environment,
    load_config,
    select_environment,
)
from config.errors import ConfigurationError

pytestmark = [pytest.mark.unit]

_BASE_YAML = """
database:
  type: sqlite
  url: sqlite:///base.db
migrations:
  directories: [migrations]
environments:
  prod:
    database:
      url: sqlite:///prod.db
    snapshot:
      source: file:.dblift/environments/prod.snapshot.json
      max_snapshot_age: 7d
  uat:
    database:
      url: sqlite:///uat.db
    migrations:
      directories: [migrations, migrations_uat]
    data_sets:
      corrections:
        policy: {allow_unchecked: true}
resolve:
  branch_var: TEST_BRANCH
  branch_map:
    "env/*": prod
    "release/uat": uat
"""


@pytest.fixture()
def config_file(tmp_path):
    path = tmp_path / "dblift.yaml"
    path.write_text(_BASE_YAML, encoding="utf-8")
    return str(path)


def _args(**kwargs):
    return types.SimpleNamespace(**kwargs)


# --- selection precedence ----------------------------------------------------


class TestSelectEnvironment:
    DATA = {"environments": {"prod": {}, "uat": {}}, "resolve": {}}

    def test_none_when_nothing_selects(self):
        assert select_environment(self.DATA, env={}) is None

    def test_explicit_wins_over_env_var(self):
        assert (
            select_environment(self.DATA, explicit="uat", env={DEFAULT_ENV_SELECTOR_VAR: "prod"})
            == "uat"
        )

    def test_selector_env_var(self):
        assert select_environment(self.DATA, env={DEFAULT_ENV_SELECTOR_VAR: "prod"}) == "prod"

    def test_resolve_env_var_override(self):
        data = {"environments": {"prod": {}}, "resolve": {"env_var": "MY_ENV"}}
        assert select_environment(data, env={"MY_ENV": "prod"}) == "prod"
        # the default selector is ignored once overridden
        assert select_environment(data, env={DEFAULT_ENV_SELECTOR_VAR: "prod"}) is None

    def test_branch_map_glob(self):
        data = {
            "environments": {"prod": {}},
            "resolve": {"branch_var": "BRANCH", "branch_map": {"env/*": "prod"}},
        }
        assert select_environment(data, env={"BRANCH": "env/prod"}) == "prod"
        assert select_environment(data, env={"BRANCH": "feature/x"}) is None

    def test_env_var_wins_over_branch_map(self):
        data = {
            "environments": {"prod": {}, "uat": {}},
            "resolve": {"branch_var": "BRANCH", "branch_map": {"*": "prod"}},
        }
        env = {"BRANCH": "anything", DEFAULT_ENV_SELECTOR_VAR: "uat"}
        assert select_environment(data, env=env) == "uat"

    def test_unknown_name_lists_configured(self):
        with pytest.raises(ConfigurationError) as exc:
            select_environment(self.DATA, explicit="nope", env={})
        assert "Unknown environment 'nope'" in str(exc.value)
        assert "prod" in str(exc.value) and "uat" in str(exc.value)

    def test_selected_without_environments_section_errors(self):
        with pytest.raises(ConfigurationError) as exc:
            select_environment({}, explicit="prod", env={})
        assert "add an environments: section" in str(exc.value)


# --- merge semantics ---------------------------------------------------------


class TestApplyEnvironment:
    def test_selector_keys_always_stripped(self):
        data = {"database": {"type": "sqlite"}, "environments": {"p": {}}, "resolve": {}}
        assert apply_environment(data, None) == {"database": {"type": "sqlite"}}

    def test_dicts_merge_recursively(self):
        data = {
            "database": {"type": "sqlite", "url": "sqlite:///base.db"},
            "environments": {"p": {"database": {"url": "sqlite:///p.db"}}},
        }
        merged = apply_environment(data, "p")
        assert merged["database"] == {"type": "sqlite", "url": "sqlite:///p.db"}

    def test_lists_replace(self):
        data = {
            "migrations": {"directories": ["a"]},
            "environments": {"p": {"migrations": {"directories": ["b", "c"]}}},
        }
        assert apply_environment(data, "p")["migrations"]["directories"] == ["b", "c"]

    def test_scalars_replace_and_new_sections_appear(self):
        data = {"environments": {"p": {"snapshot": {"source": "db:"}}}}
        assert apply_environment(data, "p")["snapshot"] == {"source": "db:"}

    def test_non_mapping_block_errors(self):
        with pytest.raises(ConfigurationError):
            apply_environment({"environments": {"p": "oops"}}, "p")


# --- end-to-end through load_config ------------------------------------------


class TestLoadConfig:
    def test_no_selection_yields_root_config(self, config_file, monkeypatch):
        monkeypatch.delenv(DEFAULT_ENV_SELECTOR_VAR, raising=False)
        config = load_config(config_file)
        assert config.database.url == "sqlite:///base.db"
        assert getattr(config, "_active_environment", None) is None

    def test_backward_compat_without_environments(self, tmp_path):
        plain = tmp_path / "plain.yaml"
        plain.write_text("database:\n  type: sqlite\n  url: sqlite:///only.db\n", encoding="utf-8")
        config = load_config(str(plain))
        assert config.database.url == "sqlite:///only.db"
        assert getattr(config, "_active_environment", None) is None

    def test_explicit_env_flag(self, config_file):
        config = load_config(config_file, _args(env="prod"))
        assert config.database.url == "sqlite:///prod.db"
        assert config._active_environment == "prod"

    def test_selector_env_var(self, config_file, monkeypatch):
        monkeypatch.setenv(DEFAULT_ENV_SELECTOR_VAR, "uat")
        config = load_config(config_file)
        assert config.database.url == "sqlite:///uat.db"
        assert config._active_environment == "uat"

    def test_branch_map_selection(self, config_file, monkeypatch):
        monkeypatch.delenv(DEFAULT_ENV_SELECTOR_VAR, raising=False)
        monkeypatch.setenv("TEST_BRANCH", "env/prod")
        config = load_config(config_file)
        assert config._active_environment == "prod"

    def test_env_vars_beat_environment_block(self, config_file, monkeypatch):
        monkeypatch.setenv(DEFAULT_ENV_SELECTOR_VAR, "prod")
        monkeypatch.setenv("DBLIFT_DB_URL", "sqlite:///envvar.db")
        config = load_config(config_file)
        assert config.database.url == "sqlite:///envvar.db"

    def test_cli_args_beat_environment_block(self, config_file):
        args = _args(env="prod", database_url="sqlite:///cli.db")
        config = load_config(config_file, args)
        assert config.database.url == "sqlite:///cli.db"

    def test_env_block_list_replaces_root(self, config_file):
        config = load_config(config_file, _args(env="uat"))
        paths = [d.path if hasattr(d, "path") else d for d in config.migrations.directories]
        assert paths == ["migrations", "migrations_uat"]

    def test_unknown_env_is_actionable(self, config_file):
        with pytest.raises(ConfigurationError) as exc:
            load_config(config_file, _args(env="nope"))
        assert "Unknown environment 'nope'" in str(exc.value)

    def test_paid_passthrough_is_environment_scoped(self, config_file):
        config = load_config(config_file, _args(env="prod"))
        assert config._paid_config_data == {
            "snapshot": {
                "source": "file:.dblift/environments/prod.snapshot.json",
                "max_snapshot_age": "7d",
            }
        }
        config = load_config(config_file, _args(env="uat"))
        assert (
            config._paid_config_data["data_sets"]["corrections"]["policy"]["allow_unchecked"]
            is True
        )

    def test_no_env_means_no_env_scoped_paid_data(self, config_file, monkeypatch):
        monkeypatch.delenv(DEFAULT_ENV_SELECTOR_VAR, raising=False)
        config = load_config(config_file)
        assert getattr(config, "_paid_config_data", None) is None


# --- ConfigBuilder / API path -------------------------------------------------


class TestConfigBuilder:
    def test_environment_keyword(self, config_file):
        config = ConfigBuilder.build(file_path=config_file, environment="prod", env_overrides=False)
        assert config.database.url == "sqlite:///prod.db"
        assert config._active_environment == "prod"

    def test_selector_env_var_honored(self, config_file, monkeypatch):
        monkeypatch.setenv(DEFAULT_ENV_SELECTOR_VAR, "uat")
        config = ConfigBuilder.build(file_path=config_file, env_overrides=False)
        assert config._active_environment == "uat"

    def test_kwargs_beat_environment_block(self, config_file):
        config = ConfigBuilder.build(
            file_path=config_file,
            environment="prod",
            env_overrides=False,
            database_url="sqlite:///kw.db",
        )
        assert config.database.url == "sqlite:///kw.db"

    def test_environment_kwarg_is_a_build_key(self):
        """The client factory must not forward it to the client constructor."""
        assert "environment" in ConfigBuilder.CONFIG_BUILD_KWARG_KEYS


# --- selector reservation -----------------------------------------------------


class TestSelectorReservation:
    def test_no_registry_property_claims_the_selector_surface(self):
        """DBLIFT_ENV / --env select configuration; they must never become a
        persistent property (which would inject an ``env`` key into the config
        dict and shadow the selector)."""
        from config.property_registry import PROPERTY_REGISTRY

        for spec in PROPERTY_REGISTRY:
            assert spec.env != DEFAULT_ENV_SELECTOR_VAR, spec.name
            assert spec.cli != "--env", spec.name

    def test_from_env_dict_ignores_selector_var(self, monkeypatch):
        monkeypatch.setenv(DEFAULT_ENV_SELECTOR_VAR, "prod")
        env_dict = DbliftConfig.from_env_dict()
        assert "env" not in env_dict
        assert "environment" not in env_dict
