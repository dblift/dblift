"""CLI regression tests for the default log file location.

Runs the installed ``dblift`` console script so the whole startup path
(URL parsing -> log configuration -> first log write) is exercised.
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


def _dblift_script() -> str:
    candidate = Path(sys.executable).parent / "dblift"
    if candidate.exists():
        return str(candidate)
    found = shutil.which("dblift")
    if not found:
        pytest.skip("dblift console script is not installed")
    return found


def _run(args, cwd: Path) -> "subprocess.CompletedProcess[str]":
    env = {k: v for k, v in os.environ.items() if not k.startswith("DBLIFT_")}
    return subprocess.run(
        [_dblift_script(), *args],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )


def _deep_sqlite_project(tmp_path: Path) -> Path:
    deep = tmp_path.joinpath(*["nested_directory_level_xx"] * 12)
    (deep / "migrations").mkdir(parents=True)
    return deep


def test_info_with_sqlite_file_in_deeply_nested_dir(tmp_path):
    deep = _deep_sqlite_project(tmp_path)
    url = f"sqlite:///{deep / 'app.db'}"
    assert len(url) > 255

    result = _run(["info", "--db-url", url, "--scripts", str(deep / "migrations")], tmp_path)

    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    assert "File name too long" not in output
    logs = list((tmp_path / "logs").iterdir())
    assert len(logs) == 1
    assert len(logs[0].name) <= 255
    assert "app.db" in logs[0].name


@pytest.mark.skipif(
    sys.platform == "win32" or (hasattr(os, "geteuid") and os.geteuid() == 0),
    reason="needs POSIX permissions enforced for a non-root user",
)
def test_unwritable_log_dir_reports_friendly_error(tmp_path):
    read_only = tmp_path / "ro"
    read_only.mkdir()
    read_only.chmod(0o555)
    try:
        result = _run(
            [
                "info",
                "--db-url",
                f"sqlite:///{tmp_path / 'app.db'}",
                "--log-dir",
                str(read_only),
            ],
            tmp_path,
        )
    finally:
        read_only.chmod(0o755)

    assert result.returncode == 1
    assert "Error: cannot write log file" in result.stderr
    assert "Traceback" not in result.stderr
