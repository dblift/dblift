"""Connection utility logs describe the same outcome as its structured response."""

import argparse
import json

import pytest

from dblift.cli import db_utils
from dblift.config.dblift_config import DbliftConfig
from tests.unit.cli.test_requested_log_file_cli import _project, _run

pytestmark = [pytest.mark.unit]


def test_real_connection_failure_is_recorded_in_the_requested_json_log(tmp_path):
    project = _project(tmp_path)
    (project / "t.db").mkdir()
    target = tmp_path / "connection.json"
    proc = _run(
        tmp_path,
        [
            "--config",
            str(project / "d.yaml"),
            "--log-format",
            "json",
            "--log-file",
            str(target),
            "db",
            "check-connection",
            "--format",
            "json",
        ],
    )
    assert proc.returncode == 1, proc.stdout + proc.stderr
    response = json.loads(proc.stdout)
    assert response["success"] is False
    log = json.loads(target.read_text())
    assert log["status"] == "FAILED"
    assert log["error"] == response["error"]


@pytest.mark.parametrize("failure", ["missing-parameters", "provider-refusal"])
def test_utility_failure_before_connection_has_a_truthful_json_log(
    tmp_path, monkeypatch, capsys, failure
):
    config = DbliftConfig.from_dict(
        {"database": {"type": "sqlite", "path": str(tmp_path / "app.db")}}
    )
    if failure == "missing-parameters":
        # This direct-call guard also accepts legacy/partially constructed configurations.
        config.database.url = None
        config.database.path = None
    else:

        def refuse_provider(*args, **kwargs):
            raise ValueError("provider unavailable")

        monkeypatch.setattr(db_utils.ProviderRegistry, "create_provider", refuse_provider)
    monkeypatch.setattr(db_utils, "load_config", lambda *args: config)
    target = tmp_path / "failure.json"
    args = argparse.Namespace(
        config=None,
        format="json",
        log_file=str(target),
        log_dir=None,
        log_format="json",
        log_level="info",
    )
    assert db_utils.check_connection(args) == 1
    response = json.loads(capsys.readouterr().out)
    assert response["success"] is False
    log = json.loads(target.read_text())
    assert log["status"] == "FAILED"
    assert log["error"] == response["error"]
