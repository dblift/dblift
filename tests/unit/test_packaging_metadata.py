"""Packaging metadata contract tests."""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.unit
def test_pyproject_exposes_dblift_console_script():
    with (ROOT / "pyproject.toml").open("rb") as handle:
        pyproject = tomllib.load(handle)

    assert pyproject["project"]["scripts"]["dblift"] == "cli.main:main"


@pytest.mark.unit
def test_pyproject_requires_python_311_or_newer():
    with (ROOT / "pyproject.toml").open("rb") as handle:
        pyproject = tomllib.load(handle)

    assert pyproject["project"]["requires-python"] == ">=3.11"


@pytest.mark.unit
def test_pyproject_packages_report_template():
    with (ROOT / "pyproject.toml").open("rb") as handle:
        pyproject = tomllib.load(handle)

    package_data = pyproject["tool"]["setuptools"]["package-data"]
    assert "reports/templates/*.html" in package_data["core"]
