"""``log_level`` suppresses what is below it, whichever way it was set.

The CLI mapped only the lowercase names the flag produces, so ``ERROR`` or
``WARNING`` from ``DBLIFT_LOG_LEVEL`` or the config file fell back to INFO, and
``logging.level`` was ignored. The Python API built its console and file sinks
without the level, so ``log_level="ERROR"`` still wrote every INFO line.
Each case runs in a subprocess so the real stderr and log files are inspected.
"""

import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

pytestmark = [pytest.mark.unit]

_DBLIFT = str(Path(sys.executable).parent / "dblift")
_PROGRESS = "Successfully applied migration"
_FAILING = "Failed to execute statement"


def _project(tmp_path: Path, yaml_extra: str = "", failing: bool = False) -> None:
    (tmp_path / "mig").mkdir(exist_ok=True)
    (tmp_path / "mig" / "V1__a.sql").write_text("CREATE TABLE a (id INTEGER PRIMARY KEY);\n")
    if failing:
        (tmp_path / "mig" / "V2__bad.sql").write_text("INSERT INTO missing_table VALUES (1);\n")
    (tmp_path / "d.yaml").write_text(
        f"database:\n  url: sqlite:///{tmp_path / 't.db'}\nmigrations:\n  directory: mig\n"
        + yaml_extra
    )


def _env(tmp_path: Path, extra=None):
    env = {k: v for k, v in os.environ.items() if not k.startswith("DBLIFT_")}
    env["HOME"] = str(tmp_path)
    env.update(extra or {})
    return env


def _cli(tmp_path: Path, *, env=None, flags=(), yaml_extra="", failing=False):
    _project(tmp_path, yaml_extra, failing)
    return subprocess.run(
        [_DBLIFT, *flags, "--config", "d.yaml", "migrate"],
        cwd=tmp_path,
        env=_env(tmp_path, env),
        capture_output=True,
        text=True,
        timeout=120,
    )


def _api(tmp_path: Path, level_literal: str, failing: bool = False):
    _project(tmp_path, failing=failing)
    script = textwrap.dedent(f"""
        from dblift.api.client import DBLiftClient
        from dblift.config.dblift_config import DbliftConfig
        cfg = DbliftConfig.from_dict({{
            "database": {{"url": "sqlite:///{tmp_path / 't.db'}"}},
            "migrations": {{"directory": "{tmp_path / 'mig'}"}},
            "log_dir": "{tmp_path / 'apilogs'}",
            {level_literal}
        }})
        DBLiftClient.from_config(cfg).migrate()
        """)
    return subprocess.run(
        [sys.executable, "-c", script],
        cwd=tmp_path,
        env=_env(tmp_path),
        capture_output=True,
        text=True,
        timeout=120,
    )


def _api_log_text(tmp_path: Path) -> str:
    return "".join(p.read_text() for p in (tmp_path / "apilogs").glob("*.log"))


@pytest.mark.parametrize(
    "env",
    [
        {"DBLIFT_LOG_LEVEL": "ERROR"},
        {"DBLIFT_LOG_LEVEL": "WARNING"},
        {"DBLIFT_LOG_LEVEL": "error"},
    ],
)
def test_cli_level_from_environment_hides_progress(tmp_path, env):
    out = _cli(tmp_path, env=env)
    assert out.returncode == 0, out.stderr
    assert _PROGRESS not in out.stdout + out.stderr


@pytest.mark.parametrize("extra", ["log_level: ERROR\n", "logging:\n  level: ERROR\n"])
def test_cli_level_from_yaml_hides_progress(tmp_path, extra):
    out = _cli(tmp_path, yaml_extra=extra)
    assert out.returncode == 0, out.stderr
    assert _PROGRESS not in out.stdout + out.stderr


def test_cli_default_still_shows_progress(tmp_path):
    out = _cli(tmp_path)
    assert _PROGRESS in out.stdout + out.stderr


@pytest.mark.parametrize("level", ["ERROR", "WARNING"])
def test_cli_errors_remain_visible(tmp_path, level):
    out = _cli(tmp_path, env={"DBLIFT_LOG_LEVEL": level}, failing=True)
    assert out.returncode != 0
    assert _FAILING in out.stdout + out.stderr
    assert _PROGRESS not in out.stdout + out.stderr


def test_cli_flag_and_quiet_semantics_are_unchanged(tmp_path):
    flagged = _cli(tmp_path, flags=("--log-level", "error"))
    assert _PROGRESS not in flagged.stdout + flagged.stderr
    (tmp_path / "q").mkdir()
    quiet = _cli(tmp_path / "q", flags=("--quiet",))
    assert _PROGRESS not in quiet.stdout + quiet.stderr
    assert "Command MIGRATE completed successfully" in quiet.stdout + quiet.stderr


