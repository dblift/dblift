"""The two built distributions preserve one owner for every Python file."""

import configparser
import json
import subprocess
import sys
import tarfile
import zipfile
from email.parser import Parser
from pathlib import Path

import pytest
from packaging.requirements import Requirement

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def wheels(tmp_path_factory):
    output = tmp_path_factory.mktemp("distribution-profiles")
    for source in (ROOT, ROOT / "packages" / "dblift"):
        assert (source / "pyproject.toml").is_file(), f"missing distribution project: {source}"
        subprocess.run(
            [
                sys.executable,
                "-m",
                "pip",
                "wheel",
                "--no-deps",
                "--wheel-dir",
                str(output),
                str(source),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
    return {path.name.split("-", 1)[0]: path for path in output.glob("*.whl")}


def _wheel_metadata(path):
    with zipfile.ZipFile(path) as archive:
        files = set(archive.namelist())
        metadata_file = next(name for name in files if name.endswith(".dist-info/METADATA"))
        message = Parser().parsestr(archive.read(metadata_file).decode())
        entries_file = next(
            (name for name in files if name.endswith(".dist-info/entry_points.txt")), None
        )
        entries = configparser.ConfigParser()
        if entries_file:
            entries.read_string(archive.read(entries_file).decode())
    return files, message, entries


def test_core_owns_code_and_bundle_owns_console(wheels):
    assert set(wheels) == {"dblift_core", "dblift"}
    core_files, core, core_entries = _wheel_metadata(wheels["dblift_core"])
    bundle_files, bundle, bundle_entries = _wheel_metadata(wheels["dblift"])
    assert core["Name"] == "dblift-core"
    assert bundle["Name"] == "dblift"
    assert core["Version"] == bundle["Version"]
    assert "dblift/py.typed" in core_files
    assert "dblift/core/logger/templates/report.html" in core_files
    assert not any(name.startswith("dblift/") for name in bundle_files)
    assert not core_entries.has_section("console_scripts")
    assert dict(bundle_entries.items("console_scripts")) == {"dblift": "dblift.cli.main:main"}
    for group in ("dblift.providers", "dblift.provider_descriptors"):
        assert core_entries.has_section(group)
        assert not bundle_entries.has_section(group)


def test_minimal_and_standard_requirements(wheels):
    _, core, _ = _wheel_metadata(wheels["dblift_core"])
    _, bundle, _ = _wheel_metadata(wheels["dblift"])
    core_reqs = [Requirement(value) for value in core.get_all("Requires-Dist", [])]
    plain = {req.name.lower() for req in core_reqs if req.marker is None}
    assert plain == {"pyyaml", "sqlalchemy"}
    extras = {name.lower(): set() for name in core.get_all("Provides-Extra", [])}
    for requirement in core_reqs:
        for extra in extras:
            if requirement.marker and requirement.marker.evaluate({"extra": extra}):
                extras[extra].add(requirement.name.lower())
    assert {"sqlglot"} <= extras["analysis"]
    assert {"rich", "jinja2"} <= extras["presentation"]
    bundle_reqs = [Requirement(value) for value in bundle.get_all("Requires-Dist", [])]
    assert len([req for req in bundle_reqs if req.marker is None]) == 1
    standard = next(req for req in bundle_reqs if req.marker is None)
    assert standard.name == "dblift-core"
    assert standard.extras == {"analysis", "presentation"}
    assert str(standard.specifier) == f"=={bundle['Version']}"


@pytest.mark.parametrize("source_name", ("core", "bundle"))
def test_each_sdist_rebuilds_without_checkout_files(tmp_path, source_name):
    source = ROOT if source_name == "core" else ROOT / "packages" / "dblift"
    archives = tmp_path / "archives"
    archives.mkdir()
    subprocess.run(
        [sys.executable, "-m", "build", "--sdist", "--outdir", str(archives), str(source)],
        check=True,
        capture_output=True,
        text=True,
    )
    sdist = next(archives.glob("*.tar.gz"))
    extracted = tmp_path / "extracted"
    extracted.mkdir()
    with tarfile.open(sdist) as archive:
        tar_names = archive.getnames()
        assert any(name.endswith("/LICENSE") for name in tar_names)
        assert any(name.endswith("/README.md") for name in tar_names)
        archive.extractall(extracted, filter="data")
    project = next(extracted.iterdir())
    wheels = tmp_path / "wheels"
    wheels.mkdir()
    subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "wheel",
            "--no-deps",
            "--wheel-dir",
            str(wheels),
            str(project),
        ],
        check=True,
        capture_output=True,
        text=True,
        cwd=tmp_path,
    )
    files, metadata, _ = _wheel_metadata(next(wheels.glob("*.whl")))
    assert any(name.endswith(".dist-info/licenses/LICENSE") for name in files)
    if source_name == "core":
        assert metadata["Name"] == "dblift-core"
        assert "dblift/py.typed" in files
    else:
        assert metadata["Name"] == "dblift"
        assert not any(name.startswith("dblift/") for name in files)


def test_qualification_candidate_changes_only_archived_version_sites(tmp_path):
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    output = tmp_path / "candidate"
    run = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "build_core_candidate.py"),
            "--revision",
            revision,
            "--output",
            str(output),
        ],
        capture_output=True,
        text=True,
    )
    assert run.returncode == 0, run.stderr
    manifest = json.loads((output / "manifest.json").read_text())
    assert manifest["revision"] == revision
    assert manifest["candidate_version"] == "999.0.0.dev1"
    assert set(manifest["transforms"]) == {
        "pyproject.toml",
        "packages/dblift/pyproject.toml",
        "dblift/__init__.py",
    }
    artifacts = sorted(output.glob("*.whl")) + sorted(output.glob("*.tar.gz"))
    assert len(artifacts) == 4
    assert {path.name for path in artifacts} == set(manifest["sha256"])
    for path in artifacts:
        assert "999.0.0.dev1" in path.name
