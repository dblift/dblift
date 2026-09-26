"""The forking guide names real files: every repository path in it must exist."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

pytestmark = [pytest.mark.unit]

ROOT = Path(__file__).resolve().parents[3]
GUIDE = ROOT / "docs" / "developer-guide" / "forking.md"

# Backticked tokens that look like repository paths: a known top-level
# directory or file, followed by a slash-separated path. Angle-bracket
# placeholders such as ``db/plugins/<engine>/`` are skipped.
_PATH_TOKEN = re.compile(
    r"`((?:dblift|tests|docs|packages|scripts)/[A-Za-z0-9_./-]*|"
    r"pyproject\.toml|\.importlinter|CONTRIBUTING\.md)`"
)


def _paths_named_in_guide() -> list[str]:
    text = GUIDE.read_text(encoding="utf-8")
    return sorted({m.group(1).rstrip("/") for m in _PATH_TOKEN.finditer(text)})


def test_guide_names_at_least_the_core_files() -> None:
    named = _paths_named_in_guide()
    for expected in (
        "dblift/core/constants.py",
        "dblift/core/seams",
        "dblift/core/premium_manifest.py",
        "dblift/cli/extensions.py",
        "tests/unit/core/test_product_constants.py",
    ):
        assert expected in named


def test_every_path_named_in_guide_exists() -> None:
    missing = [p for p in _paths_named_in_guide() if not (ROOT / p).exists()]
    assert missing == []
