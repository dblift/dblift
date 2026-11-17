"""Logging paths retain their source when independent overrides are merged."""

import pytest

from tests.unit.cli.test_requested_log_file_cli import _files, _project, _run

pytestmark = [pytest.mark.unit]


@pytest.mark.parametrize("command", [["info"], ["db", "check-connection"]])
@pytest.mark.parametrize("source", ["flag", "environment"])
@pytest.mark.parametrize("style", ["flat", "nested"])
def test_directory_only_override_preserves_configured_bare_filename(
    tmp_path, command, source, style
):
    extra = "log_file: requested.log\n" if style == "flat" else "logging:\n  file: requested.log\n"
    project = _project(tmp_path, extra)
    flags = ["--log-dir", "override"] if source == "flag" else []
    env = {"DBLIFT_LOG_DIR": "override"} if source == "environment" else {}
    proc = _run(tmp_path, ["--config", str(project / "d.yaml"), *flags, *command], env=env)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    target = tmp_path / "cwd" / "override" / "requested.log"
    assert _files(tmp_path) == [target]
    assert target.read_text()


@pytest.mark.parametrize("command", [["info"], ["db", "check-connection"]])
@pytest.mark.parametrize("source", ["flag", "environment"])
def test_explicit_subdirectory_filename_uses_its_own_invocation_relative_path(
    tmp_path, command, source
):
    project = _project(tmp_path, "logging:\n  directory: unused\n  file: configured.log\n")
    filename = "requested/output.log"
    flags = ["--log-file", filename] if source == "flag" else []
    env = {"DBLIFT_LOG_FILE": filename} if source == "environment" else {}
    proc = _run(tmp_path, ["--config", str(project / "d.yaml"), *flags, *command], env=env)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    target = tmp_path / "cwd" / filename
    assert _files(tmp_path) == [target]
    assert target.read_text()
    assert not (project / "unused").exists()


@pytest.mark.parametrize("command", [["info"], ["db", "check-connection"]])
def test_configured_subdirectory_filename_is_config_relative(tmp_path, command):
    project = _project(tmp_path, "logging:\n  directory: unused\n  file: own/requested.log\n")
    proc = _run(tmp_path, ["--config", str(project / "d.yaml"), *command])
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert _files(tmp_path) == [project / "own" / "requested.log"]
    assert not (project / "unused").exists()


@pytest.mark.parametrize("command", [["info"], ["db", "check-connection"]])
def test_selected_environment_nested_filename_overrides_root_flat_filename(tmp_path, command):
    project = _project(
        tmp_path,
        "log_file: root.log\nenvironments:\n  selected:\n    logging:\n      file: selected.log\n",
    )
    proc = _run(
        tmp_path,
        ["--config", str(project / "d.yaml"), "--env", "selected", *command],
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert _files(tmp_path) == [project / "selected.log"]
