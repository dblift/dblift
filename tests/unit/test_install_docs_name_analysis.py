"""Documented installs that go on to run ``dblift`` must include ``analysis``.

The command line defaults to full SQL analysis, which needs SQLGlot. An install
line like ``pip install "dblift[cli,postgresql]"`` followed by ``dblift migrate``
therefore dies with ``No module named 'sqlglot'``. Extras that already carry
``analysis`` (``all``, ``mcp`` and the framework integrations) are exempt.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest
from packaging.requirements import Requirement

pytestmark = [pytest.mark.unit]

ROOT = Path(__file__).resolve().parents[2]
_FENCE = re.compile(r"^\s*```")
_INSTALL = re.compile(r'pip install\s+"?dblift\[([^\]]+)\]')
_CARRIES_ANALYSIS = {"analysis", "all", "mcp", "django", "flask", "fastapi", "dev"}


def _install_lines_in_code_blocks():
    files = [ROOT / "README.md", *sorted((ROOT / "docs").rglob("*.md"))]
    for path in files:
        in_block = False
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if _FENCE.match(line):
                in_block = not in_block
            elif in_block:
                match = _INSTALL.search(line)
                if match:
                    yield path.relative_to(ROOT), number, set(match.group(1).split(","))


def test_documented_installs_include_analysis_or_an_extra_that_carries_it():
    offenders = [
        f"{path}:{number} installs {sorted(extras)}"
        for path, number, extras in _install_lines_in_code_blocks()
        if not extras & _CARRIES_ANALYSIS
    ]
    assert offenders == []


def test_pytest_dblift_depends_on_the_analysis_extra():
    """The plugin builds clients in the default (full) mode."""
    project = tomllib.loads(
        (ROOT / "packages" / "pytest-dblift" / "pyproject.toml").read_text(encoding="utf-8")
    )["project"]
    (requirement,) = [
        Requirement(spec) for spec in project["dependencies"] if spec.startswith("dblift")
    ]
    assert "analysis" in requirement.extras
    assert str(requirement.specifier) == ">=4.9.0"