@pytest.mark.parametrize("level", ["ERROR", "WARNING"])
def test_api_level_hides_progress_on_console_and_file(tmp_path, level):
    out = _api(tmp_path, f'"log_level": "{level}",')
    assert out.returncode == 0, out.stderr
    assert _PROGRESS not in out.stdout + out.stderr
    assert _PROGRESS not in _api_log_text(tmp_path)


def test_api_error_level_still_reports_errors(tmp_path):
    out = _api(tmp_path, '"log_level": "ERROR",', failing=True)
    assert _FAILING in out.stdout + out.stderr
    assert _FAILING in _api_log_text(tmp_path)


def test_api_info_level_shows_progress(tmp_path):
    out = _api(tmp_path, '"log_level": "INFO",')
    assert _PROGRESS in out.stdout + out.stderr
    assert _PROGRESS in _api_log_text(tmp_path)


def test_api_without_logging_settings_stays_silent(tmp_path):
    _project(tmp_path)
    script = textwrap.dedent(f"""
        from dblift.api.client import DBLiftClient
        from dblift.config.dblift_config import DbliftConfig
        cfg = DbliftConfig.from_dict({{
            "database": {{"url": "sqlite:///{tmp_path / 't.db'}"}},
            "migrations": {{"directory": "{tmp_path / 'mig'}"}},
        }})
        DBLiftClient.from_config(cfg).migrate()
        """)
    out = subprocess.run(
        [sys.executable, "-c", script],
        cwd=tmp_path,
        env=_env(tmp_path),
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert out.returncode == 0, out.stderr
    assert out.stdout + out.stderr == ""


@pytest.mark.parametrize(
    "kwargs",
    [
        {"env": {"DBLIFT_LOG_LEVEL": "loud"}},
        {"yaml_extra": "log_level: loud\n"},
    ],
)
def test_cli_invalid_level_from_environment_or_yaml_exits_2(tmp_path, kwargs):
    out = _cli(tmp_path, **kwargs)
    assert out.returncode == 2, out.stdout + out.stderr
    assert "Invalid log level: loud" in out.stderr


def test_cli_flag_accepts_warning_like_environment_and_yaml(tmp_path):
    out = _cli(tmp_path, flags=("--log-level", "WARNING"))
    assert out.returncode == 0, out.stderr
    assert _PROGRESS not in out.stdout + out.stderr


def test_cli_invalid_flag_still_exits_2(tmp_path):
    out = _cli(tmp_path, flags=("--log-level", "loud"))
    assert out.returncode == 2


@pytest.mark.parametrize("level", ["ERROR", "WARNING"])
def test_api_from_config_log_level_argument_is_honoured(tmp_path, level):
    _project(tmp_path)
    script = textwrap.dedent(f"""
        from dblift.api.client import DBLiftClient
        from dblift.config.dblift_config import DbliftConfig
        cfg = DbliftConfig.from_dict({{
            "database": {{"url": "sqlite:///{tmp_path / 't.db'}"}},
            "migrations": {{"directory": "{tmp_path / 'mig'}"}},
            "log_dir": "{tmp_path / 'apilogs'}",
        }})
        DBLiftClient.from_config(cfg, log_level="{level}").migrate()
        """)
    out = subprocess.run(
        [sys.executable, "-c", script],
        cwd=tmp_path,
        env=_env(tmp_path),
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert out.returncode == 0, out.stderr
    assert _PROGRESS not in out.stdout + out.stderr
    assert (tmp_path / "apilogs").is_dir()  # logging was requested, not dropped
    assert _PROGRESS not in _api_log_text(tmp_path)


def test_api_from_config_log_level_info_argument_turns_logging_on(tmp_path):
    _project(tmp_path)
    script = textwrap.dedent(f"""
        from dblift.api.client import DBLiftClient
        from dblift.config.dblift_config import DbliftConfig
        cfg = DbliftConfig.from_dict({{
            "database": {{"url": "sqlite:///{tmp_path / 't.db'}"}},
            "migrations": {{"directory": "{tmp_path / 'mig'}"}},
        }})
        DBLiftClient.from_config(cfg, log_level="INFO").migrate()
        """)
    out = subprocess.run(
        [sys.executable, "-c", script],
        cwd=tmp_path,
        env=_env(tmp_path),
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert _PROGRESS in out.stdout + out.stderr
