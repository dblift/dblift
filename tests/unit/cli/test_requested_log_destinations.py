"""Requested log destinations survive the complete CLI configuration path."""

import re

import pytest

from tests.unit.cli.test_requested_log_file_cli import _files, _project, _run

pytestmark = [pytest.mark.unit]


@pytest.mark.parametrize(
    "extra, directory, filename",
    [
        ("log_dir: configured\n", "project/configured", None),
        ("logging:\n  directory: configured\n", "project/configured", None),
        ("log_file: requested.log\n", "project", "requested.log"),
        ("logging:\n  file: requested.log\n", "project", "requested.log"),
    ],
    ids=["flat-directory", "nested-directory", "flat-file", "nested-file"],
)
def test_check_connection_uses_the_configured_destination(tmp_path, extra, directory, filename):
    project = _project(tmp_path, extra)
    proc = _run(tmp_path, ["--config", str(project / "d.yaml"), "db", "check-connection"])
    assert proc.returncode == 0, proc.stdout + proc.stderr
    logs = _files(tmp_path)
    assert len(logs) == 1
    assert logs[0].parent == tmp_path / directory
    if filename is not None:
        assert logs[0].name == filename
    assert (project / "t.db").is_file()
    assert not (tmp_path / "cwd" / "logs").exists()


@pytest.mark.parametrize("destination", ["directory", "file"])
def test_check_connection_environment_destination_beats_config(tmp_path, destination):
    project = _project(tmp_path, "logging:\n  directory: configured\n  file: configured.log\n")
    env = {"DBLIFT_LOG_DIR": "environment"}
    if destination == "file":
        env["DBLIFT_LOG_FILE"] = "environment.log"
    proc = _run(
        tmp_path,
        ["--config", str(project / "d.yaml"), "db", "check-connection"],
        env=env,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    expected_name = "environment.log" if destination == "file" else "configured.log"
    assert _files(tmp_path) == [tmp_path / "cwd" / "environment" / expected_name]
    assert not (project / "configured").exists()


def test_check_connection_environment_filename_overrides_a_config_only_filename(tmp_path):
    project = _project(tmp_path, "logging:\n  file: configured.log\n")
    proc = _run(
        tmp_path,
        ["--config", str(project / "d.yaml"), "db", "check-connection"],
        env={"DBLIFT_LOG_FILE": "environment.log"},
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert _files(tmp_path) == [tmp_path / "cwd" / "environment.log"]


def test_check_connection_flags_beat_environment_and_nested_config(tmp_path):
    project = _project(tmp_path, "logging:\n  directory: configured\n  file: configured.log\n")
    proc = _run(
        tmp_path,
        [
            "--config",
            str(project / "d.yaml"),
            "--log-dir",
            "flags",
            "--log-file",
            "flags.log",
            "db",
            "check-connection",
        ],
        env={"DBLIFT_LOG_DIR": "environment", "DBLIFT_LOG_FILE": "environment.log"},
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert _files(tmp_path) == [tmp_path / "cwd" / "flags" / "flags.log"]
    assert not (project / "configured").exists()
    assert not (tmp_path / "cwd" / "environment").exists()


@pytest.mark.parametrize(
    "extra, relative",
    [
        ("log_file: requested.log\n", "requested.log"),
        ("logging:\n  file: requested.log\n", "requested.log"),
        ("logging:\n  directory: configured\n  file: requested.log\n", "configured/requested.log"),
    ],
    ids=["flat-file", "nested-file", "nested-directory-and-file"],
)
def test_info_uses_the_config_relative_filename(tmp_path, extra, relative):
    project = _project(tmp_path, extra)
    proc = _run(tmp_path, ["--config", str(project / "d.yaml"), "info"])
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert _files(tmp_path) == [project / relative]
    assert not (tmp_path / "cwd" / "configured").exists()


@pytest.mark.parametrize("source", ["flag", "environment"])
def test_info_filename_override_stays_relative_to_the_working_directory(tmp_path, source):
    project = _project(tmp_path, "logging:\n  file: configured.log\n")
    flags = ["--log-file", "override.log"] if source == "flag" else []
    env = {"DBLIFT_LOG_FILE": "override.log"} if source == "environment" else {}
    proc = _run(tmp_path, ["--config", str(project / "d.yaml"), *flags, "info"], env=env)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert _files(tmp_path) == [tmp_path / "cwd" / "override.log"]


@pytest.mark.parametrize("command", [["info"], ["db", "check-connection"]], ids=["info", "check"])
def test_unusable_log_file_parent_reports_the_friendly_error(tmp_path, command):
    project = _project(tmp_path)
    (tmp_path / "cwd" / "blocked").write_text("A file cannot be a log directory.\n")
    proc = _run(
        tmp_path,
        ["--config", str(project / "d.yaml"), "--log-file", "blocked/requested.log", *command],
    )
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "Error: cannot write log file" in proc.stderr
    assert "Traceback" not in proc.stdout + proc.stderr
    assert _files(tmp_path) == []


@pytest.mark.parametrize("command", [["info"], ["db", "check-connection"]], ids=["info", "check"])
def test_absolute_filename_does_not_create_the_unused_log_directory(tmp_path, command):
    project = _project(tmp_path)
    target = tmp_path / "actual" / "requested.log"
    proc = _run(
        tmp_path,
        [
            "--config",
            str(project / "d.yaml"),
            "--log-dir",
            "unused",
            "--log-file",
            str(target),
            *command,
        ],
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert _files(tmp_path) == [target]
    assert not (tmp_path / "cwd" / "unused").exists()


@pytest.mark.parametrize("command", [["info"], ["db", "check-connection"]], ids=["info", "check"])
def test_no_location_requested_writes_no_log_file(tmp_path, command):
    project = _project(tmp_path)
    proc = _run(tmp_path, ["--config", str(project / "d.yaml"), *command])
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert _files(tmp_path) == []
    assert not (tmp_path / "cwd" / "logs").exists()
    assert not (project / "logs").exists()


def test_timestamp_pattern_produces_the_actual_requested_cli_file(tmp_path):
    project = _project(tmp_path)
    proc = _run(
        tmp_path,
        [
            "--config",
            str(project / "d.yaml"),
            "--log-file",
            "out/<timestamp>/requested-<timestamp>.log",
            "info",
        ],
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    logs = _files(tmp_path)
    assert len(logs) == 1
    relative = logs[0].relative_to(tmp_path / "cwd")
    match = re.fullmatch(r"out/(\d{8}_\d{6})/requested-\1\.log", relative.as_posix())
    assert match is not None, relative
    assert logs[0].read_text()
    assert not (tmp_path / "cwd" / "out" / "<timestamp>").exists()
