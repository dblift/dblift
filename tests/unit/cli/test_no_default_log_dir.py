"""No log file is written unless the user asks for one.

Logging goes to the console only, unless a log directory or a log file is
requested (``--log-dir``, ``--log-file``, ``DBLIFT_LOG_DIR``, ``log_dir`` or
``logging.directory`` in the configuration file). Each CLI test runs the
installed ``dblift`` script in a subprocess against an empty working directory.
"""

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
    """A SQLite project under ``tmp_path/project``; the working dir is ``tmp_path/cwd``."""
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
    tmp_path: Path,
    args: List[str],
    *,
    env: Optional[Dict[str, str]] = None,
    cwd: Optional[Path] = None,
) -> "subprocess.CompletedProcess[str]":
    run_env = {k: v for k, v in os.environ.items() if not k.startswith("DBLIFT_")}
    run_env["HOME"] = str(tmp_path / "home")
    run_env.update(env or {})
    return subprocess.run(
        [_dblift_script(), *args],
        cwd=cwd or tmp_path / "cwd",
        env=run_env,
        capture_output=True,
        text=True,
        timeout=120,
    )


def _log_files(root: Path) -> List[Path]:
    return sorted(p for p in root.rglob("*") if p.suffix in (".log", ".json", ".html"))


def test_command_without_log_settings_writes_no_log_file_anywhere(tmp_path):
    project = _project(tmp_path)
    proc = _run(tmp_path, ["--config", str(project / "d.yaml"), "info"])
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert list((tmp_path / "cwd").iterdir()) == []
    assert not (project / "logs").exists()
    assert _log_files(tmp_path) == []


def test_mutating_command_without_log_settings_writes_no_log_file(tmp_path):
    project = _project(tmp_path)
    proc = _run(tmp_path, ["--config", str(project / "d.yaml"), "migrate"])
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert list((tmp_path / "cwd").iterdir()) == []
    assert _log_files(tmp_path) == []


def test_check_connection_without_log_settings_writes_no_log_file(tmp_path):
    project = _project(tmp_path)
    proc = _run(
        tmp_path,
        ["db", "check-connection", "--db-url", f"sqlite:///{project / 't.db'}"],
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert list((tmp_path / "cwd").iterdir()) == []
    assert _log_files(tmp_path) == []


@pytest.mark.skipif(
    sys.platform == "win32" or (hasattr(os, "geteuid") and os.geteuid() == 0),
    reason="needs POSIX permissions enforced for a non-root user",
)
def test_read_only_working_directory_no_longer_fails(tmp_path):
    project = _project(tmp_path)
    cwd = tmp_path / "cwd"
    cwd.chmod(0o555)
    try:
        proc = _run(tmp_path, ["--config", str(project / "d.yaml"), "info"], cwd=cwd)
    finally:
        cwd.chmod(0o755)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "cannot write log file" not in proc.stderr


def test_log_dir_flag_writes_there(tmp_path):
    project = _project(tmp_path)
    target = tmp_path / "flaglogs"
    proc = _run(tmp_path, ["--config", str(project / "d.yaml"), "--log-dir", str(target), "info"])
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert len(_log_files(target)) == 1
    assert list((tmp_path / "cwd").iterdir()) == []


def test_log_dir_flag_honours_log_format(tmp_path):
    project = _project(tmp_path)
    target = tmp_path / "jsonlogs"
    proc = _run(
        tmp_path,
        [
            "--config",
            str(project / "d.yaml"),
            "--log-dir",
            str(target),
            "--log-format",
            "json",
            "info",
        ],
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert [p.suffix for p in _log_files(target)] == [".json"]


def test_log_dir_flag_with_check_connection_writes_there(tmp_path):
    project = _project(tmp_path)
    target = tmp_path / "ccLogs"
    proc = _run(
        tmp_path,
        [
            "--log-dir",
            str(target),
            "db",
            "check-connection",
            "--db-url",
            f"sqlite:///{project / 't.db'}",
        ],
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert len(_log_files(target)) == 1
    assert list((tmp_path / "cwd").iterdir()) == []


def test_yaml_log_dir_writes_next_to_the_file(tmp_path):
    project = _project(tmp_path, "log_dir: ylogs\n")
    proc = _run(tmp_path, ["--config", str(project / "d.yaml"), "info"])
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert len(_log_files(project / "ylogs")) == 1
    assert list((tmp_path / "cwd").iterdir()) == []


def test_yaml_logging_directory_writes_next_to_the_file(tmp_path):
    project = _project(tmp_path, "logging:\n  directory: nested_logs\n")
    proc = _run(tmp_path, ["--config", str(project / "d.yaml"), "info"])
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert len(_log_files(project / "nested_logs")) == 1
    assert list((tmp_path / "cwd").iterdir()) == []


def test_env_log_dir_writes_there(tmp_path):
    project = _project(tmp_path)
    target = tmp_path / "envlogs"
    proc = _run(
        tmp_path,
        ["--config", str(project / "d.yaml"), "info"],
        env={"DBLIFT_LOG_DIR": str(target)},
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert len(_log_files(target)) == 1


def test_log_file_flag_alone_is_a_request_for_a_file(tmp_path):
    project = _project(tmp_path)
    proc = _run(tmp_path, ["--config", str(project / "d.yaml"), "--log-file", "run.log", "info"])
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert (tmp_path / "cwd" / "run.log").is_file()
    assert not (tmp_path / "cwd" / "logs").exists()


def test_log_file_flag_with_directory_part_writes_there(tmp_path):
    project = _project(tmp_path)
    target = tmp_path / "somewhere" / "run.log"
    proc = _run(tmp_path, ["--config", str(project / "d.yaml"), "--log-file", str(target), "info"])
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert target.is_file()
    assert not (tmp_path / "cwd" / "logs").exists()


def test_log_dir_logs_keeps_the_old_layout(tmp_path):
    project = _project(tmp_path)
    proc = _run(tmp_path, ["--config", str(project / "d.yaml"), "--log-dir", "logs", "info"])
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert len(_log_files(tmp_path / "cwd" / "logs")) == 1
