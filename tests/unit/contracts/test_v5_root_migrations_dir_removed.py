"""The root migration-directory alias must fail before a wrong path can be used."""

import pytest

from dblift.config.dblift_config import DbliftConfig, unrecognized_top_level_keys
from dblift.config.errors import ConfigurationError

pytestmark = pytest.mark.unit

DATABASE = {"url": "sqlite:///tmp/dblift-v5-config.db"}


@pytest.mark.parametrize("alias", ["legacy", "", None])
@pytest.mark.parametrize("nested", [False, True])
def test_from_dict_rejects_every_present_root_alias(alias, nested):
    data = {"database": DATABASE, "migrations_dir": alias}
    if nested:
        data["migrations"] = {"directory": "canonical"}
    with pytest.raises(ConfigurationError, match="migrations.directory"):
        DbliftConfig.from_dict(data)


@pytest.mark.parametrize("alias", ["legacy", "", None])
@pytest.mark.parametrize("nested", [False, True])
def test_merge_rejects_every_present_root_alias(alias, nested):
    config = DbliftConfig.from_dict({"database": DATABASE})
    data = {"migrations_dir": alias}
    if nested:
        data["migrations"] = {"directory": "canonical"}
    with pytest.raises(ConfigurationError, match="migrations.directory"):
        config.merge(data)


def test_root_alias_is_reported_as_unrecognized():
    assert unrecognized_top_level_keys({"migrations_dir": None}) == ["migrations_dir"]


def test_canonical_and_cli_paths_remain_available():
    canonical = DbliftConfig.from_dict(
        {"database": DATABASE, "migrations": {"directory": "canonical"}}
    )
    assert canonical.migrations.directory == "./canonical"
    cli = DbliftConfig.from_args_dict({"migrations_dir": "cli"})
    assert cli["migrations"] == {"directory": "cli"}
    assert "migrations_dir" not in cli
