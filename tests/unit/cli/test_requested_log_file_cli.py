"""Precedence and placement of requested log files on the command line."""

import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional

import pytest

pytestmark = [pytest.mark.unit]


def _dblift_script() -> str:
    candidate = Path(sys.executable).parent / "dblift"
    if candidate.exists():
        return str(candidate)
    found = shutil.which("dblift")
    if not found:
        pytest.skip("dblift console script is not installed")
    return found


def _project(tmp_path: Path, yaml_extra: str = "") -> Path:
    project = tmp_path / "project"
    (project / "mig").mkdir(parents=True)
    (project / "mig" / "V1__a.sql").write_text("CREATE TABLE a (id INTEGER PRIMARY KEY);\n")
    (project / "d.yaml").write_text(
        f"database:\n  url: sqlite:///{project / 't.db'}\nmigrations:\n  directory: "
        f"{project / 'mig'}\n" + yaml_extra
    )
    (tmp_path / "cwd").mkdir(exist_ok=True)
    return project


def _run(
    tmp_path: Path, args: List[str], *, env: Optional[Dict[str, str]] = None
) -> "subprocess.CompletedProcess[str]":
    run_env = {k: v for k, v in os.environ.items() if not k.startswith("DBLIFT_")}
    run_env["HOME"] = str(tmp_path / "home")
    run_env.update(env or {})
    return subprocess.run(
        [_dblift_script(), *args],
        cwd=tmp_path / "cwd",
        env=run_env,
        capture_output=True,
        text=True,
        timeout=120,
    )


def _files(root: Path) -> List[Path]:
    return sorted(p for p in root.rglob("*") if p.suffix in (".log", ".json", ".html"))


def test_log_dir_flag_beats_the_configured_logging_directory(tmp_path):
    project = _project(tmp_path, "logging:\n  directory: configured\n")
    target = tmp_path / "flaglogs"
    proc = _run(tmp_path, ["--config", str(project / "d.yaml"), "--log-dir", str(target), "info"])
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert len(_files(target)) == 1
    assert not (project / "configured").exists()


def test_check_connection_with_log_file_flag_writes_it_to_the_working_directory(tmp_path):
    project = _project(tmp_path)
    proc = _run(
        tmp_path,
        [
            "--log-file",
            "x.log",
            "db",
            "check-connection",
            "--db-url",
            f"sqlite:///{project / 't.db'}",
        ],
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert (tmp_path / "cwd" / "x.log").is_file()
    assert not (tmp_path / "cwd" / "logs").exists()


def test_timestamp_placeholder_in_a_log_file_directory_creates_no_literal_directory(tmp_path):
    project = _project(tmp_path)
    proc = _run(
        tmp_path,
        ["--config", str(project / "d.yaml"), "--log-file", "out/<timestamp>/x.log", "info"],
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert not (tmp_path / "cwd" / "out" / "<timestamp>").exists()


@pytest.mark.skipif(
    sys.platform == "win32" or (hasattr(os, "geteuid") and os.geteuid() == 0),
    reason="needs POSIX permissions enforced for a non-root user",
)
@pytest.mark.parametrize("log_file", ["x.log", "ro/x.log"], ids=["bare_in_cwd", "parent_dir"])
def test_unwritable_log_file_location_reports_the_friendly_error(tmp_path, log_file):
    project = _project(tmp_path)
    cwd = tmp_path / "cwd"
    (cwd / "ro").mkdir()
    cwd.chmod(0o555)
    (cwd / "ro").chmod(0o555)
    try:
        proc = _run(tmp_path, ["--config", str(project / "d.yaml"), "--log-file", log_file, "info"])
    finally:
        (cwd / "ro").chmod(0o755)
        cwd.chmod(0o755)
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "cannot write log file" in proc.stderr
    assert "Traceback" not in proc.stderr
