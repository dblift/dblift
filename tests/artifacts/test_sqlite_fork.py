"""A SQLite-only fork qualifies as an installed artifact without editing OSS."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tarfile
import zipfile
from email.parser import Parser
from pathlib import Path

import pytest

from scripts.qualify_sqlite_fork import _transform, replace_once

ROOT = Path(__file__).resolve().parents[2]
QUALIFIER = ROOT / "scripts" / "qualify_sqlite_fork.py"


def test_replace_once_rejects_an_unexpected_identity_constant(tmp_path):
    constants = tmp_path / "constants.py"
    constants.write_text('ENV_PREFIX = "CHANGED_"\n')
    with pytest.raises(ValueError, match="exactly one source match"):
        replace_once(constants, 'ENV_PREFIX = "DBLIFT_"', 'ENV_PREFIX = "FORKLIFT_"')
    assert constants.read_text() == 'ENV_PREFIX = "CHANGED_"\n'


def test_invalid_revision_fails_without_a_fork_wheel(tmp_path):
    output = tmp_path / "result.json"
    run = subprocess.run(
        [
            sys.executable,
            str(QUALIFIER),
            "--revision",
            "missing-e3-revision",
            "--output",
            str(output),
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert run.returncode != 0
    result = json.loads(output.read_text())
    assert result["status"] == "fail"
    assert not list(tmp_path.glob("*.whl"))


def test_transformation_refuses_a_drifted_constant(tmp_path):
    revision = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout.strip()
    source = tmp_path / "source"
    source.mkdir()
    archive = subprocess.run(
        ["git", "archive", "--format=tar", revision],
        cwd=ROOT,
        capture_output=True,
        check=True,
    )
    tar_path = tmp_path / "source.tar"
    tar_path.write_bytes(archive.stdout)
    with tarfile.open(tar_path) as tar:
        tar.extractall(source, filter="data")
    constants = source / "dblift/core/constants.py"
    constants.write_text(
        constants.read_text().replace('ENV_PREFIX = "DBLIFT_"', 'ENV_PREFIX = "CHANGED_"')
    )
    with pytest.raises(ValueError, match="ENV_PREFIX"):
        _transform(source)
    assert not list(tmp_path.rglob("*.whl"))


def test_sqlite_fork_wheel_and_source_integrity(tmp_path):
    before = subprocess.run(
        ["git", "status", "--short"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout
    revision = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout.strip()
    output = tmp_path / "result.json"
    run = subprocess.run(
        [sys.executable, str(QUALIFIER), "--revision", revision, "--output", str(output)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert run.returncode == 0, run.stderr + output.read_text() if output.exists() else run.stderr
    result = json.loads(output.read_text())
    assert result["status"] == "pass"
    assert result["revision"] == revision
    wheel = Path(result["wheel"])
    assert wheel.is_file() and wheel.parent == tmp_path
    assert hashlib.sha256(wheel.read_bytes()).hexdigest() == result["wheel_sha256"]
    diff = Path(result["diff"])
    assert diff.is_file()
    assert hashlib.sha256(diff.read_bytes()).hexdigest() == result["diff_sha256"]
    assert set(result["removed_plugins"]) == set(result["original_plugins"]) - {"sqlite"}
    assert result["installed"]["distributions"] == ["dblift-sqlite-fork-fixture"]
    assert result["installed"]["providers"] == ["sqlite"]
    assert result["installed"]["sqlite_migrate"] is True
    assert result["installed"]["history_table"] == "forklift_schema_history"
    assert result["installed"]["lock_table"] == "forklift_migration_lock"
    assert result["installed"]["fork_env_selected"] is True
    assert result["installed"]["original_env_ignored"] is True
    assert "/site-packages/dblift/" in result["installed"]["origin"]
    assert "core-lightweight-e3" not in result["installed"]["origin"]
    with zipfile.ZipFile(wheel) as archive:
        names = archive.namelist()
        metadata = Parser().parsestr(
            archive.read(
                next(name for name in names if name.endswith(".dist-info/METADATA"))
            ).decode()
        )
        assert metadata["Name"] == "dblift-sqlite-fork-fixture"
        assert any(name.endswith("/premium_manifest.py") for name in names)
        assert any(name.startswith("dblift/db/plugins/sqlite/") for name in names)
        assert any(name.startswith("dblift/db/plugins/nosql_base/") for name in names)
        for plugin in result["removed_plugins"]:
            assert not any(name.startswith(f"dblift/db/plugins/{plugin}/") for name in names)
        entries = archive.read(
            next(name for name in names if name.endswith(".dist-info/entry_points.txt"))
        ).decode()
        assert "dblift-fork-fixture = dblift.cli.main:main" in entries
        assert "sqlite = dblift.db.plugins.sqlite.plugin:PLUGIN" in entries
        assert "mysql =" not in entries
    after = subprocess.run(
        ["git", "status", "--short"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout
    assert after == before
