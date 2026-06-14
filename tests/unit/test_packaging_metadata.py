"""Packaging metadata contract tests."""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from scripts import build_distributions

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
def test_distribution_manifest_lists_required_files_and_checksums(tmp_path, monkeypatch):
    dist_dir = tmp_path / "dblift-1.2.3-linux-x86_64"
    dist_dir.mkdir()
    for name in ["README.md", "LICENSE", "dblift", "__init__.py"]:
        (dist_dir / name).write_text("content", encoding="utf-8")
    for dirname in ["api", "cli", "config", "core", "db"]:
        pkg = dist_dir / dirname
        pkg.mkdir()
        (pkg / "__init__.py").write_text("", encoding="utf-8")
    native_drivers = dist_dir / "native_drivers"
    native_drivers.mkdir()
    (native_drivers / "psycopg.txt").write_text("psycopg", encoding="utf-8")
    monkeypatch.setattr(build_distributions.platform, "python_version", lambda: "3.11.8")
    monkeypatch.setenv("GITHUB_SHA", "abc123")

    manifest = build_distributions.build_distribution_manifest(
        dist_dir,
        project_root=ROOT,
        version="1.2.3",
        system="linux",
        machine="x86_64",
        artifact_type="archive",
    )

    paths = {entry["path"] for entry in manifest["files"]}
    assert {"README.md", "LICENSE", "dblift", "api/__init__.py", "db/__init__.py"} <= paths
    assert manifest["version"] == "1.2.3"
    assert manifest["platform"] == "linux"
    assert manifest["architecture"] == "x86_64"
    assert manifest["build_python"] == "3.11.8"
    assert manifest["source_commit"] == "abc123"
    assert manifest["native_drivers"] == ["psycopg.txt"]
    assert all(len(entry["sha256"]) == 64 for entry in manifest["files"])


@pytest.mark.unit
def test_write_distribution_manifest_omits_manifest_self_hash(tmp_path):
    dist_dir = tmp_path / "dist"
    dist_dir.mkdir()
    (dist_dir / "README.md").write_text("content", encoding="utf-8")

    manifest_path = build_distributions.write_distribution_manifest(
        dist_dir,
        project_root=ROOT,
        version="1.0.0",
        system="darwin",
        machine="arm64",
        artifact_type="executable",
    )

    assert manifest_path.is_file()
    assert "DISTRIBUTION-MANIFEST.json" not in manifest_path.read_text(encoding="utf-8")
