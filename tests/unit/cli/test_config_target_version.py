"""``target_version`` from the YAML config or ``DBLIFT_TARGET_VERSION`` is honoured.

Precedence is the one every other key follows: flag > environment variable > YAML.
"""

import json
import os
import sqlite3
import subprocess
import sys

import pytest
import yaml
from sqlalchemy import create_engine

from dblift.api import DBLiftClient
from dblift.config.dblift_config import DbliftConfig
from dblift.core.exceptions import InvalidTargetVersionError

pytestmark = pytest.mark.unit


def _project(tmp_path, target=None, name="dblift.yaml"):
    for number in (1, 2, 3):
        for prefix, sql in (("V", "CREATE TABLE"), ("U", "DROP TABLE")):
            script = tmp_path / f"{prefix}{number}__t{number}.sql"
            if not script.exists():
                script.write_text(
                    f"{sql} t{number}(id INTEGER);" if prefix == "V" else f"{sql} t{number};"
                )
    data = {
        "database": {"type": "sqlite", "path": str(tmp_path / "db.sqlite")},
        "migrations": {"directory": str(tmp_path)},
    }
    if target is not None:
        data["target_version"] = target
    config = tmp_path / name
    config.write_text(yaml.safe_dump(data))
    return config


def _tables(tmp_path):
    with sqlite3.connect(tmp_path / "db.sqlite") as db:
        return {
            row[0]
            for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")
            if row[0] in ("t1", "t2", "t3")
        }


def _cli(tmp_path, config, *args, env=None):
    environment = {k: v for k, v in os.environ.items() if not k.startswith("DBLIFT_")}
    environment.update(env or {})
    return subprocess.run(
        [sys.executable, "-m", "dblift.cli.main", "--config", str(config), *args],
        capture_output=True,
        text=True,
        timeout=60,
        env=environment,
        cwd=tmp_path,
    )


@pytest.fixture(autouse=True)
def _clean_environment(monkeypatch):
    for key in list(os.environ):
        if key.startswith("DBLIFT_"):
            monkeypatch.delenv(key)


def test_cli_migrate_honours_yaml_target_version(tmp_path):
    config = _project(tmp_path, target=1)
    result = _cli(tmp_path, config, "migrate")
    assert result.returncode == 0, result.stdout + result.stderr
    assert _tables(tmp_path) == {"t1"}


def test_cli_migrate_honours_environment_target_version(tmp_path):
    config = _project(tmp_path)
    result = _cli(tmp_path, config, "migrate", env={"DBLIFT_TARGET_VERSION": "1"})
    assert result.returncode == 0, result.stdout + result.stderr
    assert _tables(tmp_path) == {"t1"}


@pytest.mark.parametrize(
    "yaml_target, env_target, flag, expected",
    [
        (1, "2", None, {"t1", "t2"}),
        (1, "2", "3", {"t1", "t2", "t3"}),
        (3, None, "1", {"t1"}),
        (1, None, None, {"t1"}),
    ],
)
def test_cli_target_version_precedence_is_flag_then_env_then_yaml(
    tmp_path, yaml_target, env_target, flag, expected
):
    config = _project(tmp_path, target=yaml_target)
    env = {"DBLIFT_TARGET_VERSION": env_target} if env_target else {}
    args = ["migrate"] + (["--target-version", flag] if flag else [])
    result = _cli(tmp_path, config, *args, env=env)
    assert result.returncode == 0, result.stdout + result.stderr
    assert _tables(tmp_path) == expected


def test_api_from_config_file_migrate_honours_yaml_target_version(tmp_path):
    config = _project(tmp_path, target=1)
    with DBLiftClient.from_config_file(str(config)) as client:
        result = client.migrate()
        assert result.success, result.error_message
    assert _tables(tmp_path) == {"t1"}


def test_api_explicit_argument_overrides_configured_target_version(tmp_path):
    config = _project(tmp_path, target=1)
    with DBLiftClient.from_config_file(str(config)) as client:
        assert client.migrate(target_version="2").success
    assert _tables(tmp_path) == {"t1", "t2"}


def test_api_from_sqlalchemy_with_config_object_honours_target_version(tmp_path):
    config = DbliftConfig.from_file(_project(tmp_path))
    config.target_version = "2"
    engine = create_engine(f"sqlite:///{tmp_path / 'db.sqlite'}")
    try:
        with DBLiftClient.from_sqlalchemy(engine, config=config) as client:
            assert client.migrate().success
    finally:
        engine.dispose()
    assert _tables(tmp_path) == {"t1", "t2"}


def test_api_honours_target_version_from_environment(tmp_path, monkeypatch):
    config = _project(tmp_path)
    monkeypatch.setenv("DBLIFT_TARGET_VERSION", "1")
    with DBLiftClient.from_config_file(str(config)) as client:
        assert client.migrate().success
    assert _tables(tmp_path) == {"t1"}


def test_empty_yaml_target_version_is_rejected_by_cli(tmp_path):
    config = _project(tmp_path, target="")
    result = _cli(tmp_path, config, "migrate")
    assert result.returncode != 0
    assert "Invalid target version ''" in result.stdout + result.stderr
    assert "Available versions:" not in result.stdout + result.stderr
    assert _tables(tmp_path) == set()


