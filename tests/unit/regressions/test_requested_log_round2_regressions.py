"""Actual log sinks and late utility errors retain the selected destination and outcome."""

import argparse
import json
from unittest.mock import Mock

import pytest

from dblift.cli import db_utils
from dblift.core.logger import DbliftLogger, LogFactory, LogFormat
from tests.unit.api.test_requested_log_file_api import _project as _api_project
from tests.unit.cli.test_requested_log_file_cli import _files, _project, _run

pytestmark = [pytest.mark.unit]


@pytest.mark.parametrize("selection", ["configure", "reuse"])
@pytest.mark.parametrize("log_format", [LogFormat.TEXT, LogFormat.JSON, LogFormat.HTML])
@pytest.mark.parametrize("name", ["actual", "literal-<timestamp>-<format>"])
def test_existing_file_factory_constructs_only_the_selected_literal_sink(
    tmp_path, selection, log_format, name
):
    extension = "log" if log_format == LogFormat.TEXT else log_format.value
    target = tmp_path / f"{name}.{extension}"
    target.touch()
    LogFactory.reset()
    try:
        options = {"log_file": str(target)} if selection == "configure" else {}
        LogFactory.configure(tmp_path, log_format, use_console=False, **options)
        if selection == "reuse":
            LogFactory.use_existing_log_file(target)
        log = LogFactory.get_log("requested")
        log.info("selected literal sink marker")
        log.close()
        assert _files(tmp_path) == [target]
        assert target.stat().st_size > 0
        if log_format == LogFormat.JSON:
            json.loads(target.read_text())
        elif log_format == LogFormat.TEXT:
            assert "selected literal sink marker" in target.read_text()
    finally:
        LogFactory.reset()


@pytest.mark.parametrize("selection", ["configure", "reuse"])
@pytest.mark.parametrize("log_format", [LogFormat.TEXT, LogFormat.JSON, LogFormat.HTML])
def test_existing_file_factory_validates_its_actual_final_leaf(tmp_path, selection, log_format):
    target = tmp_path / "occupied.log"
    target.mkdir()
    LogFactory.reset()
    try:
        options = {"log_file": str(target)} if selection == "configure" else {}
        LogFactory.configure(tmp_path, log_format, use_console=False, **options)
        if selection == "reuse":
            LogFactory.use_existing_log_file(target)
        with pytest.raises(OSError):
            LogFactory.get_log("requested")
        assert sorted(tmp_path.iterdir()) == [target]
    finally:
        LogFactory.reset()


@pytest.mark.parametrize("phase", ["version", "display", "close", "success"])
def test_escaping_provider_error_is_captured_before_the_utility_log_closes(
    tmp_path, monkeypatch, capsys, phase
):
    config_file = _api_project(tmp_path, "")
    provider = Mock()
    provider.get_database_version.return_value = "test version"
    marker = f"provider failure in {phase}"
    if phase == "version":
        provider.get_database_version.side_effect = RuntimeError(marker)
    elif phase == "close":
        provider.close.side_effect = RuntimeError(marker)
    monkeypatch.setattr(db_utils.ProviderRegistry, "create_provider", lambda *args: provider)

    def display_url(*args):
        if phase == "display":
            raise RuntimeError(marker)
        return "sqlite:///test.db"

    monkeypatch.setattr(db_utils, "get_provider_display_url", display_url)
    load_calls = []
    original_load = db_utils.load_config

    def load_once(*args):
        load_calls.append(args)
        return original_load(*args)

    monkeypatch.setattr(db_utils, "load_config", load_once)
    close_calls = []
    original_close = DbliftLogger.close

    def close_once(logger):
        close_calls.append(logger)
        original_close(logger)

    monkeypatch.setattr(DbliftLogger, "close", close_once)
    target = tmp_path / "result.json"
    args = argparse.Namespace(
        config=str(config_file),
        format="json",
        log_file=str(target),
        log_dir=None,
        log_format="json",
        log_level="info",
    )
    assert db_utils.check_connection(args) == (0 if phase == "success" else 1)
    captured = capsys.readouterr()
    outcome = json.loads(target.read_text())
    if phase == "success":
        assert json.loads(captured.out)["success"] is True
        assert outcome["status"] == "SUCCESS"
        assert "error" not in outcome
    else:
        assert marker in captured.err
        assert "Command check-connection" not in captured.err
        assert outcome["status"] == "FAILED"
        assert outcome["error"] == marker
    assert len(load_calls) == 1
    assert len(close_calls) == 1
    provider.close.assert_called_once()


@pytest.mark.parametrize("level", ["fish", "warning", "critical"])
@pytest.mark.parametrize("flag_override", [False, True])
def test_refusal_keeps_the_primary_config_error_when_environment_level_is_invalid(
    tmp_path, level, flag_override
):
    project = _project(tmp_path)
    config = project / "d.yaml"
    config.write_text("database: [malformed\n")
    flags = ["--log-level", "debug"] if flag_override else []
    proc = _run(
        tmp_path,
        ["--config", str(config), *flags, "db", "check-connection", "--format", "json"],
        env={
            "DBLIFT_LOG_FILE": "refusal.json",
            "DBLIFT_LOG_FORMAT": "json",
            "DBLIFT_LOG_LEVEL": level,
        },
    )
    assert proc.returncode == 1, proc.stdout + proc.stderr
    response = json.loads(proc.stdout)
    assert response["success"] is False
    assert "Error loading config file" in response["error"]
    assert "Invalid log level" not in proc.stdout + proc.stderr
    target = tmp_path / "cwd" / "refusal.json"
    outcome = json.loads(target.read_text())
    assert outcome["status"] == "FAILED"
    assert response["error"] in outcome["error"]
    assert "Traceback" not in proc.stdout + proc.stderr


def test_valid_config_keeps_normal_invalid_environment_level_validation(tmp_path):
    project = _project(tmp_path)
    proc = _run(
        tmp_path,
        ["--config", str(project / "d.yaml"), "db", "check-connection", "--format", "json"],
        env={"DBLIFT_LOG_LEVEL": "fish"},
    )
    assert proc.returncode != 0
    assert "Invalid log level" in proc.stdout + proc.stderr
    assert _files(tmp_path) == []
