"""CLI options registered by the pytest-dblift plugin."""

from __future__ import annotations

import subprocess
import sys


def test_help_lists_dblift_url_and_migrations_dir() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "--help"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    help_text = result.stdout
    assert "--dblift-url" in help_text
    assert "--dblift-migrations-dir" in help_text
    assert "--dblift-no-migrate" not in help_text
