"""An empty ``migrations.directory`` is a configuration error, never the working directory.

``${UNSET}`` resolves to ``""``; reading that as ``./`` made ``migrate`` apply every
``V*.sql`` under the working directory.
"""

import os
import sqlite3
import subprocess
import sys

import pytest
import yaml
from sqlalchemy import create_engine

from dblift.api import DBLiftClient
from dblift.config.dblift_config import DbliftConfig
from dblift.config.errors import ConfigurationError

pytestmark = pytest.mark.unit

_DB = {"type": "sqlite", "path": "x.db"}
_SCRIPT = "CREATE TABLE {} (id INTEGER NOT NULL PRIMARY KEY);\n"


def _load(migrations):
    return DbliftConfig.from_dict({"database": _DB, "migrations": migrations})


@pytest.mark.parametrize("value", ["", None])
def test_empty_directory_is_a_configuration_error(value):
    with pytest.raises(ConfigurationError, match=r"migrations\.directory is empty"):
        _load({"directory": value})


@pytest.mark.parametrize(
    "entries",
    [
        [""],
        ["migrations", ""],
        [{"path": ""}],
        [{"directory": ""}],
        [{"path": "", "recursive": False}],
    ],
)
def test_empty_directories_entry_is_a_configuration_error(entries):
    with pytest.raises(ConfigurationError, match=r"migrations\.directories\[\d\] is empty"):
        _load({"directory": "migrations", "directories": entries})


def test_absent_directory_still_defaults_to_migrations():
    assert DbliftConfig.from_dict({"database": _DB}).migrations.directory == "./migrations"


def test_non_empty_entries_are_accepted():
    config = _load({"directory": "a", "directories": ["b", {"path": "c", "recursive": False}]})
    assert config.migrations.directory == "./a"


def test_merge_refuses_an_empty_directory():
    config = DbliftConfig.from_dict({"database": _DB})
    with pytest.raises(ConfigurationError, match=r"migrations\.directory is empty"):
        config.merge({"migrations": {"directory": ""}})


def test_unset_placeholder_in_a_file_is_named_as_the_cause(tmp_path, monkeypatch):
    monkeypatch.delenv("Q4C_NOT_SET", raising=False)
    path = tmp_path / "c.yaml"
    path.write_text(
        yaml.safe_dump({"database": _DB, "migrations": {"directory": "${Q4C_NOT_SET}"}})
    )
    with pytest.raises(ConfigurationError, match=r"migrations\.directory is empty.*\$\{VAR\}"):
        DbliftConfig.from_file(path)
    with pytest.raises(ConfigurationError, match=r"migrations\.directory is empty"):
        DbliftConfig.load_config_data_from_yaml(path)


def test_set_placeholder_still_resolves(tmp_path, monkeypatch):
    monkeypatch.setenv("Q4C_SET", "scripts")
    path = tmp_path / "c.yaml"
    path.write_text(yaml.safe_dump({"database": _DB, "migrations": {"directory": "${Q4C_SET}"}}))
    assert DbliftConfig.from_file(path).migrations.directory == "./scripts"


def test_empty_directory_in_an_environment_block_is_refused(tmp_path):
    path = tmp_path / "c.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "database": _DB,
                "migrations": {"directory": "migrations"},
                "environments": {"ci": {"migrations": {"directory": ""}}},
            }
        )
    )
    with pytest.raises(ConfigurationError, match=r"environments\.ci\.migrations\.directory"):
        DbliftConfig.load_config_data_from_yaml(path)


@pytest.mark.parametrize("value", ["", [""], [{"path": ""}]])
def test_api_refuses_an_empty_migrations_dir(tmp_path, value):
    engine = create_engine(f"sqlite:///{tmp_path / 'a.db'}")
    with pytest.raises(ConfigurationError, match="migrations_dir"):
        DBLiftClient.from_sqlalchemy(engine, migrations_dir=value)


def _project(tmp_path, migrations):
    (tmp_path / "proj" / "migrations").mkdir(parents=True)
    (tmp_path / "proj" / "migrations" / "V1__a.sql").write_text(_SCRIPT.format("proj_table"))
    (tmp_path / "cwd").mkdir()
    (tmp_path / "cwd" / "V9__cwd.sql").write_text(_SCRIPT.format("cwd_table"))
    config = tmp_path / "proj" / "c.yaml"
    config.write_text(
        yaml.safe_dump(
            {"database": {"url": f"sqlite:///{tmp_path / 'db.sqlite'}"}, "migrations": migrations}
        )
    )
    return config


def _cli(tmp_path, config, *args):
    environment = {k: v for k, v in os.environ.items() if not k.startswith(("DBLIFT_", "Q4C_"))}
    return subprocess.run(
        [sys.executable, "-m", "dblift.cli.main", "--config", str(config), *args],
        capture_output=True,
        text=True,
        timeout=60,
        env=environment,
        cwd=tmp_path / "cwd",
    )


def _tables(tmp_path):
    if not (tmp_path / "db.sqlite").exists():
        return set()
    with sqlite3.connect(tmp_path / "db.sqlite") as db:
        return {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}


@pytest.mark.parametrize("directory", ["${Q4C_NOT_SET}", ""])
@pytest.mark.parametrize("command", ["info", "validate", "migrate"])
def test_cli_refuses_an_empty_directory_and_applies_nothing(tmp_path, command, directory):
    config = _project(tmp_path, {"directory": directory})
    result = _cli(tmp_path, config, command, "--format", "json")
    assert result.returncode != 0, result.stdout + result.stderr
    assert "migrations.directory is empty" in result.stdout + result.stderr
    assert "cwd_table" not in _tables(tmp_path)


def test_cli_scripts_flag_refuses_an_empty_value(tmp_path):
    config = _project(tmp_path, {"directory": "migrations"})
    result = _cli(tmp_path, config, "--scripts", "", "migrate")
    assert result.returncode != 0
    assert "--scripts" in result.stderr
    assert "cwd_table" not in _tables(tmp_path)


def test_cli_good_directory_is_untouched(tmp_path):
    config = _project(tmp_path, {"directory": "migrations"})
    result = _cli(tmp_path, config, "migrate")
    assert result.returncode == 0, result.stdout + result.stderr
    assert {"proj_table"} <= _tables(tmp_path)
    assert "cwd_table" not in _tables(tmp_path)


def test_client_from_config_file_surfaces_the_empty_directory(tmp_path):
    path = tmp_path / "c.yaml"
    path.write_text(yaml.safe_dump({"database": _DB, "migrations": {"directory": ""}}))
    with pytest.raises(ConfigurationError, match=r"migrations\.directory is empty"):
        DBLiftClient.from_config_file(str(path))