def test_empty_yaml_target_version_is_rejected_by_api(tmp_path):
    config = _project(tmp_path, target="")
    with pytest.raises(InvalidTargetVersionError) as raised:
        DBLiftClient.from_config_file(str(config))
    assert "Available versions:" not in str(raised.value)
    assert _tables(tmp_path) == set()


def test_empty_target_version_in_an_environment_block_is_rejected(tmp_path, monkeypatch):
    config = _project(tmp_path, target=1)
    data = yaml.safe_load(config.read_text())
    data["environments"] = {"dev": {"target_version": ""}}
    config.write_text(yaml.safe_dump(data))
    monkeypatch.setenv("DBLIFT_ENV", "dev")
    with pytest.raises(InvalidTargetVersionError):
        DBLiftClient.from_config_file(str(config))
    result = _cli(tmp_path, config, "migrate", env={"DBLIFT_ENV": "dev"})
    assert result.returncode != 0
    assert "Invalid target version ''" in result.stdout + result.stderr
    assert _tables(tmp_path) == set()


def test_cli_undo_honours_yaml_target_version(tmp_path):
    config = _project(tmp_path)
    assert _cli(tmp_path, config, "migrate").returncode == 0
    config = _project(tmp_path, target=1)
    result = _cli(tmp_path, config, "undo")
    assert result.returncode == 0, result.stdout + result.stderr
    assert _tables(tmp_path) == {"t1"}


def test_cli_info_honours_yaml_target_version_like_the_flag(tmp_path):
    base = _project(tmp_path)
    unfiltered = _cli(tmp_path, base, "info", "--format", "json")
    flagged = _cli(tmp_path, base, "info", "--format", "json", "--target-version", "1")
    assert flagged.returncode == 0, flagged.stdout + flagged.stderr
    configured = _cli(
        tmp_path, _project(tmp_path, target=1, name="target.yaml"), "info", "--format", "json"
    )
    assert configured.returncode == 0, configured.stdout + configured.stderr

    def statuses(result):
        payload = json.loads(result.stdout[result.stdout.index("{") :])
        return [(m["version"], m["status"]) for m in payload["migrations"]]

    assert statuses(configured) == statuses(flagged)
    assert statuses(configured) != statuses(unfiltered)


def test_cli_validate_honours_yaml_target_version_like_the_flag(tmp_path):
    base = _project(tmp_path)
    assert _cli(tmp_path, base, "migrate").returncode == 0
    (tmp_path / "V3__t3.sql").write_text("CREATE TABLE t3(id INTEGER, extra TEXT);")
    assert _cli(tmp_path, base, "validate").returncode != 0
    assert _cli(tmp_path, base, "validate", "--target-version", "2").returncode == 0
    assert (
        _cli(tmp_path, _project(tmp_path, target=2, name="target.yaml"), "validate").returncode == 0
    )


def _applied_client(tmp_path, target):
    """Apply all three migrations, then return a client whose config carries *target*."""
    with DBLiftClient.from_config_file(str(_project(tmp_path))) as client:
        assert client.migrate().success
    return DBLiftClient.from_config_file(str(_project(tmp_path, target=target, name="t.yaml")))


def test_api_validate_honours_configured_target_version(tmp_path):
    with _applied_client(tmp_path, 2) as client:
        (tmp_path / "V3__t3.sql").write_text("CREATE TABLE t3(id INTEGER, extra TEXT);")
        assert client.validate().success is True
        assert client.validate(target_version="3").success is False


def test_api_undo_honours_configured_target_version(tmp_path):
    with _applied_client(tmp_path, 1) as client:
        assert client.undo().success
    assert _tables(tmp_path) == {"t1"}


def test_api_info_honours_configured_target_version(tmp_path):
    def statuses(result):
        return [(str(m.version), str(m.status)) for m in result.migrations]

    plain = DBLiftClient.from_config_file(str(_project(tmp_path)))
    configured = DBLiftClient.from_config_file(str(_project(tmp_path, 1, name="t.yaml")))
    with plain, configured:
        flagged = statuses(plain.info(target_version="1"))
        assert statuses(configured.info()) == flagged
        assert flagged != statuses(plain.info())


def test_api_info_refuses_an_unknown_configured_target_version(tmp_path):
    with DBLiftClient.from_config_file(str(_project(tmp_path, 9))) as client:
        with pytest.raises(InvalidTargetVersionError):
            client.info()


def test_config_data_loader_refuses_empty_target_and_tolerates_other_shapes(tmp_path):
    from dblift.config.dblift_config import DbliftConfig

    def load(content):
        path = tmp_path / "shape.yaml"
        path.write_text(content)
        return DbliftConfig.load_config_data_from_yaml(path)

    assert load("- not\n- a mapping\n") == {}
    assert load("environments: nope\ntarget_version: 2\n") == {
        "environments": "nope",
        "target_version": 2,
    }
    assert load("environments:\n  dev: nope\n")["environments"] == {"dev": "nope"}
    with pytest.raises(InvalidTargetVersionError):
        load("target_version: ''\n")
    with pytest.raises(InvalidTargetVersionError):
        load("environments:\n  dev:\n    target_version: ''\n")


def test_load_config_refuses_empty_target_without_wrapping_it(tmp_path):
    from dblift.config.dblift_config import load_config

    with pytest.raises(InvalidTargetVersionError):
        load_config(str(_project(tmp_path, target="")))
