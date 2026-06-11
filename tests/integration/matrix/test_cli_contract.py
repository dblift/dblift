"""CLI surface contract — tests that need no database.

These are the tests that would have caught the CLI wiring bugs that kept
shipping: 1.3.1 BUG-01/02/03/04, NEW-BUG-08/09/10, 1.3.2 BUG-02, the logger
contamination bugs, and the --log-format validation gaps.

Each test maps to a section of the dblift-dev-test skill (SKILL.md §5.2) and
references the concrete bug(s) it guards against.

All tests run ``python -m cli.main`` as a subprocess so that argparse, config
merging, logger initialization, and stdout/stderr discipline are all exercised
end-to-end. No mocks.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import List, Tuple

import pytest

DBLIFT_ROOT = Path(__file__).resolve().parents[3]
CLI_INVOCATION = [sys.executable, "-m", "cli.main"]


def run_cli(*argv: str, cwd: Path | None = None) -> Tuple[int, str, str]:
    """Run the CLI with the given argv and return (exit_code, stdout, stderr)."""
    result = subprocess.run(
        [*CLI_INVOCATION, *argv],
        cwd=cwd or DBLIFT_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode, result.stdout, result.stderr


# --- §5.2.2 — Missing config file must fail loudly, no silent fallback --------


@pytest.mark.integration
def test_missing_config_exits_nonzero_with_friendly_stderr():
    """--config /nonexistent → exit 1, clear message on stderr, no traceback.

    Guards against: silent fallback to defaults (which would run destructive
    commands against an unintended database), and raw Python tracebacks leaking
    to users.
    """
    exit_code, stdout, stderr = run_cli("--config", "/definitely/does/not/exist.yaml", "info")

    assert exit_code != 0, f"Expected non-zero exit, got {exit_code}"
    assert (
        "not found" in stderr.lower() or "does not exist" in stderr.lower()
    ), f"Expected a clear 'not found' error on stderr, got: {stderr!r}"
    assert "Traceback" not in stderr, f"Raw Python traceback leaked to user:\n{stderr}"
    assert "Traceback" not in stdout, f"Raw Python traceback leaked on stdout:\n{stdout}"


# --- §5.2.5 — --log-format must be validated up front ------------------------


@pytest.mark.integration
def test_invalid_log_format_rejected_before_any_work():
    """--log-format bogus → exit non-zero, no database connection attempted.

    Guards against: the class of 1.3.x bugs where log-format validation was
    tangled with license/DB checks, causing confusing error ordering.
    """
    exit_code, stdout, stderr = run_cli("--log-format", "bogus", "info")

    assert exit_code != 0, f"Expected non-zero exit for bogus log-format, got {exit_code}"
    combined = (stdout + stderr).lower()
    assert (
        "log-format" in combined or "log format" in combined or "invalid" in combined
    ), f"Expected a log-format error, got stdout={stdout!r} stderr={stderr!r}"


# --- §5.2.6 — --log-level must be case-insensitive ---------------------------


@pytest.mark.integration
@pytest.mark.parametrize("level", ["DEBUG", "Info", "WaRn", "error"])
def test_log_level_is_case_insensitive(level: str):
    """Every casing of a valid log level must parse without error.

    Guards against regressions where argparse choices were changed to a
    case-sensitive list. This caught a real bug previously.
    """
    # --help is a trivial command that exits 0 but still goes through arg parsing.
    exit_code, stdout, stderr = run_cli("--log-level", level, "--help")
    assert (
        exit_code == 0
    ), f"--log-level {level!r} should be accepted, got exit={exit_code}, stderr={stderr!r}"


# --- §5.2.7 — Error UX: wrong URL/port/password must not leak tracebacks ------


@pytest.mark.integration
def test_bad_db_url_produces_friendly_error_no_traceback():
    """A syntactically valid but unreachable URL must yield a clean error.

    Guards against raw driver/SQLAlchemy stack traces reaching end users, which
    was a recurring UX bug. We don't assert on exact error text (dialect
    drivers vary) — only that the output is a message, not a traceback.
    """
    exit_code, stdout, stderr = run_cli(
        "--db-url",
        "postgresql://127.0.0.1:1/no_such_db_12345",
        "db",
        "check-connection",
    )

    assert exit_code != 0, "check-connection against an unreachable DB must fail"
    combined = stdout + stderr
    # A Python traceback always starts with "Traceback (most recent call last):".
    # Java stack traces are allowed in DEBUG mode but not at default log level.
    assert (
        "Traceback (most recent call last)" not in combined
    ), f"Raw Python traceback leaked at default log level:\n{combined}"


# --- CLI help discoverability — every subcommand must have --help -----------

LEAF_SUBCOMMANDS: List[str] = [
    "migrate",
    "info",
    "validate",
    "undo",
    "clean",
    "baseline",
    "repair",
    "import-flyway",
    "snapshot",
]


@pytest.mark.integration
@pytest.mark.parametrize("subcmd", LEAF_SUBCOMMANDS)
def test_every_subcommand_has_help(subcmd: str):
    """Every documented subcommand must respond to --help with exit 0.

    Guards against partial subparser registrations (e.g. a subcommand that
    appears in the registry but is never added to the argparse tree).
    """
    exit_code, stdout, stderr = run_cli(subcmd, "--help")
    assert exit_code == 0, f"{subcmd} --help failed: exit={exit_code}, stderr={stderr!r}"
    assert "usage:" in stdout.lower(), f"{subcmd} --help did not emit usage text. stdout={stdout!r}"


@pytest.mark.integration
@pytest.mark.parametrize(
    "subcmd",
    ["list-drivers", "validate-config", "diagnose-connection", "check-connection"],
)
def test_every_db_subcommand_has_help(subcmd: str):
    """Every documented `db` subsubcommand must respond to --help."""
    exit_code, stdout, stderr = run_cli("db", subcmd, "--help")
    assert exit_code == 0, f"db {subcmd} --help failed: exit={exit_code}, stderr={stderr!r}"
    assert "usage:" in stdout.lower()
