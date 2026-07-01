from config.property_registry import (
    PROPERTY_REGISTRY,
    PropertySpec,
    cli_flag,
    env_name,
    spec_for,
)


def test_env_name_derivation():
    assert env_name("installed_by") == "DBLIFT_INSTALLED_BY"
    assert env_name("history_table") == "DBLIFT_HISTORY_TABLE"
    assert env_name("database.username") == "DBLIFT_DB_USERNAME"


def test_cli_flag_derivation():
    assert cli_flag("installed_by") == "--installed-by"
    assert cli_flag("history_table") == "--history-table"
    assert cli_flag("database.username") == "--db-username"


def test_registry_contains_installed_by_with_all_surfaces():
    spec = spec_for("installed_by")
    assert spec is not None
    assert spec.cli_only is False
    assert spec.env == "DBLIFT_INSTALLED_BY"


def test_registry_names_are_unique():
    names = [s.name for s in PROPERTY_REGISTRY]
    assert len(names) == len(set(names))


def test_every_spec_has_derived_surfaces():
    for spec in PROPERTY_REGISTRY:
        assert spec.env == env_name(spec.name)
        if not spec.cli_only:
            assert spec.cli == cli_flag(spec.name)


def test_spec_for_unknown_returns_none():
    assert spec_for("does_not_exist") is None


def test_derived_env_and_cli_names_are_globally_unique():
    envs = [s.env for s in PROPERTY_REGISTRY]
    assert len(envs) == len(set(envs))
    clis = [s.cli for s in PROPERTY_REGISTRY if not s.cli_only]
    assert len(clis) == len(set(clis))
