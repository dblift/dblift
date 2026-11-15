"""Requested log destinations remain safe through anchoring, overrides and refused config."""

import json
from pathlib import Path

import pytest
from sqlalchemy import create_engine

from dblift.api._cli_support import ProviderRegistry
from dblift.api.client import DBLiftClient
from dblift.config.config_builder import ConfigBuilder
from dblift.config.dblift_config import DbliftConfig
from dblift.config.path_anchoring import anchor_config_paths
from dblift.core.logger import FileLog, LogFormat, NullLog
from tests.unit.api.test_requested_log_file_api import _project as _api_project
from tests.unit.cli.test_requested_log_file_cli import _files, _project, _run

pytestmark = [pytest.mark.unit]


def _logging_yaml(style, filename):
    return f"log_file: {filename}\n" if style == "flat" else f"logging:\n  file: {filename}\n"


@pytest.mark.parametrize("command", [["info"], ["db", "check-connection"]])
@pytest.mark.parametrize("style", ["flat", "nested"])
@pytest.mark.parametrize("filename", ["linked.log", "own/linked.log"])
def test_cli_configured_symlink_leaf_is_refused(tmp_path, command, style, filename):
    project = _project(tmp_path, _logging_yaml(style, filename))
    sentinel = tmp_path / "sentinel.log"
    sentinel.write_text("sentinel content\n")
    leaf = project / filename
    leaf.parent.mkdir(parents=True, exist_ok=True)
    leaf.symlink_to(sentinel)
    proc = _run(tmp_path, ["--config", str(project / "d.yaml"), *command])
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "Error: cannot write log file" in proc.stderr
    assert "Traceback" not in proc.stdout + proc.stderr
    assert sentinel.read_text() == "sentinel content\n"
    assert leaf.is_symlink()


@pytest.mark.parametrize("route", ["raw-file", "typed-anchor"])
@pytest.mark.parametrize("style", ["flat", "nested"])
@pytest.mark.parametrize("filename", ["linked.log", "own/linked.log"])
def test_api_configured_symlink_leaf_is_refused(tmp_path, route, style, filename):
    config_file = _api_project(tmp_path, _logging_yaml(style, filename))
    sentinel = tmp_path / "sentinel.log"
    sentinel.write_text("sentinel content\n")
    leaf = config_file.parent / filename
    leaf.parent.mkdir(parents=True, exist_ok=True)
    leaf.symlink_to(sentinel)
    with pytest.raises(OSError, match="symlinked output"):
        if route == "raw-file":
            with DBLiftClient.from_config_file(str(config_file)):
                pass
        else:
            data = {"database": {"type": "sqlite", "path": str(tmp_path / "app.db")}}
            if style == "flat":
                data["log_file"] = filename
            else:
                data["logging"] = {"file": filename}
            config = DbliftConfig.from_dict(data)
            anchor_config_paths(config, config_file.parent)
            with DBLiftClient.from_config(config):
                pass
    assert sentinel.read_text() == "sentinel content\n"
    assert leaf.is_symlink()


@pytest.mark.parametrize("command", [["info"], ["db", "check-connection", "--format", "json"]])
@pytest.mark.parametrize("log_format", ["text", "json", "html"])
def test_cli_directory_at_final_file_fails_before_command_success(tmp_path, command, log_format):
    project = _project(tmp_path)
    target = tmp_path / "cwd" / f"occupied.{log_format}"
    target.mkdir()
    (target / "existing").write_text("keep this directory nonempty\n")
    proc = _run(
        tmp_path,
        [
            "--config",
            str(project / "d.yaml"),
            "--log-format",
            log_format,
            "--log-file",
            str(target),
            *command,
        ],
    )
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "Error: cannot write log file" in proc.stderr
    assert "Traceback" not in proc.stdout + proc.stderr
    assert '"success": true' not in proc.stdout.lower()
    assert "Connection successful!" not in proc.stdout + proc.stderr
    assert not (project / "t.db").exists()


