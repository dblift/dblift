"""Repository-level publication boundaries."""

import subprocess
from pathlib import Path


def test_internal_planning_artifacts_are_not_tracked() -> None:
    """Keep agent plans and specifications outside the public repository."""
    repository = Path(__file__).resolve().parents[2]

    tracked = subprocess.run(
        ["git", "ls-files", "--", "docs/superpowers"],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()

    assert tracked == []
