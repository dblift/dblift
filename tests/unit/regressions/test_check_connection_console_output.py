"""Recording utility results does not add console completion messages."""

import json

import pytest

from tests.unit.cli.test_requested_log_file_cli import _files, _project, _run

pytestmark = [pytest.mark.unit]


@pytest.mark.parametrize("quiet", [False, True])
@pytest.mark.parametrize("failure", [False, True])
def test_result_logging_preserves_connection_console_output(tmp_path, quiet, failure):
    project = _project(tmp_path)
    if failure:
        (project / "t.db").mkdir()
    flags = ["--quiet"] if quiet else []
    proc = _run(
        tmp_path,
        ["--config", str(project / "d.yaml"), *flags, "db", "check-connection", "--format", "json"],
    )
    assert proc.returncode == int(failure), proc.stdout + proc.stderr
    assert json.loads(proc.stdout)["success"] is not failure
    assert "Command check-connection" not in proc.stderr
    assert _files(tmp_path) == []