@pytest.mark.parametrize("log_format", [LogFormat.TEXT, LogFormat.JSON, LogFormat.HTML])
def test_sink_rejects_a_directory_at_the_actual_file_during_construction(tmp_path, log_format):
    target = tmp_path / "occupied.log"
    target.mkdir()
    (target / "existing").touch()
    with pytest.raises(OSError):
        FileLog("requested", tmp_path, log_format, log_file_pattern=str(target))


def _factory_client(factory, config, engine, **overrides):
    if factory == "direct":
        provider = ProviderRegistry.create_provider(config, NullLog())
        return DBLiftClient(provider, config.migrations.directory, config, **overrides)
    if factory == "config":
        return DBLiftClient.from_config(config, **overrides)
    return DBLiftClient.from_sqlalchemy(engine, config=config, **overrides)


@pytest.mark.parametrize("factory", ["direct", "config", "sqlalchemy"])
@pytest.mark.parametrize("style", ["flat", "nested"])
@pytest.mark.parametrize("kind", ["bare", "absolute", "own-directory", "explicit-absolute"])
def test_two_stage_api_directory_override_preserves_filename_provenance(
    tmp_path, monkeypatch, factory, style, kind
):
    filename = "requested.log"
    if kind == "absolute":
        filename = str(tmp_path / "absolute" / "requested.log")
    elif kind == "own-directory":
        filename = "own/requested.log"
    config_file = _api_project(tmp_path, _logging_yaml(style, filename))
    config = ConfigBuilder.build(file_path=config_file, env_overrides=False)
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.chdir(work)
    overrides = {"log_dir": "override"}
    if kind == "explicit-absolute":
        overrides["log_file"] = config.log_file or config.logging.file
    engine = create_engine(f"sqlite:///{tmp_path / 'external.db'}")
    try:
        with _factory_client(factory, config, engine, **overrides) as client:
            client.logger.info("two-stage filename provenance marker")
    finally:
        engine.dispose()
    if kind == "bare":
        target = work / "override" / "requested.log"
    elif kind == "absolute":
        target = Path(filename)
    elif kind == "own-directory":
        target = config_file.parent / filename
    else:
        target = config_file.parent / "requested.log"
    assert _files(tmp_path) == [target]
    assert "two-stage filename provenance marker" in target.read_text()
    if kind != "bare":
        assert not (work / "override").exists()
    assert not any(key.startswith("_log_") for key in config.to_dict())


@pytest.mark.parametrize("destination", ["file", "directory", "both", "flag-file", "flag-dir"])
def test_refused_config_uses_environment_logging_with_independent_flag_precedence(
    tmp_path, destination
):
    project = _project(tmp_path)
    config = project / "d.yaml"
    config.write_text("database: [malformed\n")
    env = {"DBLIFT_LOG_FORMAT": "json"}
    flags = []
    if destination != "directory":
        env["DBLIFT_LOG_FILE"] = "environment.json"
    if destination != "file":
        env["DBLIFT_LOG_DIR"] = "environment"
    if destination == "flag-file":
        flags = ["--log-file", "flag.json"]
    elif destination == "flag-dir":
        flags = ["--log-dir", "flags"]
    proc = _run(
        tmp_path,
        ["--config", str(config), *flags, "db", "check-connection", "--format", "json"],
        env=env,
    )
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert json.loads(proc.stdout)["success"] is False
    assert "Traceback" not in proc.stdout + proc.stderr
    logs = _files(tmp_path)
    assert len(logs) == 1
    target_dir = tmp_path / "cwd"
    if destination == "flag-dir":
        target_dir /= "flags"
    elif destination != "file":
        target_dir /= "environment"
    assert logs[0].parent == target_dir
    if destination != "directory":
        assert logs[0].name == ("flag.json" if destination == "flag-file" else "environment.json")
    json.loads(logs[0].read_text())
    assert "Error creating configuration" in logs[0].read_text()
