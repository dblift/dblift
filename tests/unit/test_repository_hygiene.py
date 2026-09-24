"""Repository-level publication boundaries."""

import re
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


_TRACKING_ID_IN_NAME = re.compile(r"_\d+_\d+\.py$|batch\d+|story_\d")


def test_test_files_are_named_by_subject() -> None:
    """A test file is named after what it tests, not after a ticket or batch number."""
    repository = Path(__file__).resolve().parents[2]

    offenders = sorted(
        str(path.relative_to(repository))
        for path in (repository / "tests").rglob("test_*.py")
        if _TRACKING_ID_IN_NAME.search(path.name)
    )

    assert offenders == []
