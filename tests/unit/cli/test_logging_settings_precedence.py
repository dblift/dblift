"""``log_dir`` and ``log_format`` follow the same precedence as every other setting.

``dblift config`` lists both, but only the flags used to take effect: the parser
declared non-empty defaults, so a flag value always won over the YAML file and
the environment. Each test runs the real CLI in a subprocess against a SQLite
file and looks at where the log files land and in which format.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = [pytest.mark.unit]

_DBLIFT = str(Path(sys.executable).parent / "dblift")


def _run(tmp_path: Path, *, yaml_extra: str = "", env=None, flags=()):
    (tmp_path / "mig").mkdir(exist_ok=True)
    (tmp_path / "mig" / "V1__a.sql").write_text("CREATE TABLE a (id INTEGER PRIMARY KEY);\n")
    (tmp_path / "d.yaml").write_text(
        f"database:\n  url: sqlite:///{tmp_path / 't.db'}\nmigrations:\n  directory: mig\n"
        + yaml_extra
    )
    run_env = {k: v for k, v in os.environ.items() if not k.startswith("DBLIFT_")}
    run_env["HOME"] = str(tmp_path)
    run_env.update(env or {})
    proc = subprocess.run(
        [_DBLIFT, *flags, "--config", "d.yaml", "migrate"],
        cwd=tmp_path,
        env=run_env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    return proc


def _files(tmp_path: Path, directory: str):
    d = tmp_path / directory
    return sorted(p.suffix for p in d.iterdir()) if d.is_dir() else []


def test_yaml_log_dir_and_log_format_apply(tmp_path):
    _run(tmp_path, yaml_extra="log_dir: ylogs\nlog_format: json\n")
    assert _files(tmp_path, "ylogs") == [".json"]
    assert not (tmp_path / "logs").exists()


def test_env_log_dir_and_log_format_apply(tmp_path):
    _run(tmp_path, env={"DBLIFT_LOG_DIR": "elogs", "DBLIFT_LOG_FORMAT": "json"})
    assert _files(tmp_path, "elogs") == [".json"]
    assert not (tmp_path / "logs").exists()


def test_env_beats_yaml(tmp_path):
    _run(
        tmp_path,
        yaml_extra="log_dir: ylogs\nlog_format: html\n",
        env={"DBLIFT_LOG_DIR": "elogs", "DBLIFT_LOG_FORMAT": "json"},
    )
    assert _files(tmp_path, "elogs") == [".json"]
    assert not (tmp_path / "ylogs").exists()


def test_flag_beats_env_and_yaml(tmp_path):
    _run(
        tmp_path,
        yaml_extra="log_dir: ylogs\nlog_format: html\n",
        env={"DBLIFT_LOG_DIR": "elogs", "DBLIFT_LOG_FORMAT": "html"},
        flags=("--log-dir", "flogs", "--log-format", "json"),
    )
    assert _files(tmp_path, "flogs") == [".json"]
    assert not (tmp_path / "elogs").exists()
    assert not (tmp_path / "ylogs").exists()


def test_defaults_are_unchanged(tmp_path):
    _run(tmp_path)
    assert _files(tmp_path, "logs") == [".log"]


def test_invalid_format_from_the_environment_is_rejected(tmp_path):
    (tmp_path / "mig").mkdir()
    (tmp_path / "d.yaml").write_text(
        f"database:\n  url: sqlite:///{tmp_path / 't.db'}\nmigrations:\n  directory: mig\n"
    )
    env = {k: v for k, v in os.environ.items() if not k.startswith("DBLIFT_")}
    env.update(HOME=str(tmp_path), DBLIFT_LOG_FORMAT="bogus")
    proc = subprocess.run(
        [_DBLIFT, "--config", "d.yaml", "migrate"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 2
    assert "Invalid log format: bogus" in proc.stderr
