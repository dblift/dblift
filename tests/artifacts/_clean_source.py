"""Extract the exact committed OSS source for isolated artifact builds."""

from __future__ import annotations

import io
import subprocess
import tarfile
from pathlib import Path


def archived_source(root: Path, destination: Path) -> Path:
    """Return a clean tracked-source tree, excluding ignored build output."""
    revision = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root, check=True, capture_output=True, text=True
    ).stdout.strip()
    archive = subprocess.run(
        ["git", "archive", "--format=tar", revision], cwd=root, check=True, capture_output=True
    ).stdout
    destination.mkdir()
    with tarfile.open(fileobj=io.BytesIO(archive)) as source:
        source.extractall(destination, filter="data")
    return destination
